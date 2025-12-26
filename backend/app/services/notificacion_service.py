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

logger = logging.getLogger(__name__)


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
    UMBRAL_URGENT = 25.0    # >25% de diferencia → urgent
    UMBRAL_WARNING = 10.0   # >10% de diferencia → warning
    
    def __init__(self, db: Session):
        self.db = db
    
    def calcular_severidad_markup(
        self,
        markup_real: Optional[Decimal],
        markup_objetivo: Optional[Decimal],
        tipo_notificacion: str
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
        self,
        tipo: str,
        markup_real: Optional[Decimal] = None,
        markup_objetivo: Optional[Decimal] = None,
        **kwargs
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
        if tipo in ['markup_bajo', 'markup_negativo', 'markup_fuera_rango']:
            return self.calcular_severidad_markup(markup_real, markup_objetivo, tipo)
        
        # Notificaciones de stock
        elif tipo in ['stock_bajo', 'sin_stock']:
            # Stock bajo es warning, sin stock es critical
            return SeveridadNotificacion.CRITICAL if tipo == 'sin_stock' else SeveridadNotificacion.WARNING
        
        # Notificaciones de precios
        elif tipo in ['precio_desactualizado', 'precio_manual_requerido']:
            return SeveridadNotificacion.WARNING
        
        # Notificaciones de errores de integración
        elif tipo in ['error_ml', 'error_tienda_nube', 'error_sync']:
            return SeveridadNotificacion.CRITICAL
        
        # Default: INFO
        else:
            return SeveridadNotificacion.INFO
    
    def esta_ignorada(
        self,
        user_id: int,
        item_id: Optional[int],
        tipo: str,
        markup_real: Optional[Decimal]
    ) -> bool:
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
        regla = self.db.query(NotificacionIgnorada).filter(
            NotificacionIgnorada.user_id == user_id,
            NotificacionIgnorada.item_id == item_id,
            NotificacionIgnorada.tipo == tipo,
            NotificacionIgnorada.markup_real == markup_redondeado
        ).first()
        
        return regla is not None
    
    def crear_notificacion(
        self,
        user_id: int,
        tipo: str,
        mensaje: str,
        severidad: Optional[SeveridadNotificacion] = None,
        **campos_adicionales
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
        item_id = campos_adicionales.get('item_id')
        markup_real = campos_adicionales.get('markup_real')
        
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
                markup_objetivo=campos_adicionales.get('markup_objetivo'),
                **campos_adicionales
            )
        
        # Crear notificación
        notificacion = Notificacion(
            user_id=user_id,
            tipo=tipo,
            mensaje=mensaje,
            severidad=severidad,
            estado=EstadoNotificacion.PENDIENTE,
            **campos_adicionales
        )
        
        self.db.add(notificacion)
        self.db.commit()
        self.db.refresh(notificacion)
        
        logger.info(
            f"Notificación creada: tipo={tipo}, severidad={severidad.value}, "
            f"user_id={user_id}, item_id={item_id}"
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
        notificacion_id: Optional[int] = None
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
        regla_existente = self.db.query(NotificacionIgnorada).filter(
            NotificacionIgnorada.user_id == user_id,
            NotificacionIgnorada.item_id == item_id,
            NotificacionIgnorada.tipo == tipo,
            NotificacionIgnorada.markup_real == markup_redondeado
        ).first()
        
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
            ignorado_por_notificacion_id=notificacion_id
        )
        
        self.db.add(regla)
        self.db.commit()
        self.db.refresh(regla)
        
        logger.info(
            f"Regla de ignorar creada: user={user_id}, item={item_id}, "
            f"tipo={tipo}, markup={markup_redondeado}"
        )
        
        return regla
    
    def existe_notificacion_similar(
        self,
        user_id: int,
        tipo: str,
        item_id: Optional[int],
        id_operacion: Optional[int] = None,
        tolerancia_horas: int = 24
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
        from datetime import datetime, timedelta
        
        fecha_limite = datetime.now() - timedelta(hours=tolerancia_horas)
        
        query = self.db.query(Notificacion).filter(
            Notificacion.user_id == user_id,
            Notificacion.tipo == tipo,
            Notificacion.item_id == item_id,
            Notificacion.fecha_creacion >= fecha_limite,
            Notificacion.estado != EstadoNotificacion.DESCARTADA
        )
        
        if id_operacion:
            query = query.filter(Notificacion.id_operacion == id_operacion)
        
        return query.first() is not None
    
    def configurar_umbrales(
        self,
        warning: Optional[float] = None,
        critical: Optional[float] = None,
        urgent: Optional[float] = None
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
