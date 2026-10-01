"""ODD `ventas-ml-ui-pendiente` T7: `POST /orders/{id}/resync` and
`GET /sales/sync-status`."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOpsSyncCursor
from app.models.permiso import Permiso, RolPermisoBase
from app.routers import ml_ventas_ops
from app.services.ml_orders_ingestion.resync_service import (
    OrderNotFound,
    ResyncFailed,
    ResyncInProgress,
    ResyncResult,
)


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


def _grant(db, rol, codigo):
    permiso = db.query(Permiso).filter(Permiso.codigo == codigo).first()
    if not permiso:
        permiso = Permiso(codigo=codigo, nombre=codigo, descripcion="", categoria="ml_ops", orden=999)
        db.add(permiso)
        db.flush()
    db.add(RolPermisoBase(rol_id=rol.id, permiso_id=permiso.id))
    db.flush()


class TestResyncEndpoint:
    def test_without_the_resync_permission_it_is_refused_and_nothing_runs(
        self, db, client, admin_auth_headers, rol_admin, monkeypatch
    ):
        _grant(db, rol_admin, "ml_ops.ver")  # seeing sales is not enough
        calls = []
        monkeypatch.setattr(ml_ventas_ops, "resync_order", lambda *a, **k: calls.append(a))

        resp = client.post("/api/ml-ventas-ops/orders/123/resync", headers=admin_auth_headers)

        assert resp.status_code == 403
        assert calls == []

    def test_success(self, db, client, admin_auth_headers, rol_admin, monkeypatch):
        _grant(db, rol_admin, "ml_ops.resincronizar")
        monkeypatch.setattr(
            ml_ventas_ops, "resync_order", lambda db, order_id: ResyncResult(order_id=order_id, order_changed=True)
        )

        resp = client.post("/api/ml-ventas-ops/orders/123/resync", headers=admin_auth_headers)

        assert resp.status_code == 200
        assert resp.json() == {"order_id": 123, "order_changed": True}

    @pytest.mark.parametrize(
        "error,status_code",
        [
            (OrderNotFound(123), 404),
            (ResyncInProgress(123), 409),
            (ResyncFailed("No se pudo traer la venta desde Mercado Libre."), 502),
        ],
    )
    def test_each_failure_is_an_explicit_error(
        self, db, client, admin_auth_headers, rol_admin, monkeypatch, error, status_code
    ):
        _grant(db, rol_admin, "ml_ops.resincronizar")

        def boom(db, order_id):
            raise error

        monkeypatch.setattr(ml_ventas_ops, "resync_order", boom)

        resp = client.post("/api/ml-ventas-ops/orders/123/resync", headers=admin_auth_headers)

        assert resp.status_code == status_code
        body = resp.json()
        message = body["error"]["message"]
        assert message
        if status_code == 502:
            assert "Mercado Libre" in message

    def test_feature_switched_off(self, db, client, admin_auth_headers, rol_admin, monkeypatch):
        _grant(db, rol_admin, "ml_ops.resincronizar")
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        resp = client.post("/api/ml-ventas-ops/orders/123/resync", headers=admin_auth_headers)
        assert resp.status_code == 503


class TestSyncStatus:
    def test_reports_the_most_recent_successful_pass_of_any_source(self, db, client, admin_auth_headers, rol_admin):
        _grant(db, rol_admin, "ml_ops.ver")
        db.add(MlOpsSyncCursor(name="sweep", last_success_at=datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)))
        db.add(MlOpsSyncCursor(name="ml_activity", last_success_at=datetime(2026, 9, 30, 11, 30, tzinfo=timezone.utc)))
        # A backfill is a one-off historical job, not "how fresh is the list".
        db.add(MlOpsSyncCursor(name="backfill", last_success_at=datetime(2026, 9, 30, 23, 0, tzinfo=timezone.utc)))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales/sync-status", headers=admin_auth_headers).json()

        assert body["last_synced_at"].startswith("2026-09-30T11:30")

    def test_null_when_nothing_ever_completed(self, db, client, admin_auth_headers, rol_admin):
        _grant(db, rol_admin, "ml_ops.ver")
        db.add(MlOpsSyncCursor(name="sweep", last_success_at=None))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales/sync-status", headers=admin_auth_headers).json()

        assert body == {"last_synced_at": None}

    def test_needs_ml_ops_ver(self, db, client, admin_auth_headers):
        assert client.get("/api/ml-ventas-ops/sales/sync-status", headers=admin_auth_headers).status_code == 403
