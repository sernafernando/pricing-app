"""Tests for `POST /api/ml-ventas-ops/activity/ping`
(ml-activity-receiver, slice 3).

Covers: `ml_ops.ingest` auth (mirrors
`test_ml_bridge_service_auth.py`), 202 response shape, the drain
scheduled via `BackgroundTasks` (never inline -- design D3, the PR #811
pool-exhaustion shape this project already lived through once), and
flag-off still returning 202 (no-op is handled inside `drain_activity`,
not by this endpoint returning 503).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token
from app.models.permiso import Permiso, RolPermisoBase
from app.models.rol import Rol
from app.models.usuario import AuthProvider, Usuario

PING_PATH = "/api/ml-ventas-ops/activity/ping"

_seq = [0]


@pytest.fixture
def add_task_espia():
    """Replaces `BackgroundTasks.add_task` with a spy that RECORDS without
    RUNNING it. Starlette's TestClient executes background tasks before
    returning control, so without this patch a test cannot honestly claim
    the drain ran outside the request (same precedent/rationale as
    `tests/routers/test_administracion_proveedores_sync_erp.py`)."""
    queued: list[tuple] = []

    def _spy(self, func, *args, **kwargs) -> None:
        queued.append((func, args, kwargs))

    from unittest.mock import patch

    with patch.object(BackgroundTasks, "add_task", _spy):
        yield queued


def _make_permiso(db, codigo: str) -> Permiso:
    p = db.query(Permiso).filter(Permiso.codigo == codigo).first()
    if not p:
        p = Permiso(codigo=codigo, nombre=codigo, categoria="ml_ops")
        db.add(p)
        db.flush()
    return p


def _make_bridge_user(db) -> Usuario:
    _seq[0] += 1
    rol = Rol(
        codigo=f"ML_BRIDGE_PING_{_seq[0]}",
        nombre="ML Webhook Bridge",
        es_sistema=True,
        orden=901,
        activo=True,
    )
    db.add(rol)
    db.flush()

    permiso = _make_permiso(db, "ml_ops.ingest")
    db.add(RolPermisoBase(rol_id=rol.id, permiso_id=permiso.id))
    db.flush()

    user = Usuario(
        username=f"ml-webhook-bridge-{_seq[0]}",
        nombre="ML Webhook Bridge",
        password_hash=None,
        rol=None,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def _make_plain_user(db) -> Usuario:
    _seq[0] += 1
    rol = Rol(
        codigo=f"NO_INGEST_PING_{_seq[0]}",
        nombre="Sin ingest",
        es_sistema=True,
        orden=902,
        activo=True,
    )
    db.add(rol)
    db.flush()
    user = Usuario(
        username=f"no-ingest-ping-{_seq[0]}",
        nombre="No Ingest",
        password_hash=None,
        rol=None,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def _headers(user: Usuario) -> dict:
    token = create_access_token({"sub": user.username}, timedelta(days=90))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


class TestAuth:
    def test_401_without_token(self, client: TestClient):
        resp = client.post(PING_PATH)
        assert resp.status_code == 401

    def test_403_without_ingest_permission(self, client: TestClient, db):
        user = _make_plain_user(db)
        resp = client.post(PING_PATH, headers=_headers(user))
        assert resp.status_code == 403

    def test_202_with_ingest_permission(self, client: TestClient, db, add_task_espia):
        bridge = _make_bridge_user(db)
        resp = client.post(PING_PATH, headers=_headers(bridge))

        assert resp.status_code == 202
        assert resp.json() == {"accepted": True}
        assert len(add_task_espia) == 1


class TestBackgroundScheduling:
    def test_schedules_exactly_one_drain_per_request(self, client: TestClient, db, add_task_espia):
        bridge = _make_bridge_user(db)
        resp = client.post(PING_PATH, headers=_headers(bridge))
        assert resp.status_code == 202

        assert len(add_task_espia) == 1
        func, args, kwargs = add_task_espia[0]
        from app.services.ml_orders_ingestion.activity_receiver_service import drain_activity

        assert func is drain_activity

    def test_request_body_is_ignored(self, client: TestClient, db, add_task_espia):
        """No body model is declared -- an arbitrary JSON body must not
        cause a 422 and must not reach the drain."""
        bridge = _make_bridge_user(db)
        resp = client.post(
            PING_PATH,
            headers=_headers(bridge),
            json={"anything": "the bridge might decide to send"},
        )
        assert resp.status_code == 202


class TestFlagOffStillReturns202:
    def test_flag_off_still_202_no_op_handled_inside_drain(self, client: TestClient, db, monkeypatch, add_task_espia):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        bridge = _make_bridge_user(db)

        resp = client.post(PING_PATH, headers=_headers(bridge))

        # The endpoint itself never checks the flag -- `drain_activity`
        # does, and reports a no-op (`ran=False`, `error=None`), covered
        # in `test_activity_receiver_service.py::TestFlagGate`. This test
        # only proves the router does NOT 503 here (unlike every other
        # route in this file, which is `_require_flag_enabled()`-gated).
        assert resp.status_code == 202
