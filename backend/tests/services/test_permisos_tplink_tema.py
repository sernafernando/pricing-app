"""`tplink.tema` is an opt-in permission, end to end on the service.

The code under test comes from the migration that creates it (its `CODIGO`),
so renaming either side breaks this test instead of silently leaving the
theme permission outside OPT_IN_PERMISSION_CODES, which would brand every
SUPERADMIN.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.core.security import get_password_hash
from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.usuario import AuthProvider, Usuario
from app.services.permisos_service import OPT_IN_PERMISSION_CODES, PermisosService

_MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20261026_tplink_tema_permiso.py"


def _codigo_de_la_migracion() -> str:
    spec = importlib.util.spec_from_file_location("tplink_tema_permiso_migration", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CODIGO


TEMA = _codigo_de_la_migracion()


def _rol(db, codigo: str) -> Rol:
    rol = db.query(Rol).filter(Rol.codigo == codigo).first()
    if rol is None:
        rol = Rol(codigo=codigo, nombre=codigo.title(), es_sistema=True, orden=1, activo=True)
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
    db.flush()
    return user


@pytest.fixture()
def tema(db) -> Permiso:
    # Same values the migration inserts.
    permiso = Permiso(
        codigo=TEMA,
        nombre="Ver tema TP-Link",
        descripcion="Aplica los colores y el logo de TP-Link en toda la interfaz",
        categoria="ventas_ml",
        orden=63,
        es_critico=False,
    )
    db.add(permiso)
    db.commit()
    return permiso


def test_the_migration_creates_the_tplink_tema_code() -> None:
    assert TEMA == "tplink.tema"


def test_tplink_tema_is_opt_in() -> None:
    assert TEMA in OPT_IN_PERMISSION_CODES


def test_superadmin_without_override_does_not_get_it(db, tema) -> None:
    owner = _usuario(db, _rol(db, "SUPERADMIN"), "owner_sin_tema")
    assert TEMA not in PermisosService(db).obtener_permisos_usuario(owner)


def test_superadmin_with_a_grant_override_gets_it(db, tema) -> None:
    owner = _usuario(db, _rol(db, "SUPERADMIN"), "owner_con_tema")
    db.add(UsuarioPermisoOverride(usuario_id=owner.id, permiso_id=tema.id, concedido=True))
    db.commit()
    assert TEMA in PermisosService(db).obtener_permisos_usuario(owner)
