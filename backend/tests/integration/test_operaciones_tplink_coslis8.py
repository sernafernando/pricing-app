"""
T-12 — operaciones endpoint uses coslis_id=8 and requires from_date/to_date.

Verifies:
1. fetch_operaciones_con_metricas is called with coslis_id=8 (not 1).
2. Missing from_date or to_date returns 422.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.permiso import Permiso
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario


def _bearer(user: Usuario) -> dict[str, str]:
    token = create_access_token(data={"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def brand_rol_ops(db) -> Rol:
    rol = Rol(codigo="BRAND_OPS", nombre="Brand Ops", es_sistema=False, orden=97, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def perm_ver_ops(db) -> Permiso:
    p = Permiso(
        codigo="dashboard_tplink.ver",
        nombre="Ver dashboard TP-Link",
        descripcion="Access",
        categoria="ventas_ml",
        orden=60,
        es_critico=False,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def user_ops(db, brand_rol_ops, perm_ver_ops) -> Usuario:
    from app.models.permiso import UsuarioPermisoOverride

    user = Usuario(
        username="ops_user",
        email="ops@tplink.com",
        nombre="Ops User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=brand_rol_ops.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=perm_ver_ops.id, concedido=True))
    db.flush()
    return user


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_operaciones_requires_from_date(client, user_ops):
    """Missing from_date → 422 (not 500)."""
    resp = client.get(
        "/api/dashboard-tplink/operaciones",
        params={"to_date": "2026-06-20"},
        headers=_bearer(user_ops),
    )
    assert resp.status_code == 422


def test_operaciones_requires_to_date(client, user_ops):
    """Missing to_date → 422 (not 500)."""
    resp = client.get(
        "/api/dashboard-tplink/operaciones",
        params={"from_date": "2026-06-01"},
        headers=_bearer(user_ops),
    )
    assert resp.status_code == 422


def test_operaciones_requires_both_dates(client, user_ops):
    """Missing both dates → 422."""
    resp = client.get(
        "/api/dashboard-tplink/operaciones",
        headers=_bearer(user_ops),
    )
    assert resp.status_code == 422


def test_operaciones_calls_fetch_with_coslis_id_8(client, user_ops):
    """fetch_operaciones_con_metricas must be called with coslis_id=8."""
    target = "app.api.endpoints.dashboard_tplink.fetch_operaciones_con_metricas"
    with patch(target, return_value=[]) as mock_fetch:
        resp = client.get(
            "/api/dashboard-tplink/operaciones",
            params={"from_date": "2026-06-01", "to_date": "2026-06-20"},
            headers=_bearer(user_ops),
        )
    assert resp.status_code == 200
    mock_fetch.assert_called_once()
    call_kwargs = mock_fetch.call_args.kwargs
    assert call_kwargs.get("coslis_id") == 8, f"Expected coslis_id=8 but got {call_kwargs.get('coslis_id')}"


def test_operaciones_store_hard_locked_to_2645(client, user_ops):
    """fetch_operaciones_con_metricas must be called with tiendas_oficiales='2645'."""
    target = "app.api.endpoints.dashboard_tplink.fetch_operaciones_con_metricas"
    with patch(target, return_value=[]) as mock_fetch:
        client.get(
            "/api/dashboard-tplink/operaciones",
            params={"from_date": "2026-06-01", "to_date": "2026-06-20"},
            headers=_bearer(user_ops),
        )
    call_kwargs = mock_fetch.call_args.kwargs
    assert call_kwargs.get("tiendas_oficiales") == "2645"
