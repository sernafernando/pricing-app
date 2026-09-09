"""Tests for the `ml-webhook-bridge` service-user authentication boundary
(ml-activity-receiver slice 1).

Covers spec domain `ml-ops-service-auth`: a seeded `Usuario`
(`username='ml-webhook-bridge'`, `password_hash=NULL`, `es_sistema` role
holding ONLY `ml_ops.ingest`) authenticates via the standard JWT path,
is granted exactly `ml_ops.ingest`, is denied against every OTHER
`ml-ventas-ops` route (`ml_ops.ver`, `ml_ops.gestionar`), and is killable
via `usuario.activo=False`.

This slice is deliberately INERT: nothing consumes `ml_ops.ingest` yet, so
these tests exercise `require_permission("ml_ops.ingest")` directly (there
is no real protected route until slice 3 adds the ping endpoint) alongside
the two real `ml-ventas-ops` routes that already exist, to prove scope
containment end to end.

Written FIRST (RED phase) per strict TDD.

Run:
    cd backend && source .venv/bin/activate && \
        pytest tests/services/ml_orders_ingestion/test_ml_bridge_service_auth.py -v
"""

from datetime import timedelta

from fastapi import Depends
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.main import app
from app.models.permiso import Permiso, RolPermisoBase
from app.models.rol import Rol
from app.models.usuario import AuthProvider, Usuario
from app.routers.ml_ventas_ops import require_permission

_seq = [0]


def _make_permiso(db, codigo: str) -> Permiso:
    p = db.query(Permiso).filter(Permiso.codigo == codigo).first()
    if not p:
        p = Permiso(codigo=codigo, nombre=codigo, categoria="ml_ops")
        db.add(p)
        db.flush()
    return p


def _make_bridge_user(db) -> Usuario:
    """Mirrors 20260909_seed_ml_bridge_service_user.py's shape: an
    `es_sistema` role holding ONLY `ml_ops.ingest`, and a user with
    `password_hash=NULL`, `activo=True`."""
    _seq[0] += 1
    rol = Rol(
        codigo=f"ML_BRIDGE_{_seq[0]}",
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
        username="ml-webhook-bridge",
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


def _bridge_headers(user: Usuario) -> dict:
    """A real 90-day service token, minted exactly like
    scripts/mint_ml_bridge_token.py mints one."""
    token = create_access_token({"sub": user.username}, timedelta(days=90))
    return {"Authorization": f"Bearer {token}"}


# A throwaway route guarded by `ml_ops.ingest`, registered only for these
# tests -- slice 1 is inert on purpose (no real endpoint requires this
# permission until slice 3's ping handler). Exercising the SAME
# `require_permission()` dependency the ping will use is what actually
# proves the auth plumbing, not a bespoke stand-in.
@app.get("/__test_only/ml_ops_ingest_probe")
def _ml_ops_ingest_probe(current_user: Usuario = Depends(require_permission("ml_ops.ingest"))):
    return {"username": current_user.username}


class TestServiceUserGrantedIngestScope:
    """SC: the bridge token IS accepted wherever `ml_ops.ingest` is
    required."""

    def test_valid_token_granted_ingest_permission(self, client: TestClient, db):
        bridge = _make_bridge_user(db)

        resp = client.get(
            "/__test_only/ml_ops_ingest_probe",
            headers=_bridge_headers(bridge),
        )

        assert resp.status_code == 200
        assert resp.json()["username"] == "ml-webhook-bridge"


class TestServiceTokenDeniedOutsideGrantedScope:
    """SC: the bridge token fails against every OTHER `ml_ops` permission
    -- the whole point of a narrow grant. Mirrors
    `tests/tickets/test_agente_ia_auth.py::TestServiceTokenDeniedOutsideGrantedScope`."""

    def test_403_on_ml_ops_ver_route(self, client: TestClient, db):
        bridge = _make_bridge_user(db)

        resp = client.get("/api/ml-ventas-ops/sales", headers=_bridge_headers(bridge))

        assert resp.status_code == 403

    def test_403_on_ml_ops_gestionar_route(self, client: TestClient, db):
        bridge = _make_bridge_user(db)

        resp = client.patch(
            "/api/ml-ventas-ops/divergences/999999",
            json={"state": "resolved"},
            headers=_bridge_headers(bridge),
        )

        assert resp.status_code == 403


class TestKillSwitch:
    """SC: `usuario.activo=False` -> 401 on the next request with the SAME
    JWT, no new token needed, no deploy."""

    def test_deactivation_kills_the_existing_token(self, client: TestClient, db):
        bridge = _make_bridge_user(db)
        headers = _bridge_headers(bridge)

        ok = client.get("/__test_only/ml_ops_ingest_probe", headers=headers)
        assert ok.status_code == 200

        bridge.activo = False
        db.flush()

        resp = client.get("/__test_only/ml_ops_ingest_probe", headers=headers)
        assert resp.status_code == 401


class TestUserWithoutPermissionDenied:
    """SC: a user who has NOT been granted `ml_ops.ingest` is denied,
    proving the probe route actually enforces the permission rather than
    passing everyone through."""

    def test_403_without_ingest_permission(self, client: TestClient, db):
        _seq[0] += 1
        rol = Rol(
            codigo=f"NO_INGEST_{_seq[0]}",
            nombre="Sin ingest",
            es_sistema=True,
            orden=902,
            activo=True,
        )
        db.add(rol)
        db.flush()

        user = Usuario(
            username=f"no-ingest-{_seq[0]}",
            nombre="No Ingest",
            password_hash=None,
            rol=None,
            rol_id=rol.id,
            auth_provider=AuthProvider.LOCAL,
            activo=True,
        )
        db.add(user)
        db.flush()

        resp = client.get(
            "/__test_only/ml_ops_ingest_probe",
            headers=_bridge_headers(user),
        )

        assert resp.status_code == 403
