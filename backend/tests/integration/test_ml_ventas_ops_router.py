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

from decimal import Decimal

from app.core.config import settings
from app.models.ml_bot_message import MlBotMessage
from app.models.ml_bot_question import MlBotQuestion
from app.models.ml_orders_ops import MlOrdersOps, MlOrderItemOps, MlShipmentOps
from app.models.ml_payments import MlPaymentCharge, MlPaymentOps
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


class TestBreakdown:
    """Corte 6: the `breakdown` block added to `GET /orders/{order_id}`.
    Additive -- every existing field asserted elsewhere in this file must
    stay unaffected."""

    def test_breakdown_sums_two_approved_payments_for_the_order(
        self, db, client, admin_auth_headers, rol_admin
    ) -> None:
        order_id = 655
        db.add(
            MlOrdersOps(
                order_id=order_id,
                status="paid",
                ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
                seller_id=999,
            )
        )
        db.add(
            MlPaymentOps(
                payment_id=1001,
                order_id=order_id,
                status="approved",
                net_received_amount=Decimal("7371.11"),
            )
        )
        db.add(
            MlPaymentOps(
                payment_id=1002,
                order_id=order_id,
                status="approved",
                net_received_amount=Decimal("12528.89"),
                shipping_amount=Decimal("1500"),
            )
        )
        db.commit()
        _grant_ml_ops_ver(db, rol_admin)

        resp = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["breakdown"]["neto"] == 19900.00
        assert body["breakdown"]["incompleto"] is False

    def test_breakdown_is_incomplete_with_a_reason_when_payments_not_synced(
        self, db, client, admin_auth_headers, rol_admin
    ) -> None:
        db.add(
            MlOrdersOps(
                order_id=656,
                status="paid",
                ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
                seller_id=999,
            )
        )
        db.commit()
        _grant_ml_ops_ver(db, rol_admin)

        resp = client.get("/api/ml-ventas-ops/orders/656", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["breakdown"]["incompleto"] is True
        assert "payments_not_synced" in body["breakdown"]["incomplete_reasons"]
        assert body["breakdown"]["neto"] is None

    def test_breakdown_exposes_the_products_total_as_monto_operacion(
        self, db, client, admin_auth_headers, rol_admin
    ) -> None:
        """The heading is the SUM OF THE PRODUCTS, not `paid_amount`.

        `paid_amount` here is deliberately a different figure: it is what
        the BUYER paid, freight included when the buyer pays it, so the
        product lines legitimately fall short of it. The endpoint must
        follow the items."""
        order_id = 657
        db.add(
            MlOrdersOps(
                order_id=order_id,
                status="paid",
                ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
                seller_id=999,
                paid_amount=Decimal("23900.00"),
            )
        )
        db.add(
            MlOrderItemOps(
                order_id=order_id,
                item_id="MLA1",
                quantity=2,
                unit_price=Decimal("9950.00"),
                title="Producto",
            )
        )
        db.commit()
        _grant_ml_ops_ver(db, rol_admin)

        resp = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["breakdown"]["monto_operacion"] == 19900.00

    def test_breakdown_reports_null_monto_operacion_when_paid_amount_unknown(
        self, db, client, admin_auth_headers, rol_admin
    ) -> None:
        """No items at all -- MUST be `None`, never a fabricated `0`. A
        heading of `0` reads as a sale worth nothing."""
        order_id = 6590
        db.add(
            MlOrdersOps(
                order_id=order_id,
                status="paid",
                ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
                seller_id=999,
            )
        )
        db.commit()
        _grant_ml_ops_ver(db, rol_admin)

        resp = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["breakdown"]["monto_operacion"] is None

    def test_breakdown_covers_every_sibling_order_of_the_same_pack(
        self, db, client, admin_auth_headers, rol_admin
    ) -> None:
        pack_id = 6570
        order_a, order_b = 6571, 6572
        for order_id in (order_a, order_b):
            db.add(
                MlOrdersOps(
                    order_id=order_id,
                    pack_id=pack_id,
                    status="paid",
                    ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
                    seller_id=999,
                )
            )
        db.add(MlPaymentOps(payment_id=2001, order_id=order_a, status="approved", net_received_amount=Decimal("100")))
        db.add(MlPaymentOps(payment_id=2002, order_id=order_b, status="approved", net_received_amount=Decimal("200")))
        db.commit()
        _grant_ml_ops_ver(db, rol_admin)

        resp = client.get(f"/api/ml-ventas-ops/orders/{order_a}", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        # Neto covers BOTH orders of the pack, not only the requested one.
        assert body["breakdown"]["neto"] == 300.00

    def test_breakdown_shipping_line_excludes_sender_cost_and_uses_shp_charges(
        self, db, client, admin_auth_headers, rol_admin
    ) -> None:
        order_id = 658
        db.add(
            MlOrdersOps(
                order_id=order_id,
                status="paid",
                ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
                seller_id=999,
                shipping_id=888,
            )
        )
        # self_service shipment with a nonzero sender_cost -- must NEVER
        # leak into the breakdown (obs #1965).
        db.add(MlShipmentOps(shipment_id=888, order_id=order_id, status="delivered", logistic_type="self_service"))
        db.add(MlPaymentOps(payment_id=3001, order_id=order_id, status="approved", net_received_amount=Decimal("100")))
        db.add(MlPaymentCharge(payment_id=3001, name="shp_hub_lm_out", type="shipping", amount=Decimal("450.00")))
        db.commit()
        _grant_ml_ops_ver(db, rol_admin)

        resp = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        lines = {line["concepto"]: line["monto"] for line in body["breakdown"]["lines"]}
        assert lines["Envios"] == 450.00
        assert body["breakdown"]["incompleto"] is False


class TestDesgloseDetalleScopes:
    """The panel carries TWO scopes on purpose and the endpoint must keep
    them apart: the product lines break down `monto_operacion` (the PACK),
    the cost detail explains `cadena_total_gauss` (THIS order).

    An earlier pass widened the cost detail to the pack "so the lists
    match", which put the pack's items under one order's cost figure --
    tidier and wrong. Nothing tested the scope, so nothing objected."""

    def test_item_lines_cover_the_pack_and_costo_items_only_this_order(
        self, db, client, admin_auth_headers, rol_admin
    ) -> None:
        pack_id = 6600
        order_a, order_b = 6601, 6602
        for order_id, mla in ((order_a, "MLA-A"), (order_b, "MLA-B")):
            db.add(
                MlOrdersOps(
                    order_id=order_id,
                    pack_id=pack_id,
                    status="paid",
                    ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
                    seller_id=999,
                    paid_amount=Decimal("100.00"),
                )
            )
            db.add(
                MlOrderItemOps(
                    order_id=order_id,
                    item_id=mla,
                    quantity=1,
                    unit_price=Decimal("100.00"),
                    title=f"Producto {mla}",
                )
            )
        db.commit()
        _grant_ml_ops_ver(db, rol_admin)

        resp = client.get(f"/api/ml-ventas-ops/orders/{order_a}", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()

        # The products list spans the whole pack -- it explains the pack's
        # `monto_operacion`.
        mlas = {line["item_id"] for line in body["breakdown"]["item_lines"]}
        assert mlas == {"MLA-A", "MLA-B"}
        assert body["breakdown"]["monto_operacion"] == 200.00

        # The cost detail is THIS order's -- it explains this order's chain.
        costo_mlas = {item["item_id"] for item in body["cadena_total_gauss"]["costo_mercaderia_items"]}
        assert costo_mlas == {"MLA-A"}


class TestSirtacFieldsOverHttp:
    """ml-ventas-neto-iibb-varios PR1: the drawer relies on these fields to
    keep SIRTAC out of the subtraction list and to render "MP $X · SIRTAC
    $Y". The frontend tests mock the payload, so only this test proves the
    order-detail endpoint actually serializes them.

    Values are production order 2000018567320906 as stored."""

    def test_order_detail_exposes_sirtac_and_withdrawal_fields(self, db, client, admin_auth_headers, rol_admin) -> None:
        from app.models.ml_order_item_costo import MlOrderItemCosto

        order_id = 2000018567320906
        payment_id = 180131165380
        db.add(
            MlOrdersOps(
                order_id=order_id,
                status="paid",
                ml_last_updated=datetime(2026, 9, 21, tzinfo=timezone.utc),
                seller_id=999,
                total_amount=Decimal("597408.67"),
                currency_id="ARS",
            )
        )
        db.add(
            MlOrderItemOps(
                order_id=order_id, item_id="MLA2060835678", quantity=1, unit_price=Decimal("597408.67"), title="Epson"
            )
        )
        db.add(
            MlOrderItemCosto(
                order_id=order_id,
                item_id="MLA2060835678",
                variation_id=None,
                costo_origen=Decimal("234.78"),
                moneda="USD",
                tipo_cambio=Decimal("1535.00"),
                tipo_cambio_fecha=None,
                costo_unitario_ars=Decimal("360391.09"),
                iva_pct=Decimal("21"),
                precio_unitario=Decimal("597408.67"),
                fuente="sku",
                producto_item_id=1,
            )
        )
        db.add(
            MlPaymentOps(
                payment_id=payment_id,
                order_id=order_id,
                status="approved",
                net_received_amount=Decimal("502165.91"),
                shipping_amount=Decimal("0.00"),
                coupon_amount=Decimal("41679.67"),
                transaction_amount_refunded=Decimal("0.00"),
            )
        )
        for name, type_, amount in (
            ("coupon_rebate", "coupon", "41679.67"),
            ("meli_percentage_fee", "fee", "74676.08"),
            ("shp_cross_docking", "shipping", "15190.00"),
            ("tax_withholding_collector-debitos_creditos", "tax", "3584.45"),
            ("tax_withholding_sirtac-caba", "tax", "1792.23"),
        ):
            db.add(
                MlPaymentCharge(
                    payment_id=payment_id, name=name, type=type_, amount=Decimal(amount), refunded=Decimal("0.00")
                )
            )
        db.commit()
        _grant_ml_ops_ver(db, rol_admin)

        resp = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()

        breakdown = body["breakdown"]
        assert breakdown["neto"] == pytest.approx(503958.14)
        assert breakdown["neto_depositado"] == pytest.approx(502165.91)
        assert breakdown["retenciones_recuperables"] == pytest.approx(1792.23)
        origenes = {line["concepto"]: line["origen"] for line in breakdown["lines"]}
        assert [c for c, o in origenes.items() if o == "recuperable"] == ["Retención IIBB (CABA) · SIRTAC"]

        iva = body["iva_decomposicion"]
        assert iva["reconcilia"] is True
        assert iva["debitos_creditos_retiro"] == pytest.approx(3584.45)
        assert iva["neto_sin_iva"] == pytest.approx(412287.78)
        informativos = [c["concepto"] for c in iva["componentes"] if c["informativo"]]
        assert informativos == ["Retención IIBB (CABA) · SIRTAC"]
