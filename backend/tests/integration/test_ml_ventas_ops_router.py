"""Integration tests for the sale-centric ML operations router (slice 4).

Covers the two structural guarantees this slice must prove:
- flag OFF -> 503, wrong/no permission -> 403 (spec: Permission-gated access)
- the existing `ml_bot` surface is provably unchanged (design D4: two
  distinct read views over one storage layer, never collapsed) -- this is
  the load-bearing regression test named in the apply prompt.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.models.ml_bot_message import MlBotMessage
from app.models.ml_bot_question import MlBotQuestion
from app.models.ml_orders_ops import MlOrdersOps, MlOrderItemOps, MlShipmentOps
from app.models.permiso import Permiso, RolPermisoBase
from app.models.rma_claim_ml import RmaClaimML
from app.services.ml_orders_ingestion.link_resolver_service import resolve_links


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


def _grant_ml_ops_ver(db, rol_admin) -> None:
    permiso = db.query(Permiso).filter(Permiso.codigo == "ml_ops.ver").first()
    if not permiso:
        permiso = Permiso(
            codigo="ml_ops.ver", nombre="Ver operaciones ML", descripcion="", categoria="ml_ops", orden=200
        )
        db.add(permiso)
        db.flush()
    db.add(RolPermisoBase(rol_id=rol_admin.id, permiso_id=permiso.id))
    db.flush()


def _seed_full_operation(db) -> int:
    order = MlOrdersOps(
        order_id=555,
        pack_id=555,
        status="paid",
        ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
        buyer_id=55,
        seller_id=999,
        total_amount=100,
        shipping_id=777,
    )
    db.add(order)
    db.add(MlOrderItemOps(order_id=555, item_id="MLA1", quantity=1, title="Producto"))
    db.add(MlShipmentOps(shipment_id=777, order_id=555, status="delivered"))
    db.add(RmaClaimML(claim_id=8888, resource_id=555, status="opened"))
    db.add(
        MlBotMessage(
            ml_message_id="msg-x",
            pack_id="555",
            seller_id=999,
            text="hola",
            status="available",
            received_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        )
    )
    db.add(
        MlBotQuestion(
            ml_question_id=1234,
            item_id="MLA1",
            buyer_id=55,
            question_text="hola",
            question_date=datetime(2026, 8, 20, tzinfo=timezone.utc),
        )
    )
    db.flush()
    resolve_links(db)
    db.commit()
    return order.order_id


class TestFlagGate:
    def test_flag_off_returns_503_for_a_user_with_permission(
        self, db, client, admin_auth_headers, rol_admin, monkeypatch
    ):
        """Permission is checked BEFORE the flag (pxq.py precedent, same
        rationale): a user WITHOUT permission always gets 403 regardless of
        flag state, so 503 unambiguously means "you can, but it's off"."""
        _grant_ml_ops_ver(db, rol_admin)
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        resp = client.get("/api/ml-ventas-ops/orders/555", headers=admin_auth_headers)
        assert resp.status_code == 503

    def test_flag_off_still_returns_403_for_a_user_without_permission(self, client, admin_auth_headers, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        resp = client.get("/api/ml-ventas-ops/orders/555", headers=admin_auth_headers)
        assert resp.status_code == 403


class TestPermissionGate:
    def test_user_without_permission_gets_403(self, client, auth_headers):
        resp = client.get("/api/ml-ventas-ops/orders/555", headers=auth_headers)
        assert resp.status_code == 403

    def test_user_with_permission_can_read(self, db, client, admin_auth_headers, rol_admin) -> None:
        order_id = _seed_full_operation(db)
        _grant_ml_ops_ver(db, rol_admin)

        resp = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers)
        assert resp.status_code == 200


class TestSaleCentricView:
    def test_returns_order_items_shipment_claim_and_messages_as_one_operation(
        self, db, client, admin_auth_headers, rol_admin
    ) -> None:
        order_id = _seed_full_operation(db)
        _grant_ml_ops_ver(db, rol_admin)

        resp = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()

        assert body["order"]["order_id"] == order_id
        assert len(body["items"]) == 1
        assert body["items"][0]["item_id"] == "MLA1"
        assert body["shipment"]["shipment_id"] == 777
        assert body["claim"]["claim_id"] == 8888
        assert len(body["messages"]) == 1
        assert len(body["questions"]) == 1

    def test_unknown_order_is_404(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant_ml_ops_ver(db, rol_admin)
        resp = client.get("/api/ml-ventas-ops/orders/99999999", headers=admin_auth_headers)
        assert resp.status_code == 404

    def test_order_with_no_claim_or_conversation_returns_nulls_and_empty_lists(
        self, db, client, admin_auth_headers, rol_admin
    ) -> None:
        db.add(
            MlOrdersOps(
                order_id=556,
                status="paid",
                ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
                seller_id=999,
            )
        )
        db.commit()
        _grant_ml_ops_ver(db, rol_admin)

        resp = client.get("/api/ml-ventas-ops/orders/556", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["claim"] is None
        assert body["shipment"] is None
        assert body["items"] == []
        assert body["messages"] == []
        assert body["questions"] == []


class TestMlBotSurfaceUnchanged:
    """Load-bearing regression (design D3/D4): the resolver and the new
    router must not touch the existing bot-centric surface's behaviour,
    fields, or permissions in any way."""

    def test_ml_bot_questions_endpoint_unaffected_by_seeded_operation_and_resolver_run(
        self, db, client, admin_auth_headers, rol_admin
    ) -> None:
        # ml_bot.ver is a distinct permission from ml_ops.ver -- grant it to
        # prove the two surfaces are independently gated too.
        permiso = Permiso(codigo="ml_bot.ver", nombre="Ver bot", descripcion="", categoria="ml_bot", orden=190)
        db.add(permiso)
        db.flush()
        db.add(RolPermisoBase(rol_id=rol_admin.id, permiso_id=permiso.id))
        db.flush()

        _seed_full_operation(db)  # exercises the resolver against a real question/message

        resp = client.get("/api/ml-bot/questions", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["questions"][0]["ml_question_id"] == 1234
        # The bot surface's own status field is untouched by the resolver.
        assert body["questions"][0]["status"] == "received"
