"""`ventas_ml` shares the pm_scope full-view contract.

`get_pares_marca_cat_usuario_ventas` used to carry its own copy of the role
check, reading the deprecated `Usuario.rol` column and ignoring the
`ventas_ml.ver_todas_marcas` permission. These tests pin it to `is_full_view`.
"""

from __future__ import annotations

import pytest

from app.api.endpoints.ventas_ml import get_pares_marca_cat_usuario_ventas
from app.core.security import get_password_hash
from app.models.marca_pm import MarcaPM
from app.models.permiso import Permiso, RolPermisoBase
from app.models.rol import Rol
from app.models.usuario import AuthProvider, Usuario


@pytest.fixture()
def rol_gerente(db) -> Rol:
    rol = Rol(codigo="GERENTE", nombre="Gerente", es_sistema=False, orden=5, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def permiso_ver_todas_marcas(db) -> Permiso:
    permiso = Permiso(
        codigo="ventas_ml.ver_todas_marcas",
        nombre="Ver todas las marcas ML",
        categoria="ventas_ml",
    )
    db.add(permiso)
    db.flush()
    return permiso


def _make_user(db, rol_obj: Rol, username: str) -> Usuario:
    user = Usuario(
        username=username,
        email=f"{username}@example.com",
        nombre=username,
        password_hash=get_password_hash("TestPass123!"),
        rol=None,
        rol_id=rol_obj.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def test_role_from_rol_id_only_returns_none(db, rol_gerente) -> None:
    user = _make_user(db, rol_gerente, "ventas_gerente_sin_enum")

    assert get_pares_marca_cat_usuario_ventas(db, user) is None


def test_permission_returns_none_without_a_full_view_role(db, rol_ventas, permiso_ver_todas_marcas) -> None:
    user = _make_user(db, rol_ventas, "ventas_con_permiso")
    db.add(MarcaPM(marca="Nike", categoria="Zapatillas", usuario_id=user.id))
    db.add(RolPermisoBase(rol_id=rol_ventas.id, permiso_id=permiso_ver_todas_marcas.id))
    db.flush()

    assert get_pares_marca_cat_usuario_ventas(db, user) is None


def test_without_the_permission_the_pairs_are_returned(db, rol_ventas, permiso_ver_todas_marcas) -> None:
    user = _make_user(db, rol_ventas, "ventas_sin_permiso")
    db.add(MarcaPM(marca="Nike", categoria="Zapatillas", usuario_id=user.id))
    db.flush()

    assert get_pares_marca_cat_usuario_ventas(db, user) == {("NIKE", "ZAPATILLAS")}
