"""Only a SUPERADMIN can hand out the SUPERADMIN role.

The admin UI already hides SUPERADMIN from a non-SUPERADMIN caller
(`rolesAsignables` in PanelPermisos.jsx); these tests pin the same rule on the API,
for `POST /api/usuarios` and `PATCH /api/usuarios/{id}`.
"""

from __future__ import annotations

import pytest

from app.core.security import get_password_hash
from app.models.rol import Rol
from app.models.usuario import AuthProvider, Usuario
from tests.conftest import make_access_token


def _usuario(db, rol: Rol, username: str) -> Usuario:
    user = Usuario(
        username=username,
        email=f"{username}@example.com",
        nombre=username,
        password_hash=get_password_hash("TestPass123!"),
        rol=None,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.commit()
    return user


def _headers(user: Usuario) -> dict:
    return {"Authorization": f"Bearer {make_access_token(user)}"}


def _alta(rol: str) -> dict:
    return {
        "username": "nuevo",
        "email": "nuevo@example.com",
        "nombre": "Nuevo",
        "password": "TestPass123!",
        "rol": rol,
    }


@pytest.fixture()
def superadmin_rol(db) -> Rol:
    rol = Rol(codigo="SUPERADMIN", nombre="Superadmin", es_sistema=True, orden=0, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def superadmin(db, superadmin_rol) -> Usuario:
    return _usuario(db, superadmin_rol, "root")


@pytest.fixture()
def vendedor(db, rol_ventas) -> Usuario:
    return _usuario(db, rol_ventas, "vendedor")


class TestEdicion:
    @pytest.mark.parametrize("rol", ["SUPERADMIN", "superadmin"])
    def test_admin_no_promueve_a_superadmin_403(
        self, client, db, admin_user, vendedor, superadmin_rol, rol_ventas, rol
    ):
        resp = client.patch(f"/api/usuarios/{vendedor.id}", json={"rol": rol}, headers=_headers(admin_user))

        assert resp.status_code == 403
        db.refresh(vendedor)
        assert vendedor.rol_id == rol_ventas.id

    def test_admin_no_se_promueve_a_si_mismo_403(self, client, db, admin_user, superadmin_rol):
        rol_previo = admin_user.rol_id

        resp = client.patch(f"/api/usuarios/{admin_user.id}", json={"rol": "SUPERADMIN"}, headers=_headers(admin_user))

        assert resp.status_code == 403
        db.refresh(admin_user)
        assert admin_user.rol_id == rol_previo

    def test_superadmin_promueve_a_superadmin(self, client, db, superadmin, vendedor, superadmin_rol):
        resp = client.patch(f"/api/usuarios/{vendedor.id}", json={"rol": "SUPERADMIN"}, headers=_headers(superadmin))

        assert resp.status_code == 200
        db.refresh(vendedor)
        assert vendedor.rol_id == superadmin_rol.id

    def test_admin_sigue_asignando_otros_roles(self, client, db, admin_user, vendedor, rol_admin):
        resp = client.patch(f"/api/usuarios/{vendedor.id}", json={"rol": "ADMIN"}, headers=_headers(admin_user))

        assert resp.status_code == 200
        db.refresh(vendedor)
        assert vendedor.rol_id == rol_admin.id


class TestAlta:
    @pytest.mark.parametrize("rol", ["SUPERADMIN", "superadmin"])
    def test_admin_no_crea_un_superadmin_403(self, client, db, admin_user, superadmin_rol, rol):
        resp = client.post("/api/usuarios", json=_alta(rol), headers=_headers(admin_user))

        assert resp.status_code == 403
        assert db.query(Usuario).filter(Usuario.username == "nuevo").first() is None

    def test_superadmin_crea_un_superadmin(self, client, db, superadmin, superadmin_rol):
        resp = client.post("/api/usuarios", json=_alta("SUPERADMIN"), headers=_headers(superadmin))

        assert resp.status_code == 200
        creado = db.query(Usuario).filter(Usuario.username == "nuevo").one()
        assert creado.rol_id == superadmin_rol.id
