"""Integration tests for the TN reconciliation endpoints (Slice 1, read-only).

Covers: permission gate, ban-list add/remove hides/reveals a row, and GBP
fetch-failure surfaces a clear error without any partial write.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.models.usuario import AuthProvider, RolUsuario, Usuario


def _bearer(user: Usuario) -> dict[str, str]:
    token = create_access_token(data={"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def brand_rol(db) -> Rol:
    rol = Rol(codigo="TN_TEST", nombre="TN Test", es_sistema=False, orden=99, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def perm_ver(db) -> Permiso:
    p = Permiso(
        codigo="admin.ver_tn_reconciliacion",
        nombre="Ver reconciliación Tienda Nube",
        descripcion="Access",
        categoria="administracion",
        orden=62,
        es_critico=False,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def perm_banlist(db) -> Permiso:
    p = Permiso(
        codigo="admin.gestionar_tn_reconcile_banlist",
        nombre="Gestionar banlist de reconciliación TN",
        descripcion="Manage banlist",
        categoria="administracion",
        orden=63,
        es_critico=False,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def user_no_perm(db, brand_rol) -> Usuario:
    user = Usuario(
        username="tn_no_perm",
        email="tn_no_perm@test.com",
        nombre="No Perm",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=brand_rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def user_ver(db, brand_rol, perm_ver, perm_banlist) -> Usuario:
    user = Usuario(
        username="tn_ver",
        email="tn_ver@test.com",
        nombre="Ver User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=brand_rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()

    for perm in (perm_ver, perm_banlist):
        db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=perm.id, concedido=True))
    db.flush()
    return user


def _fake_gbp_rows():
    return [
        {"Código": "EAN-100", "tnr_id": 0, "tnr_variationID": 0, "stock": 5},
    ]


class TestPermissionGate:
    def test_no_permission_returns_403(self, client, db, user_no_perm):
        response = client.get("/api/tienda-nube-reconcile/reporte", headers=_bearer(user_no_perm))
        assert response.status_code == 403

    def test_with_permission_returns_200(self, client, db, user_ver):
        with patch(
            "app.api.endpoints.tienda_nube_reconcile.fetch_gbp_report_78",
            new=AsyncMock(return_value=_fake_gbp_rows()),
        ):
            response = client.get("/api/tienda-nube-reconcile/reporte", headers=_bearer(user_ver))
        assert response.status_code == 200
        body = response.json()
        assert any(row["ean"] == "EAN-100" and row["verdict"] == "FALTA_PUBLICAR" for row in body)


class TestBanlist:
    def test_ban_hides_row_and_unban_reveals_it(self, client, db, user_ver):
        with patch(
            "app.api.endpoints.tienda_nube_reconcile.fetch_gbp_report_78",
            new=AsyncMock(return_value=_fake_gbp_rows()),
        ):
            before = client.get("/api/tienda-nube-reconcile/reporte", headers=_bearer(user_ver))
            assert any(row["ean"] == "EAN-100" for row in before.json())

            ban_response = client.post(
                "/api/tienda-nube-reconcile/banear",
                json={"ean": "EAN-100", "motivo": "test"},
                headers=_bearer(user_ver),
            )
            assert ban_response.status_code == 200

            after_ban = client.get("/api/tienda-nube-reconcile/reporte", headers=_bearer(user_ver))
            assert not any(row["ean"] == "EAN-100" for row in after_ban.json())

            banlist_id = ban_response.json()["banlist_id"]
            unban_response = client.post(
                "/api/tienda-nube-reconcile/desbanear",
                json={"banlist_id": banlist_id},
                headers=_bearer(user_ver),
            )
            assert unban_response.status_code == 200

            after_unban = client.get("/api/tienda-nube-reconcile/reporte", headers=_bearer(user_ver))
            assert any(row["ean"] == "EAN-100" for row in after_unban.json())

    def test_ban_requires_permission(self, client, db, user_no_perm):
        response = client.post(
            "/api/tienda-nube-reconcile/banear",
            json={"ean": "EAN-100"},
            headers=_bearer(user_no_perm),
        )
        assert response.status_code == 403


class TestGracefulDegradation:
    def test_gbp_fetch_failure_returns_clear_error_no_partial_write(self, client, db, user_ver):
        from app.services.tn_reconciliation_service import GBPFetchError

        with patch(
            "app.api.endpoints.tienda_nube_reconcile.fetch_gbp_report_78",
            new=AsyncMock(side_effect=GBPFetchError("SOAP timeout")),
        ):
            response = client.get("/api/tienda-nube-reconcile/reporte", headers=_bearer(user_ver))

        assert response.status_code == 502
        assert "SOAP timeout" in response.json()["error"]["message"]
        # No banlist/marked-for-deletion row was ever created by a failed load.
        assert db.query(TiendaNubeProducto).count() == 0
