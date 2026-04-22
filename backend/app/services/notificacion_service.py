"""
Servicio para crear y gestionar notificaciones con severidad automática.

Calcula automáticamente la severidad basándose en:
- Diferencia de markup respecto al objetivo
- Tipo de notificación
- Reglas de negocio configurables
"""

import logging
from typing import Optional
from sqlalchemy.orm import Session
from decimal import Decimal

from app.models.notificacion import Notificacion, SeveridadNotificacion, EstadoNotificacion
from app.models.notificacion_ignorada import NotificacionIgnorada
from app.models.usuario import Usuario

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Notificaciones dirigidas a admins — resueltas por permiso
# ──────────────────────────────────────────────────────────────────────────


def resolver_usuarios_con_algun_permiso(
    session: Session,
    *,
    permisos_requeridos: list[str],
) -> list[Usuario]:
    """
    Retorna la lista de usuarios activos que tienen AL MENOS UNO de los
    permisos indicados (OR lógico).

    Consulta el sistema híbrido de permisos (`PermisosService`): combina
    permisos base del rol + overrides del usuario. SUPERADMINs siempre
    matchean (tienen todos los permisos).

    Uso: dirigir notificaciones "globales" (p. ej. alertas de matching
    contable del módulo compras) a los usuarios efectivamente autorizados
    a actuar sobre ellas. Reemplaza el antipatrón `Notificacion(user_id=None)`
    que el endpoint `GET /notificaciones` no muestra a nadie
    (filtra estricto `user_id == current_user.id`).

    Args:
        session: sesión activa.
        permisos_requeridos: códigos de permiso en formato
            `'modulo.accion'` (ej: 'administracion.gestionar_ordenes_compra').

    Returns:
        Lista de `Usuario` activos con al menos uno de los permisos.
        Lista vacía si nadie matchea.
    """
    from app.services.permisos_service import PermisosService  # noqa: PLC0415

    svc = PermisosService(session)
    activos = session.query(Usuario).filter(Usuario.activo.is_(True)).all()

    resultado: list[Usuario] = []
    for u in activos:
        if svc.tiene_algun_permiso(u, permisos_requeridos):
            resultado.append(u)
    return resultado


def crear_notificaciones_para_permisos(
    session: Session,
    *,
    permisos_requeridos: list[str],
    tipo: str,
    mensaje: str,
    severidad: SeveridadNotificacion = SeveridadNotificacion.WARNING,
    estado: EstadoNotificacion = EstadoNotificacion.PENDIENTE,
    item_id: Optional[int] = None,
) -> list[Notificacion]:
    """
    Crea una notificación por cada usuario activo que tenga al menos uno
    de los permisos indicados.

    Reemplaza el patrón `Notificacion(user_id=None, ...)` que no era visible
    para ningún usuario (el listado de notificaciones filtra estrictamente
    `user_id == current_user.id`). Con este helper cada admin ve su propia
    fila y puede marcarla como leída/revisada/descartada en forma individual.

    NO commitea — las notificaciones se agregan a la sesión; el caller
    (dentro de una transacción mayor) decide el commit.

    Si no hay usuarios con los permisos → loggea WARNING y retorna `[]`
    sin crear notificaciones.

    Args:
        session: tx activa.
        permisos_requeridos: códigos de permiso (OR lógico).
        tipo: categoría de la notificación (ej: 'compras.pedido_monto_difiere_factura').
        mensaje: texto humano de la notificación.
        severidad: enum `SeveridadNotificacion` (default WARNING).
        estado: enum `EstadoNotificacion` (default PENDIENTE).
        item_id: id de referencia opcional (pedido, NC, etc.) para agrupación.

    Returns:
        Lista de `Notificacion` agregadas a la sesión (aún sin flush/commit).
    """
    destinatarios = resolver_usuarios_con_algun_permiso(
        session,
        permisos_requeridos=permisos_requeridos,
    )
    if not destinatarios:
        logger.warning(
            "crear_notificaciones_para_permisos: ningún usuario activo con permisos %s — "
            "notificación tipo='%s' no será visible para nadie.",
            permisos_requeridos,
            tipo,
        )
        return []

    creadas: list[Notificacion] = []
    for user in destinatarios:
        notif = Notificacion(
            user_id=user.id,
            tipo=tipo,
            item_id=item_id,
            mensaje=mensaje,
            severidad=severidad,
            estado=estado,
            leida=False,
        )
        session.add(notif)
        creadas.append(notif)

    logger.info(
        "crear_notificaciones_para_permisos: tipo='%s' creadas=%d destinatarios_ids=%s",
        tipo,
        len(creadas),
        [u.id for u in destinatarios],
    )
    return creadas


class NotificacionService:
    """
    Servicio para gestión inteligente de notificaciones.

    Responsabilidades:
    - Calcular severidad automática
    - Crear notificaciones con metadata completa
    - Validar y evitar duplicados
    """

    # Configuración de umbrales por defecto (pueden ser configurables)
    UMBRAL_CRITICAL = 15.0  # >15% de diferencia → critical
    UMBRAL_URGENT = 25.0  # >25% de diferencia → urgent
    UMBRAL_WARNING = 10.0  # >10% de diferencia → warning

    def __init__(self, db: Session):
        self.db = db

    def calcular_severidad_markup(
        self, markup_real: Optional[Decimal], markup_objetivo: Optional[Decimal], tipo_notificacion: str
    ) -> SeveridadNotificacion:
        """
        Calcula la severidad de una notificación de markup.

        Lógica (DIFERENCIA ABSOLUTA en puntos porcentuales):
        - >25 puntos → URGENT (ej: 5% vs 30% = 25 puntos de diferencia)
        - >15 puntos → CRITICAL
        - >10 puntos → WARNING
        - <=10 puntos → INFO

        IMPORTANTE: No confundir con diferencia porcentual RELATIVA.
        Ejemplo: markup real -1.32% vs objetivo 3.79%
          → Diferencia absoluta: |-1.32 - 3.79| = 5.11 puntos → WARNING
          → Diferencia relativa: |(-1.32-3.79)/3.79*100| = 134.8% (INCORRECTO)

        Args:
            markup_real: Markup real de la venta (ej: -1.32)
            markup_objetivo: Markup objetivo configurado (ej: 3.79)
            tipo_notificacion: Tipo de notificación (markup_bajo, etc)

        Returns:
            Severidad calculada
        """
        # Si no hay datos de markup, retornar INFO
        if markup_real is None or markup_objetivo is None:
            return SeveridadNotificacion.INFO

        # Calcular DIFERENCIA ABSOLUTA en puntos porcentuales
        # Ejemplo: -1.32% vs 3.79% → |-1.32 - 3.79| = 5.11 puntos
        diferencia_absoluta = abs(float(markup_real) - float(markup_objetivo))

        # Aplicar umbrales (en puntos porcentuales)
        if diferencia_absoluta > self.UMBRAL_URGENT:
            return SeveridadNotificacion.URGENT
        elif diferencia_absoluta > self.UMBRAL_CRITICAL:
            return SeveridadNotificacion.CRITICAL
        elif diferencia_absoluta > self.UMBRAL_WARNING:
            return SeveridadNotificacion.WARNING
        else:
            return SeveridadNotificacion.INFO

    def calcular_severidad(
        self, tipo: str, markup_real: Optional[Decimal] = None, markup_objetivo: Optional[Decimal] = None, **kwargs
    ) -> SeveridadNotificacion:
        """
        Calcula la severidad según el tipo de notificación.

        Args:
            tipo: Tipo de notificación
            markup_real: Markup real (para notificaciones de markup)
            markup_objetivo: Markup objetivo (para notificaciones de markup)
            **kwargs: Otros parámetros específicos del tipo

        Returns:
            Severidad calculada
        """
        # Notificaciones de markup
        if tipo in ["markup_bajo", "markup_negativo", "markup_fuera_rango"]:
            return self.calcular_severidad_markup(markup_real, markup_objetivo, tipo)

        # Notificaciones de stock
        elif tipo in ["stock_bajo", "sin_stock"]:
            # Stock bajo es warning, sin stock es critical
            return SeveridadNotificacion.CRITICAL if tipo == "sin_stock" else SeveridadNotificacion.WARNING

        # Notificaciones de precios
        elif tipo in ["precio_desactualizado", "precio_manual_requerido"]:
            return SeveridadNotificacion.WARNING

        # Notificaciones de errores de integración
        elif tipo in ["error_ml", "error_tienda_nube", "error_sync"]:
            return SeveridadNotificacion.CRITICAL

        # Default: INFO
        else:
            return SeveridadNotificacion.INFO

    def esta_ignorada(self, user_id: int, item_id: Optional[int], tipo: str, markup_real: Optional[Decimal]) -> bool:
        """
        Verifica si existe una regla de ignorar para esta combinación.

        Args:
            user_id: ID del usuario
            item_id: ID del producto
            tipo: Tipo de notificación
            markup_real: Markup real

        Returns:
            True si está ignorada, False si debe notificar
        """
        if not item_id or markup_real is None:
            return False

        # Redondear markup a 2 decimales para matching
        markup_redondeado = round(float(markup_real), 2)

        # Buscar regla que matchee
        regla = (
            self.db.query(NotificacionIgnorada)
            .filter(
                NotificacionIgnorada.user_id == user_id,
                NotificacionIgnorada.item_id == item_id,
                NotificacionIgnorada.tipo == tipo,
                NotificacionIgnorada.markup_real == markup_redondeado,
            )
            .first()
        )

        return regla is not None

    def crear_notificacion(
        self,
        user_id: int,
        tipo: str,
        mensaje: str,
        severidad: Optional[SeveridadNotificacion] = None,
        **campos_adicionales,
    ) -> Optional[Notificacion]:
        """
        Crea una notificación con severidad automática.

        IMPORTANTE: Verifica primero si está ignorada. Si lo está, retorna None.

        Args:
            user_id: ID del usuario destinatario
            tipo: Tipo de notificación
            mensaje: Mensaje descriptivo
            severidad: Severidad manual (si None, se calcula automáticamente)
            **campos_adicionales: Otros campos (item_id, markup_real, etc)

        Returns:
            Notificación creada o None si está ignorada
        """
        # Verificar si está ignorada
        item_id = campos_adicionales.get("item_id")
        markup_real = campos_adicionales.get("markup_real")

        if self.esta_ignorada(user_id, item_id, tipo, markup_real):
            logger.info(
                f"Notificación ignorada: tipo={tipo}, user_id={user_id}, "
                f"item_id={item_id}, markup={markup_real} (regla de ignorar activa)"
            )
            return None

        # Calcular severidad si no se proveyó
        if severidad is None:
            severidad = self.calcular_severidad(
                tipo=tipo,
                markup_real=markup_real,
                markup_objetivo=campos_adicionales.get("markup_objetivo"),
                **campos_adicionales,
            )

        # Crear notificación
        notificacion = Notificacion(
            user_id=user_id,
            tipo=tipo,
            mensaje=mensaje,
            severidad=severidad,
            estado=EstadoNotificacion.PENDIENTE,
            **campos_adicionales,
        )

        self.db.add(notificacion)
        self.db.commit()
        self.db.refresh(notificacion)

        logger.info(
            f"Notificación creada: tipo={tipo}, severidad={severidad.value}, user_id={user_id}, item_id={item_id}"
        )

        return notificacion

    def agregar_regla_ignorar(
        self,
        user_id: int,
        item_id: int,
        tipo: str,
        markup_real: Decimal,
        codigo_producto: Optional[str] = None,
        descripcion_producto: Optional[str] = None,
        notificacion_id: Optional[int] = None,
    ) -> NotificacionIgnorada:
        """
        Agrega una regla para ignorar futuras notificaciones.

        Args:
            user_id: ID del usuario
            item_id: ID del producto
            tipo: Tipo de notificación
            markup_real: Markup real (se redondea a 2 decimales)
            codigo_producto: Código del producto (opcional, para UI)
            descripcion_producto: Descripción del producto (opcional, para UI)
            notificacion_id: ID de la notificación que disparó el ignorar

        Returns:
            Regla creada (o existente si ya había una)
        """
        markup_redondeado = round(float(markup_real), 2)

        # Verificar si ya existe
        regla_existente = (
            self.db.query(NotificacionIgnorada)
            .filter(
                NotificacionIgnorada.user_id == user_id,
                NotificacionIgnorada.item_id == item_id,
                NotificacionIgnorada.tipo == tipo,
                NotificacionIgnorada.markup_real == markup_redondeado,
            )
            .first()
        )

        if regla_existente:
            logger.info(f"Regla de ignorar ya existe: {regla_existente}")
            return regla_existente

        # Crear nueva regla
        regla = NotificacionIgnorada(
            user_id=user_id,
            item_id=item_id,
            tipo=tipo,
            markup_real=markup_redondeado,
            codigo_producto=codigo_producto,
            descripcion_producto=descripcion_producto,
            ignorado_por_notificacion_id=notificacion_id,
        )

        self.db.add(regla)
        self.db.commit()
        self.db.refresh(regla)

        logger.info(f"Regla de ignorar creada: user={user_id}, item={item_id}, tipo={tipo}, markup={markup_redondeado}")

        return regla

    def existe_notificacion_similar(
        self,
        user_id: int,
        tipo: str,
        item_id: Optional[int],
        id_operacion: Optional[int] = None,
        tolerancia_horas: int = 24,
    ) -> bool:
        """
        Verifica si existe una notificación similar reciente para evitar spam.

        Args:
            user_id: ID del usuario
            tipo: Tipo de notificación
            item_id: ID del item
            id_operacion: ID de operación (opcional)
            tolerancia_horas: Horas a considerar como "reciente"

        Returns:
            True si existe una similar, False si no
        """
        from datetime import UTC, datetime, timedelta

        fecha_limite = datetime.now(UTC) - timedelta(hours=tolerancia_horas)

        query = self.db.query(Notificacion).filter(
            Notificacion.user_id == user_id,
            Notificacion.tipo == tipo,
            Notificacion.item_id == item_id,
            Notificacion.fecha_creacion >= fecha_limite,
            Notificacion.estado != EstadoNotificacion.DESCARTADA,
        )

        if id_operacion:
            query = query.filter(Notificacion.id_operacion == id_operacion)

        return query.first() is not None

    def configurar_umbrales(
        self, warning: Optional[float] = None, critical: Optional[float] = None, urgent: Optional[float] = None
    ):
        """
        Configura los umbrales de severidad dinámicamente.

        Args:
            warning: Umbral para WARNING (% de diferencia)
            critical: Umbral para CRITICAL (% de diferencia)
            urgent: Umbral para URGENT (% de diferencia)
        """
        if warning is not None:
            self.UMBRAL_WARNING = warning
        if critical is not None:
            self.UMBRAL_CRITICAL = critical
        if urgent is not None:
            self.UMBRAL_URGENT = urgent

        logger.info(
            f"Umbrales configurados: WARNING={self.UMBRAL_WARNING}%, "
            f"CRITICAL={self.UMBRAL_CRITICAL}%, URGENT={self.UMBRAL_URGENT}%"
        )
