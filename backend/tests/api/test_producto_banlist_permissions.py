"""Who may add a product to the banlist (POST /producto-banlist).

The Productos and Tienda screens offer "Agregar a banlist" only to ADMIN and SUPERADMIN; the Banlist page
(`/mla-banlist`, `admin.gestionar_mla_banlist`) has a products tab that adds too. The server enforces the same: the
role, or that permission. Anyone else gets 403 and nothing is written.
"""

from __future__ import annotations

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.permiso import Permiso, RolPermisoBase, UsuarioPermisoOverride
from app.models.producto import ProductoERP
from app.models.producto_banlist import ProductoBanlist
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario

ITEM_ID = 4101


def _bearer(user: Usuario) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(data={'sub': user.username})}"}


@pytest.fixture()
def test_rol(db) -> Rol:
    rol = Rol(codigo="BANLIST_TEST", nombre="Banlist Test", es_sistema=False, orden=99, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def perm_banlist(db) -> Permiso:
    permiso = Permiso(
        codigo="admin.gestionar_mla_banlist",
        nombre="Gestionar MLA banlist",
        descripcion="Agregar y quitar MLAs de la banlist",
        categoria="administracion",
        orden=57,
        es_critico=False,
    )
    db.add(permiso)
    db.flush()
    return permiso


@pytest.fixture()
def producto(db) -> ProductoERP:
    row = ProductoERP(item_id=ITEM_ID, codigo="COD4101", descripcion="Router Archer AX55")
    db.add(row)
    db.flush()
    return row


def _make_user(db, rol: Rol, username: str, rol_usuario: RolUsuario, perms=(), revoked=()) -> Usuario:
    user = Usuario(
        username=username,
        email=f"{username}@test.com",
        nombre=username,
        password_hash=get_password_hash("Pass123!"),
        rol=rol_usuario,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    for perm in perms:
        db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=perm.id, concedido=True))
    for perm in revoked:
        db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=perm.id, concedido=False))
    db.flush()
    return user


def _ban(client, user: Usuario):
    return client.post(
        "/api/producto-banlist", json={"item_ids": str(ITEM_ID), "motivo": "test"}, headers=_bearer(user)
    )


def _banned(db) -> list[ProductoBanlist]:
    return db.query(ProductoBanlist).filter(ProductoBanlist.item_id == ITEM_ID).all()


@pytest.mark.parametrize("rol_usuario", [RolUsuario.GERENTE, RolUsuario.PRICING, RolUsuario.VENTAS])
def test_a_user_without_the_role_or_the_permission_gets_403_and_nothing_is_banned(
    client, db, test_rol, producto, rol_usuario
):
    ventas = _make_user(db, test_rol, f"ban_denied_{rol_usuario.value.lower()}", rol_usuario)

    response = _ban(client, ventas)

    assert response.status_code == 403
    assert _banned(db) == []


@pytest.mark.parametrize("rol_usuario", [RolUsuario.ADMIN, RolUsuario.SUPERADMIN])
def test_admin_and_superadmin_still_ban(client, db, test_rol, producto, rol_usuario):
    admin = _make_user(db, test_rol, f"ban_{rol_usuario.value.lower()}", rol_usuario)

    response = _ban(client, admin)

    assert response.status_code == 200
    assert response.json()["total_agregados"] == 1
    [row] = _banned(db)
    assert row.activo is True
    assert row.usuario_id == admin.id
    assert row.motivo == "test"


def test_the_banlist_page_permission_still_bans(client, db, test_rol, producto, perm_banlist):
    gestor = _make_user(db, test_rol, "gestor_ban", RolUsuario.VENTAS, perms=[perm_banlist])

    response = _ban(client, gestor)

    assert response.status_code == 200
    assert response.json()["total_agregados"] == 1
    assert [row.usuario_id for row in _banned(db)] == [gestor.id]


def test_the_permission_granted_by_the_role_still_bans(client, db, test_rol, producto, perm_banlist):
    db.add(RolPermisoBase(rol_id=test_rol.id, permiso_id=perm_banlist.id))
    db.flush()
    gestor = _make_user(db, test_rol, "gestor_rol_ban", RolUsuario.VENTAS)

    response = _ban(client, gestor)

    assert response.status_code == 200
    assert response.json()["total_agregados"] == 1
    assert [row.usuario_id for row in _banned(db)] == [gestor.id]


def test_the_permission_revoked_for_the_user_denies_even_when_the_role_grants_it(
    client, db, test_rol, producto, perm_banlist
):
    db.add(RolPermisoBase(rol_id=test_rol.id, permiso_id=perm_banlist.id))
    db.flush()
    revocado = _make_user(db, test_rol, "revocado_ban", RolUsuario.VENTAS, revoked=[perm_banlist])

    response = _ban(client, revocado)

    assert response.status_code == 403
    assert _banned(db) == []
