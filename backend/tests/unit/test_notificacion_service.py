"""
Tests de `notificacion_service`.

Cubre el Fix 4 del batch "4 riesgos compras":
  - `resolver_usuarios_con_algun_permiso`: selección por permisos híbrida
    (rol base + overrides) para fan-out de notificaciones.
  - `crear_notificaciones_para_permisos`: reemplaza el antipatrón previo
    `Notificacion(user_id=None)` que no era visible para nadie (el endpoint
    `GET /notificaciones` filtra estricto `user_id == current_user.id`).
"""

from __future__ import annotations

import pytest

from app.core.security import get_password_hash
from app.models.notificacion import EstadoNotificacion, Notificacion, SeveridadNotificacion
from app.models.permiso import Permiso, RolPermisoBase, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario


# ──────────────────────────────────────────────────────────────────────────
# Fixtures específicos
# ──────────────────────────────────────────────────────────────────────────

PERMISO_OPS = "administracion.gestionar_ordenes_compra"
PERMISO_CC = "administracion.ver_cuentas_corrientes"
PERMISOS_NOTIF = [PERMISO_OPS, PERMISO_CC]


@pytest.fixture
def permisos_admin_compras(db) -> tuple[Permiso, Permiso]:
    """Siembra los dos permisos que usa el hook de matching."""
    p_ops = Permiso(
        codigo=PERMISO_OPS,
        nombre="Gestionar órdenes de compra",
        categoria="administracion",
        orden=1,
    )
    p_cc = Permiso(
        codigo=PERMISO_CC,
        nombre="Ver cuentas corrientes",
        categoria="administracion",
        orden=2,
    )
    db.add_all([p_ops, p_cc])
    db.flush()
    return p_ops, p_cc


@pytest.fixture
def rol_admin_compras(db) -> Rol:
    rol = Rol(codigo="ADMIN_COMPRAS", nombre="Admin Compras", es_sistema=False, orden=5, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture
def rol_admin_compras_con_permisos(db, rol_admin_compras, permisos_admin_compras) -> Rol:
    p_ops, p_cc = permisos_admin_compras
    db.add_all(
        [
            RolPermisoBase(rol_id=rol_admin_compras.id, permiso_id=p_ops.id),
            RolPermisoBase(rol_id=rol_admin_compras.id, permiso_id=p_cc.id),
        ]
    )
    db.flush()
    return rol_admin_compras


def _crear_usuario(
    db,
    *,
    username: str,
    rol_id: int,
    activo: bool = True,
    rol_enum: RolUsuario = RolUsuario.VENTAS,
) -> Usuario:
    user = Usuario(
        username=username,
        email=f"{username}@example.com",
        nombre=f"User {username}",
        password_hash=get_password_hash("TestPass123!"),
        rol=rol_enum,
        rol_id=rol_id,
        auth_provider=AuthProvider.LOCAL,
        activo=activo,
    )
    db.add(user)
    db.flush()
    return user


# ──────────────────────────────────────────────────────────────────────────
# resolver_usuarios_con_algun_permiso
# ──────────────────────────────────────────────────────────────────────────


class TestResolverUsuariosConAlgunPermiso:
    def test_retorna_usuarios_activos_con_rol_que_tiene_permiso(
        self, db, rol_admin_compras_con_permisos, rol_ventas
    ) -> None:
        from app.services.notificacion_service import resolver_usuarios_con_algun_permiso  # noqa: PLC0415

        admin = _crear_usuario(db, username="admin_a", rol_id=rol_admin_compras_con_permisos.id)
        _ventas = _crear_usuario(db, username="ventas_a", rol_id=rol_ventas.id)

        usuarios = resolver_usuarios_con_algun_permiso(db, permisos_requeridos=PERMISOS_NOTIF)
        ids = {u.id for u in usuarios}
        assert admin.id in ids
        assert _ventas.id not in ids  # rol VENTAS no tiene esos permisos

    def test_excluye_usuarios_inactivos(self, db, rol_admin_compras_con_permisos) -> None:
        from app.services.notificacion_service import resolver_usuarios_con_algun_permiso  # noqa: PLC0415

        _activo = _crear_usuario(db, username="admin_act", rol_id=rol_admin_compras_con_permisos.id, activo=True)
        inactivo = _crear_usuario(db, username="admin_inact", rol_id=rol_admin_compras_con_permisos.id, activo=False)

        usuarios = resolver_usuarios_con_algun_permiso(db, permisos_requeridos=PERMISOS_NOTIF)
        ids = {u.id for u in usuarios}
        assert _activo.id in ids
        assert inactivo.id not in ids

    def test_override_agregado_incluye_usuario(
        self, db, rol_ventas, permisos_admin_compras
    ) -> None:
        """
        Usuario con rol VENTAS (sin permisos base de admin) pero con override
        CONCEDIDO de `administracion.gestionar_ordenes_compra` → se incluye.
        """
        from app.services.notificacion_service import resolver_usuarios_con_algun_permiso  # noqa: PLC0415

        p_ops, _ = permisos_admin_compras
        user = _crear_usuario(db, username="ventas_override", rol_id=rol_ventas.id)
        db.add(
            UsuarioPermisoOverride(
                usuario_id=user.id,
                permiso_id=p_ops.id,
                concedido=True,
            )
        )
        db.flush()

        usuarios = resolver_usuarios_con_algun_permiso(db, permisos_requeridos=PERMISOS_NOTIF)
        ids = {u.id for u in usuarios}
        assert user.id in ids


# ──────────────────────────────────────────────────────────────────────────
# crear_notificaciones_para_permisos
# ──────────────────────────────────────────────────────────────────────────


class TestCrearNotificacionesParaPermisos:
    def test_crea_una_notificacion_por_admin_visible_en_listado(
        self, db, rol_admin_compras_con_permisos, rol_ventas
    ) -> None:
        """
        Fix 4 — caso feliz: el helper crea 1 notificación por cada usuario
        con permisos → el endpoint `GET /notificaciones` la ve.
        """
        from app.services.notificacion_service import crear_notificaciones_para_permisos  # noqa: PLC0415

        admin1 = _crear_usuario(db, username="adm1", rol_id=rol_admin_compras_con_permisos.id)
        admin2 = _crear_usuario(db, username="adm2", rol_id=rol_admin_compras_con_permisos.id)
        _ventas = _crear_usuario(db, username="ventas_b", rol_id=rol_ventas.id)

        creadas = crear_notificaciones_para_permisos(
            db,
            permisos_requeridos=PERMISOS_NOTIF,
            tipo="compras.pedido_monto_difiere_factura",
            mensaje="Diferencia detectada",
            severidad=SeveridadNotificacion.WARNING,
            item_id=42,
        )
        db.flush()

        assert len(creadas) == 2
        user_ids_notif = {n.user_id for n in creadas}
        assert user_ids_notif == {admin1.id, admin2.id}
        # Verificación extra: el endpoint filtra por user_id; ahora la ve admin1.
        notifs_admin1 = db.query(Notificacion).filter(Notificacion.user_id == admin1.id).all()
        assert len(notifs_admin1) == 1
        assert notifs_admin1[0].severidad == SeveridadNotificacion.WARNING
        assert notifs_admin1[0].estado == EstadoNotificacion.PENDIENTE
        assert notifs_admin1[0].tipo == "compras.pedido_monto_difiere_factura"
        assert notifs_admin1[0].item_id == 42
        # El usuario de ventas NO ve nada.
        assert db.query(Notificacion).filter(Notificacion.user_id == _ventas.id).count() == 0

    def test_sin_destinatarios_retorna_lista_vacia_y_no_crea_nada(
        self, db, rol_ventas, caplog
    ) -> None:
        """
        Si no hay usuarios activos con permisos, el helper NO crea filas
        huérfanas (las fantasmas `user_id=None` son justo lo que estamos
        eliminando) y loggea WARNING para telemetría.
        """
        import logging  # noqa: PLC0415

        from app.services.notificacion_service import crear_notificaciones_para_permisos  # noqa: PLC0415

        _ = _crear_usuario(db, username="ventas_c", rol_id=rol_ventas.id)  # sin permisos de admin

        app_logger = logging.getLogger("app")
        app_logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.WARNING, logger="app"):
                creadas = crear_notificaciones_para_permisos(
                    db,
                    permisos_requeridos=PERMISOS_NOTIF,
                    tipo="compras.pedido_monto_difiere_factura",
                    mensaje="Nadie debería ver esto",
                )
        finally:
            app_logger.removeHandler(caplog.handler)

        assert creadas == []
        # No se creó ninguna notificación huérfana.
        assert db.query(Notificacion).count() == 0
        # Logueó WARNING para telemetría.
        mensajes = " ".join(r.getMessage() for r in caplog.records)
        assert "ningún usuario activo con permisos" in mensajes
