"""`tplink.solo`: the TP-only data lock, on the service side.

The code comes from the migration that creates it (its `CODIGO`), so renaming
either side breaks this test instead of silently checking a permission that
no migration defines.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.core.security import get_password_hash
from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.usuario import AuthProvider, Usuario
from app.services import tplink_solo
from app.services.permisos_service import OPT_IN_PERMISSION_CODES
from app.services.tiendas_oficiales import StoreClaveNotConfigured

_MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20261028_tplink_solo_permiso.py"


def _codigo_de_la_migracion() -> str:
    spec = importlib.util.spec_from_file_location("tplink_solo_permiso_migration", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CODIGO


SOLO = _codigo_de_la_migracion()


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
def solo(db) -> Permiso:
    permiso = Permiso(codigo=SOLO, nombre="Acceso solo TP-Link", categoria="ventas_ml", orden=64, es_critico=False)
    db.add(permiso)
    db.commit()
    return permiso


class TestPermission:
    def test_the_helper_checks_the_code_the_migration_creates(self) -> None:
        assert tplink_solo.TPLINK_SOLO == SOLO == "tplink.solo"

    def test_it_is_opt_in(self) -> None:
        assert SOLO in OPT_IN_PERMISSION_CODES

    def test_superadmin_without_a_grant_is_not_tp_only(self, db, solo) -> None:
        owner = _usuario(db, _rol(db, "SUPERADMIN"), "owner_sin_solo")
        assert tplink_solo.es_tplink_solo(db, owner) is False

    def test_a_user_with_the_grant_is_tp_only(self, db, solo) -> None:
        user = _usuario(db, _rol(db, "VENTAS"), "solo_tp")
        db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=solo.id, concedido=True))
        db.commit()
        assert tplink_solo.es_tplink_solo(db, user) is True


class TestStoreLock:
    @pytest.fixture()
    def tiendas(self, db) -> None:
        db.add_all(
            [
                MlTiendaOficial(store_id=2645, nombre="TP-Link", clave="tplink"),
                MlTiendaOficial(store_id=471846, nombre="TP-Link nueva", clave="tplink"),
                MlTiendaOficial(store_id=57997, nombre="Gauss", clave=None),
            ]
        )
        db.commit()

    def test_no_request_means_the_whole_tp_group(self, db, tiendas) -> None:
        assert tplink_solo.lock_stores(db, ()) == ("2645", "471846")

    def test_a_request_is_intersected_with_the_tp_group(self, db, tiendas) -> None:
        assert tplink_solo.lock_stores(db, ("471846", "57997")) == ("471846",)

    @pytest.mark.parametrize("requested", [("57997",), ("sin_tienda",), ("57997", "sin_tienda")])
    def test_a_request_outside_the_group_matches_nothing(self, db, tiendas, requested) -> None:
        locked = tplink_solo.lock_stores(db, requested)

        assert locked == (tplink_solo.NO_STORE_MATCH,)
        assert int(tplink_solo.NO_STORE_MATCH) < 0

    def test_no_tp_store_configured_fails_closed(self, db) -> None:
        with pytest.raises(StoreClaveNotConfigured):
            tplink_solo.lock_stores(db, ())
