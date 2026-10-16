"""Opt-in permissions: codes SUPERADMIN does NOT get implicitly.

SUPERADMIN normally holds every permission code. Opt-in codes change how the
app looks or what data it shows (the TP-Link theme, the TP-only data lock), so
giving them to every SUPERADMIN would brand or lock every administrator.
SUPERADMIN gets an opt-in code only through an explicit per-user override;
everyone else gets it through roles/overrides exactly as before.
"""

from __future__ import annotations

import pytest

from app.core.security import get_password_hash
from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.usuario import AuthProvider, Usuario
from app.services.permisos_service import OPT_IN_PERMISSION_CODES, PermisosService, verificar_permiso

NORMAL = "productos.ver"
TEMA = "tplink.tema"
SOLO = "tplink.solo"


def _permiso(db, codigo: str) -> Permiso:
    permiso = db.query(Permiso).filter(Permiso.codigo == codigo).first()
    if permiso is None:
        permiso = Permiso(codigo=codigo, nombre=codigo, descripcion="", categoria=codigo.split(".")[0], orden=999)
        db.add(permiso)
        db.flush()
    return permiso


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


def _override(db, user: Usuario, codigo: str, concedido: bool) -> None:
    db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=_permiso(db, codigo).id, concedido=concedido))
    db.commit()


def _detalle(db, user: Usuario) -> dict:
    resultado = PermisosService(db).obtener_permisos_detallados_usuario(user)
    return {p["codigo"]: p for permisos in resultado.values() for p in permisos}


@pytest.fixture()
def catalogo(db) -> None:
    for codigo in (NORMAL, TEMA, SOLO):
        _permiso(db, codigo)
    db.commit()


@pytest.fixture()
def superadmin(db, catalogo) -> Usuario:
    return _usuario(db, _rol(db, "SUPERADMIN"), "owner_opt_in")


def test_opt_in_codes_are_the_tplink_ones() -> None:
    assert OPT_IN_PERMISSION_CODES == frozenset({TEMA, SOLO})


class TestSuperadminWithoutOverride:
    def test_gets_every_code_except_opt_in(self, db, superadmin) -> None:
        permisos = PermisosService(db).obtener_permisos_usuario(superadmin)
        assert NORMAL in permisos
        assert TEMA not in permisos
        assert SOLO not in permisos

    def test_checks_are_false_for_opt_in_and_true_otherwise(self, db, superadmin) -> None:
        service = PermisosService(db)
        assert service.tiene_permiso(superadmin, NORMAL) is True
        assert service.tiene_permiso(superadmin, TEMA) is False
        assert service.tiene_algun_permiso(superadmin, [TEMA, SOLO]) is False
        assert service.tiene_algun_permiso(superadmin, [TEMA, NORMAL]) is True
        assert service.tiene_todos_los_permisos(superadmin, [NORMAL, TEMA]) is False
        assert verificar_permiso(db, superadmin, TEMA) is False
        assert verificar_permiso(db, superadmin, NORMAL) is True

    def test_checks_with_the_request_cache(self, db, superadmin) -> None:
        # get_current_user pre-loads `_permisos_cache`; the fast paths must agree.
        service = PermisosService(db)
        superadmin._permisos_cache = service.obtener_permisos_usuario(superadmin)
        assert verificar_permiso(db, superadmin, TEMA) is False
        assert verificar_permiso(db, superadmin, NORMAL) is True
        assert service.tiene_permiso(superadmin, TEMA) is False
        assert service.tiene_todos_los_permisos(superadmin, [NORMAL, SOLO]) is False

    def test_detail_view_shows_opt_in_as_not_effective(self, db, superadmin) -> None:
        detalle = _detalle(db, superadmin)
        assert (detalle[NORMAL]["efectivo"], detalle[NORMAL]["origen"]) == (True, "superadmin")
        assert detalle[TEMA]["efectivo"] is False
        assert detalle[TEMA]["tiene_por_rol"] is False
        assert detalle[TEMA]["origen"] == "sin_permiso"


class TestSuperadminWithOverride:
    def test_granted_opt_in_code_is_included(self, db, superadmin) -> None:
        _override(db, superadmin, TEMA, True)
        service = PermisosService(db)
        permisos = service.obtener_permisos_usuario(superadmin)
        assert TEMA in permisos
        assert SOLO not in permisos
        assert service.tiene_permiso(superadmin, TEMA) is True
        assert verificar_permiso(db, superadmin, TEMA) is True
        superadmin._permisos_cache = permisos
        assert verificar_permiso(db, superadmin, TEMA) is True

    def test_detail_view_shows_the_grant(self, db, superadmin) -> None:
        _override(db, superadmin, TEMA, True)
        detalle = _detalle(db, superadmin)
        assert (detalle[TEMA]["efectivo"], detalle[TEMA]["origen"], detalle[TEMA]["override"]) == (
            True,
            "override_agregado",
            True,
        )

    def test_explicit_revoke_keeps_it_out(self, db, superadmin) -> None:
        _override(db, superadmin, TEMA, False)
        assert TEMA not in PermisosService(db).obtener_permisos_usuario(superadmin)
        assert _detalle(db, superadmin)[TEMA]["origen"] == "override_quitado"

    def test_overrides_on_regular_codes_stay_ignored_for_superadmin(self, db, superadmin) -> None:
        _override(db, superadmin, NORMAL, False)
        assert NORMAL in PermisosService(db).obtener_permisos_usuario(superadmin)


class TestRegularUserUnchanged:
    def test_role_grant_of_an_opt_in_code_still_applies(self, db, catalogo, grant_permiso) -> None:
        rol = _rol(db, "TPLINK_PRUEBA")
        grant_permiso(rol, TEMA)
        user = _usuario(db, rol, "regular_opt_in")
        assert TEMA in PermisosService(db).obtener_permisos_usuario(user)

    def test_override_grant_of_an_opt_in_code_still_applies(self, db, catalogo) -> None:
        user = _usuario(db, _rol(db, "VENTAS_PRUEBA"), "regular_override")
        _override(db, user, SOLO, True)
        service = PermisosService(db)
        assert SOLO in service.obtener_permisos_usuario(user)
        assert service.tiene_permiso(user, SOLO) is True
