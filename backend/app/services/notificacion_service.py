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
        
        Lógica:
        - >25% diferencia → URGENT
        - >15% diferencia → CRITICAL
        - >10% diferencia → WARNING
        - <=10% diferencia → INFO
        
        Args:
            markup_real: Markup real de la venta
            markup_objetivo: Markup objetivo configurado
            tipo_notificacion: Tipo de notificación (markup_bajo, etc)
        
        Returns:
            Severidad calculada
        """
        # Si no hay datos de markup, retornar INFO
        if markup_real is None or markup_objetivo is None:
            return SeveridadNotificacion.INFO
        
        # Calcular diferencia porcentual
        if markup_objetivo == 0:
            # Si el objetivo es 0, cualquier markup negativo es crítico
            if markup_real < 0:
                return SeveridadNotificacion.URGENT
            return SeveridadNotificacion.INFO
        
        diferencia_porcentual = abs(
            (float(markup_real) - float(markup_objetivo)) / float(markup_objetivo) * 100
        )
        
        # Aplicar umbrales
        if diferencia_porcentual > self.UMBRAL_URGENT:
            return SeveridadNotificacion.URGENT
        elif diferencia_porcentual > self.UMBRAL_CRITICAL:
            return SeveridadNotificacion.CRITICAL
        elif diferencia_porcentual > self.UMBRAL_WARNING:
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
    
    def crear_notificacion(
        self,
        user_id: int,
        tipo: str,
        mensaje: str,
        severidad: Optional[SeveridadNotificacion] = None,
        **campos_adicionales
    ) -> Notificacion:
        """
        Crea una notificación con severidad automática.
        
        Args:
            user_id: ID del usuario destinatario
            tipo: Tipo de notificación
            mensaje: Mensaje descriptivo
            severidad: Severidad manual (si None, se calcula automáticamente)
            **campos_adicionales: Otros campos (item_id, markup_real, etc)
        
        Returns:
            Notificación creada
        """
        # Calcular severidad si no se proveyó
        if severidad is None:
            severidad = self.calcular_severidad(
                tipo=tipo,
                markup_real=campos_adicionales.get('markup_real'),
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
            f"user_id={user_id}, item_id={campos_adicionales.get('item_id')}"
        )
        
        return notificacion
    
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
