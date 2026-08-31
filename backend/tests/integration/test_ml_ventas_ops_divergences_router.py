"""Integration tests for the divergence dashboard API (slice 6). Covers
permission BEFORE flag on every endpoint, `ml_ops.ver` for reads vs
`ml_ops.gestionar` for state changes, pagination, and the mandatory
`window_not_enumerable` sentinel never rendering `order_id=0` as an
order."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOpsDivergence
from app.models.permiso import Permiso, RolPermisoBase


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


def _grant(db, rol_admin, codigo: str, es_critico: bool = False) -> None:
    permiso = db.query(Permiso).filter(Permiso.codigo == codigo).first()
    if not permiso:
        permiso = Permiso(
            codigo=codigo, nombre=codigo, descripcion="", categoria="ml_ops", orden=200, es_critico=es_critico
        )
        db.add(permiso)
        db.flush()
    db.add(RolPermisoBase(rol_id=rol_admin.id, permiso_id=permiso.id))
    db.flush()


def _seed_divergence(db, order_id: int = 400, kind: str = "field_mismatch", **kwargs) -> MlOpsDivergence:
    row = MlOpsDivergence(
        order_id=order_id,
        kind=kind,
        field=kwargs.get("field", "status"),
        ml_value=kwargs.get("ml_value", "paid"),
        gbp_value=kwargs.get("gbp_value", "cancelled"),
        state=kwargs.get("state", "open"),
        detected_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
    )
    db.add(row)
    db.commit()
    return row


class TestFlagAndPermissionGateList:
    def test_flag_off_returns_503_for_a_user_with_permission(
        self, db, client, admin_auth_headers, rol_admin, monkeypatch
    ):
        _grant(db, rol_admin, "ml_ops.ver")
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        resp = client.get("/api/ml-ventas-ops/divergences", headers=admin_auth_headers)
        assert resp.status_code == 503

    def test_flag_off_still_returns_403_for_a_user_without_permission(self, client, admin_auth_headers, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        resp = client.get("/api/ml-ventas-ops/divergences", headers=admin_auth_headers)
        assert resp.status_code == 403

    def test_user_without_permission_gets_403(self, client, auth_headers):
        resp = client.get("/api/ml-ventas-ops/divergences", headers=auth_headers)
        assert resp.status_code == 403


class TestListDivergences:
    def test_user_with_ver_can_list(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")
        _seed_divergence(db, order_id=401)

        resp = client.get("/api/ml-ventas-ops/divergences", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["divergences"][0]["order_id"] == 401

    def test_pagination_fields_are_present_and_respected(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")
        for i in range(3):
            _seed_divergence(db, order_id=500 + i)

        resp = client.get("/api/ml-ventas-ops/divergences?limit=2&offset=0", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert body["limit"] == 2
        assert body["offset"] == 0
        assert len(body["divergences"]) == 2

    def test_filters_by_kind_and_state(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")
        _seed_divergence(db, order_id=600, kind="missing_in_gbp", state="open")
        _seed_divergence(db, order_id=601, kind="field_mismatch", state="resolved")

        resp = client.get("/api/ml-ventas-ops/divergences?kind=missing_in_gbp&state=open", headers=admin_auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["divergences"][0]["order_id"] == 600

    def test_invalid_kind_is_422(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")
        resp = client.get("/api/ml-ventas-ops/divergences?kind=bogus", headers=admin_auth_headers)
        assert resp.status_code == 422

    def test_window_not_enumerable_sentinel_is_never_rendered_as_an_order(
        self, db, client, admin_auth_headers, rol_admin
    ) -> None:
        db.add(
            MlOpsDivergence(
                order_id=0,
                kind="window_not_enumerable",
                field="123|456",
                ml_value="2026-08-01T00:00:00+00:00",
                gbp_value="2026-08-01T00:01:00+00:00",
                detected_at=datetime(2026, 8, 30, tzinfo=timezone.utc),
            )
        )
        db.commit()
        _grant(db, rol_admin, "ml_ops.ver")

        resp = client.get("/api/ml-ventas-ops/divergences?kind=window_not_enumerable", headers=admin_auth_headers)
        assert resp.status_code == 200
        row = resp.json()["divergences"][0]
        assert row["order_id"] is None
        assert row["window_from"] == "2026-08-01T00:00:00+00:00"
        assert row["window_to"] == "2026-08-01T00:01:00+00:00"


class TestGetDivergence:
    def test_unknown_id_is_404(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")
        resp = client.get("/api/ml-ventas-ops/divergences/999999", headers=admin_auth_headers)
        assert resp.status_code == 404


class TestUpdateDivergence:
    def test_ver_only_permission_cannot_update_state(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")
        row = _seed_divergence(db, order_id=800)

        resp = client.patch(
            f"/api/ml-ventas-ops/divergences/{row.id}", json={"state": "acknowledged"}, headers=admin_auth_headers
        )
        assert resp.status_code == 403

    def test_gestionar_permission_can_update_state_note_and_assignee(
        self, db, client, admin_auth_headers, rol_admin, admin_user
    ) -> None:
        _grant(db, rol_admin, "ml_ops.gestionar", es_critico=True)
        row = _seed_divergence(db, order_id=801)

        resp = client.patch(
            f"/api/ml-ventas-ops/divergences/{row.id}",
            json={"state": "acknowledged", "note": "investigando", "assigned_to_id": admin_user.id},
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "acknowledged"
        assert body["note"] == "investigando"
        assert body["assigned_to_id"] == admin_user.id

    def test_invalid_state_is_422(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.gestionar", es_critico=True)
        row = _seed_divergence(db, order_id=802)

        resp = client.patch(
            f"/api/ml-ventas-ops/divergences/{row.id}", json={"state": "bogus"}, headers=admin_auth_headers
        )
        assert resp.status_code == 422

    def test_flag_off_returns_503_for_a_user_with_gestionar(
        self, db, client, admin_auth_headers, rol_admin, monkeypatch
    ) -> None:
        _grant(db, rol_admin, "ml_ops.gestionar", es_critico=True)
        row = _seed_divergence(db, order_id=803)
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)

        resp = client.patch(
            f"/api/ml-ventas-ops/divergences/{row.id}", json={"state": "resolved"}, headers=admin_auth_headers
        )
        assert resp.status_code == 503
