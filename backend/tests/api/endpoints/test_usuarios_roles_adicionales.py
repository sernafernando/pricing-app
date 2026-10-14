"""GET/PUT `/api/usuarios/{id}/roles-adicionales`.

Same guard as assigning the primary role (`PATCH /api/usuarios/{id}`): the caller's
PRIMARY role must be ADMIN or SUPERADMIN, and only a SUPERADMIN touches a SUPERADMIN.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.security import get_password_hash
from app.models.rol import Rol
from app.models.usuario import AuthProvider, Usuario
from app.models.usuario_rol_adicional import UsuarioRolAdicional
from tests.conftest import make_access_token


def _rol(db, codigo: str, *, es_sistema: bool = False) -> Rol:
    rol = Rol(codigo=codigo, nombre=codigo.title(), es_sistema=es_sistema, orden=5, activo=True)
    db.add(rol)
    db.flush()
    return rol


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


def _url(user: Usuario) -> str:
    return f"/api/usuarios/{user.id}/roles-adicionales"


@pytest.fixture()
def compras(db, grant_permiso) -> Rol:
    rol = _rol(db, "COMPRAS")
    grant_permiso(rol, "compras.ver")
    return rol


@pytest.fixture()
def vendedor(db, rol_ventas) -> Usuario:
    return _usuario(db, rol_ventas, "vendedor")


@pytest.fixture()
def superadmin_rol(db) -> Rol:
    return _rol(db, "SUPERADMIN", es_sistema=True)


class TestLectura:
    def test_devuelve_rol_principal_y_adicionales(self, client, db, admin_user, vendedor, compras):
        db.add(UsuarioRolAdicional(usuario_id=vendedor.id, rol_id=compras.id))
        db.commit()

        resp = client.get(_url(vendedor), headers=_headers(admin_user))

        assert resp.status_code == 200
        body = resp.json()
        assert body["usuario_id"] == vendedor.id
        assert body["rol_principal"]["codigo"] == "VENTAS"
        assert [r["codigo"] for r in body["roles_adicionales"]] == ["COMPRAS"]

    def test_usuario_inexistente_404(self, client, admin_user):
        resp = client.get("/api/usuarios/99999/roles-adicionales", headers=_headers(admin_user))
        assert resp.status_code == 404

    def test_sin_token_401(self, client, vendedor):
        assert client.get(_url(vendedor)).status_code == 401

    def test_no_admin_403(self, client, vendedor):
        assert client.get(_url(vendedor), headers=_headers(vendedor)).status_code == 403


class TestReemplazo:
    def test_reemplaza_y_el_permiso_queda_efectivo(self, client, db, admin_user, vendedor, compras, grant_permiso):
        grant_permiso(admin_user.rol_obj, "admin.gestionar_permisos")

        resp = client.put(_url(vendedor), json={"rol_ids": [compras.id]}, headers=_headers(admin_user))

        assert resp.status_code == 200
        assert [r["codigo"] for r in resp.json()["roles_adicionales"]] == ["COMPRAS"]
        permisos = client.get(f"/api/permisos/usuario/{vendedor.id}", headers=_headers(admin_user)).json()
        assert "compras.ver" in permisos["permisos"]
        assert permisos["rol"] == "VENTAS"

    def test_lista_vacia_quita_todos(self, client, db, admin_user, vendedor, compras):
        db.add(UsuarioRolAdicional(usuario_id=vendedor.id, rol_id=compras.id))
        db.commit()

        resp = client.put(_url(vendedor), json={"rol_ids": []}, headers=_headers(admin_user))

        assert resp.status_code == 200
        assert resp.json()["roles_adicionales"] == []
        assert db.query(UsuarioRolAdicional).count() == 0

    def test_rechaza_superadmin_400(self, client, db, admin_user, vendedor, superadmin_rol):
        resp = client.put(_url(vendedor), json={"rol_ids": [superadmin_rol.id]}, headers=_headers(admin_user))

        assert resp.status_code == 400
        assert db.query(UsuarioRolAdicional).count() == 0

    def test_rechaza_el_rol_principal_400(self, client, admin_user, vendedor, rol_ventas):
        resp = client.put(_url(vendedor), json={"rol_ids": [rol_ventas.id]}, headers=_headers(admin_user))
        assert resp.status_code == 400

    def test_rechaza_rol_inexistente_400(self, client, admin_user, vendedor):
        resp = client.put(_url(vendedor), json={"rol_ids": [99999]}, headers=_headers(admin_user))
        assert resp.status_code == 400

    def test_no_admin_403(self, client, db, vendedor, compras):
        resp = client.put(_url(vendedor), json={"rol_ids": [compras.id]}, headers=_headers(vendedor))

        assert resp.status_code == 403
        assert db.query(UsuarioRolAdicional).count() == 0

    def test_admin_como_rol_adicional_no_habilita_el_endpoint(self, client, db, vendedor, rol_admin, compras):
        db.add(UsuarioRolAdicional(usuario_id=vendedor.id, rol_id=rol_admin.id))
        db.commit()

        resp = client.put(_url(vendedor), json={"rol_ids": [compras.id]}, headers=_headers(vendedor))

        assert resp.status_code == 403

    def test_admin_no_modifica_a_un_superadmin_403(self, client, db, admin_user, superadmin_rol, compras):
        jefe = _usuario(db, superadmin_rol, "jefe")

        resp = client.put(_url(jefe), json={"rol_ids": [compras.id]}, headers=_headers(admin_user))

        assert resp.status_code == 403

    def test_usuario_inexistente_404(self, client, admin_user, compras):
        resp = client.put(
            "/api/usuarios/99999/roles-adicionales", json={"rol_ids": [compras.id]}, headers=_headers(admin_user)
        )
        assert resp.status_code == 404

    def test_choque_concurrente_409(self, client, db, admin_user, vendedor, compras, monkeypatch):
        commit_real = db.commit

        def commit_con_choque():
            if any(isinstance(obj, UsuarioRolAdicional) for obj in db.new):
                raise IntegrityError("INSERT", {}, Exception("uq_usuario_rol_adicional"))
            commit_real()

        monkeypatch.setattr(db, "commit", commit_con_choque)

        resp = client.put(_url(vendedor), json={"rol_ids": [compras.id]}, headers=_headers(admin_user))

        assert resp.status_code == 409
        assert "al mismo tiempo" in resp.text


class TestCambioDeRolPrincipal:
    def test_promover_un_adicional_a_principal_lo_saca_de_los_adicionales(
        self, client, db, admin_user, vendedor, compras
    ):
        db.add(UsuarioRolAdicional(usuario_id=vendedor.id, rol_id=compras.id))
        db.commit()

        resp = client.patch(f"/api/usuarios/{vendedor.id}", json={"rol": "COMPRAS"}, headers=_headers(admin_user))

        assert resp.status_code == 200
        assert db.query(UsuarioRolAdicional).filter(UsuarioRolAdicional.usuario_id == vendedor.id).count() == 0

    def test_patch_bloquea_al_usuario_y_borra_despues_del_update(
        self, client, db, admin_user, vendedor, compras, query_counter, monkeypatch
    ):
        from tests.services.test_permisos_roles_adicionales import (
            _assert_update_antes_del_delete,
            _espiar_with_for_update,
        )

        db.add(UsuarioRolAdicional(usuario_id=vendedor.id, rol_id=compras.id))
        db.commit()
        headers = _headers(admin_user)
        bloqueos = _espiar_with_for_update(monkeypatch)

        with query_counter() as counter:
            resp = client.patch(f"/api/usuarios/{vendedor.id}", json={"rol": "COMPRAS"}, headers=headers)

        assert resp.status_code == 200
        assert "usuarios" in bloqueos
        _assert_update_antes_del_delete(counter.statements)
        db.refresh(vendedor)
        assert vendedor.rol_id == compras.id
        assert db.query(UsuarioRolAdicional).filter(UsuarioRolAdicional.rol_id == vendedor.rol_id).count() == 0
