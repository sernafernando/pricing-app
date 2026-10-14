"""Additional roles per user (`usuarios_roles_adicionales`), permissions only.

The primary role (`usuarios.rol_id`) keeps every identity rule: superadmin, the
`pm_scope` full brand view by role code, the role label. An additional role only
adds its base permissions to the union, and user overrides still apply last.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.security import get_password_hash
from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.usuario import AuthProvider, Usuario
from app.models.usuario_rol_adicional import UsuarioRolAdicional
from app.services.permisos_service import PermisosService
from app.services.pm_scope import is_full_view
from app.services.roles_service import ConflictoRolesAdicionales, RolesService


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
    db.flush()
    return user


def _adicional(db, user: Usuario, rol: Rol) -> None:
    db.add(UsuarioRolAdicional(usuario_id=user.id, rol_id=rol.id))
    db.commit()


def _detalle(db, user: Usuario) -> dict:
    resultado = PermisosService(db).obtener_permisos_detallados_usuario(user)
    return {p["codigo"]: p for permisos in resultado.values() for p in permisos}


@pytest.fixture()
def compras(db, grant_permiso) -> Rol:
    rol = _rol(db, "COMPRAS")
    grant_permiso(rol, "compras.ver")
    grant_permiso(rol, "compras.aprobar")
    return rol


@pytest.fixture()
def vendedor(db, rol_ventas, grant_permiso) -> Usuario:
    grant_permiso(rol_ventas, "ventas.ver")
    return _usuario(db, rol_ventas, "vendedor")


class TestUnionDePermisos:
    def test_sin_roles_adicionales_solo_el_rol_principal(self, db, vendedor, compras):
        assert PermisosService(db).obtener_permisos_usuario(vendedor) == {"ventas.ver"}

    def test_suma_los_permisos_del_rol_adicional(self, db, vendedor, compras):
        _adicional(db, vendedor, compras)

        permisos = PermisosService(db).obtener_permisos_usuario(vendedor)

        assert permisos == {"ventas.ver", "compras.ver", "compras.aprobar"}

    def test_un_override_quitado_gana_sobre_el_rol_adicional(self, db, vendedor, compras):
        _adicional(db, vendedor, compras)
        permiso = db.query(Permiso).filter(Permiso.codigo == "compras.aprobar").one()
        db.add(UsuarioPermisoOverride(usuario_id=vendedor.id, permiso_id=permiso.id, concedido=False))
        db.commit()

        permisos = PermisosService(db).obtener_permisos_usuario(vendedor)

        assert "compras.aprobar" not in permisos
        assert "compras.ver" in permisos

    def test_los_roles_adicionales_de_otro_usuario_no_cuentan(self, db, vendedor, compras, rol_ventas):
        otro = _usuario(db, rol_ventas, "otro")
        _adicional(db, otro, compras)

        assert PermisosService(db).obtener_permisos_usuario(vendedor) == {"ventas.ver"}


class TestIdentidadQuedaEnElRolPrincipal:
    def test_superadmin_como_adicional_no_hace_superadmin(self, db, vendedor, grant_permiso):
        superadmin = _rol(db, "SUPERADMIN", es_sistema=True)
        grant_permiso(superadmin, "admin.todo")
        _adicional(db, vendedor, superadmin)
        db.refresh(vendedor)

        assert vendedor.es_superadmin is False
        assert vendedor.rol_codigo == "VENTAS"
        assert PermisosService(db).obtener_permisos_usuario(vendedor) == {"ventas.ver"}

    def test_gerente_como_adicional_no_da_vista_completa_de_marcas(self, db, vendedor, grant_permiso):
        gerente = _rol(db, "GERENTE")
        grant_permiso(gerente, "reportes.ver")
        _adicional(db, vendedor, gerente)
        db.refresh(vendedor)

        assert "reportes.ver" in PermisosService(db).obtener_permisos_usuario(vendedor)
        assert vendedor.rol_codigo == "VENTAS"
        assert is_full_view(vendedor, db) is False


class TestOrigenDetallado:
    def test_permiso_del_rol_adicional_tiene_origen_rol_adicional(self, db, vendedor, compras):
        _adicional(db, vendedor, compras)

        detalle = _detalle(db, vendedor)

        assert detalle["compras.ver"]["origen"] == "rol_adicional"
        assert detalle["compras.ver"]["roles_adicionales"] == ["COMPRAS"]
        assert detalle["compras.ver"]["tiene_por_rol"] is True
        assert detalle["compras.ver"]["efectivo"] is True

    def test_el_rol_principal_tiene_prioridad_en_el_origen(self, db, vendedor, rol_ventas, grant_permiso, compras):
        grant_permiso(compras, "ventas.ver")
        _adicional(db, vendedor, compras)

        detalle = _detalle(db, vendedor)

        assert detalle["ventas.ver"]["origen"] == "rol"
        assert detalle["ventas.ver"]["roles_adicionales"] == ["COMPRAS"]

    def test_lista_todos_los_roles_adicionales_que_lo_otorgan(self, db, vendedor, compras, grant_permiso):
        deposito = _rol(db, "DEPOSITO")
        grant_permiso(deposito, "compras.ver")
        _adicional(db, vendedor, compras)
        _adicional(db, vendedor, deposito)

        detalle = _detalle(db, vendedor)

        assert detalle["compras.ver"]["roles_adicionales"] == ["COMPRAS", "DEPOSITO"]
        assert detalle["compras.aprobar"]["roles_adicionales"] == ["COMPRAS"]

    def test_override_sigue_siendo_el_origen_cuando_existe(self, db, vendedor, compras):
        _adicional(db, vendedor, compras)
        permiso = db.query(Permiso).filter(Permiso.codigo == "compras.ver").one()
        db.add(UsuarioPermisoOverride(usuario_id=vendedor.id, permiso_id=permiso.id, concedido=False))
        db.commit()

        detalle = _detalle(db, vendedor)

        assert detalle["compras.ver"]["origen"] == "override_quitado"
        assert detalle["compras.ver"]["efectivo"] is False

    def test_sin_roles_adicionales_la_lista_esta_vacia(self, db, vendedor, compras):
        detalle = _detalle(db, vendedor)

        assert detalle["ventas.ver"]["origen"] == "rol"
        assert detalle["ventas.ver"]["roles_adicionales"] == []
        assert detalle["compras.ver"]["origen"] == "sin_permiso"
        assert detalle["compras.ver"]["tiene_por_rol"] is False


class TestConteoYBorradoDeRoles:
    def test_cuenta_usuarios_distintos_por_rol_principal_o_adicional(self, db, rol_ventas, compras):
        principal = _usuario(db, compras, "principal")
        adicional = _usuario(db, rol_ventas, "adicional")
        _adicional(db, adicional, compras)
        _usuario(db, rol_ventas, "ajeno")

        assert RolesService(db).contar_usuarios_rol(compras.id) == 2
        assert {u["id"] for u in RolesService(db).obtener_usuarios_rol(compras.id)} == {principal.id, adicional.id}

    def test_no_se_borra_un_rol_asignado_solo_como_adicional(self, db, vendedor, compras):
        _adicional(db, vendedor, compras)

        with pytest.raises(ValueError, match="1 usuarios asignados"):
            RolesService(db).eliminar_rol(compras.id)

        assert db.query(Rol).filter(Rol.id == compras.id).count() == 1


class TestAsignacion:
    def test_reemplaza_el_conjunto_de_roles_adicionales(self, db, vendedor, compras):
        deposito = _rol(db, "DEPOSITO")
        service = RolesService(db)

        service.set_roles_adicionales_usuario(vendedor.id, [compras.id, deposito.id])
        roles = service.set_roles_adicionales_usuario(vendedor.id, [deposito.id, deposito.id])

        assert [r.codigo for r in roles] == ["DEPOSITO"]
        assert [r.codigo for r in service.obtener_roles_adicionales_usuario(vendedor.id)] == ["DEPOSITO"]

    def test_rechaza_superadmin(self, db, vendedor):
        superadmin = _rol(db, "SUPERADMIN", es_sistema=True)

        with pytest.raises(ValueError, match="SUPERADMIN"):
            RolesService(db).set_roles_adicionales_usuario(vendedor.id, [superadmin.id])

    def test_rechaza_el_rol_principal(self, db, vendedor, rol_ventas):
        with pytest.raises(ValueError, match="rol principal"):
            RolesService(db).set_roles_adicionales_usuario(vendedor.id, [rol_ventas.id])

    def test_rechaza_roles_inexistentes_sin_tocar_lo_guardado(self, db, vendedor, compras):
        service = RolesService(db)
        service.set_roles_adicionales_usuario(vendedor.id, [compras.id])

        with pytest.raises(ValueError, match="99999"):
            service.set_roles_adicionales_usuario(vendedor.id, [99999])

        assert [r.codigo for r in service.obtener_roles_adicionales_usuario(vendedor.id)] == ["COMPRAS"]

    def test_lista_vacia_quita_todos(self, db, vendedor, compras):
        service = RolesService(db)
        service.set_roles_adicionales_usuario(vendedor.id, [compras.id])

        assert service.set_roles_adicionales_usuario(vendedor.id, []) == []
        assert PermisosService(db).obtener_permisos_usuario(vendedor) == {"ventas.ver"}

    def test_promover_un_adicional_a_principal_lo_saca_de_los_adicionales(self, db, vendedor, compras):
        _adicional(db, vendedor, compras)

        RolesService(db).asignar_rol_usuario(vendedor.id, compras.id)

        assert db.query(UsuarioRolAdicional).filter(UsuarioRolAdicional.usuario_id == vendedor.id).count() == 0
        db.refresh(vendedor)
        assert vendedor.rol_id == compras.id

    def test_choque_concurrente_hace_rollback_y_avisa_conflicto(self, db, vendedor, compras, monkeypatch):
        """Two PUTs replacing at once can both insert the same pair; the loser hits
        `uq_usuario_rol_adicional`. It must roll back cleanly and report a conflict."""
        deposito = _rol(db, "DEPOSITO")
        service = RolesService(db)
        service.set_roles_adicionales_usuario(vendedor.id, [compras.id])
        commit_real = db.commit

        def commit_con_choque():
            if any(isinstance(obj, UsuarioRolAdicional) for obj in db.new):
                raise IntegrityError("INSERT", {}, Exception("uq_usuario_rol_adicional"))
            commit_real()

        monkeypatch.setattr(db, "commit", commit_con_choque)

        with pytest.raises(ConflictoRolesAdicionales):
            service.set_roles_adicionales_usuario(vendedor.id, [deposito.id])

        monkeypatch.setattr(db, "commit", commit_real)
        assert [r.codigo for r in service.obtener_roles_adicionales_usuario(vendedor.id)] == ["COMPRAS"]
