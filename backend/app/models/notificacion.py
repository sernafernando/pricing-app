from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Numeric, BigInteger, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class SeveridadNotificacion(str, enum.Enum):
    """Severidad/prioridad de una notificación"""
    INFO = "info"           # Normal, informativa
    WARNING = "warning"     # Advertencia, requiere atención
    CRITICAL = "critical"   # Crítica, requiere acción inmediata
    URGENT = "urgent"       # Urgente, impacto alto en negocio


class EstadoNotificacion(str, enum.Enum):
    """Estado de gestión de una notificación"""
    PENDIENTE = "pendiente"     # Creada, esperando revisión
    REVISADA = "revisada"       # Revisada por usuario, puede estar leída o no
    DESCARTADA = "descartada"   # Descartada, no requiere acción (no volver a mostrar)
    EN_GESTION = "en_gestion"   # Se está trabajando en resolverla
    RESUELTA = "resuelta"       # Resuelta, problema solucionado


class Notificacion(Base):
    __tablename__ = "notificaciones"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('usuarios.id', ondelete='CASCADE'), nullable=True, index=True)
    tipo = Column(String(50), nullable=False, index=True)  # markup_bajo, stock_bajo, precio_desactualizado, etc.
    item_id = Column(Integer, nullable=True, index=True)
    id_operacion = Column(BigInteger, nullable=True)  # ID de operación ML
    ml_id = Column(String(50), nullable=True, index=True)  # ML_id de la orden
    pack_id = Column(BigInteger, nullable=True, index=True)  # Pack ID de ML para URL
    codigo_producto = Column(String(100), nullable=True)
    descripcion_producto = Column(String(500), nullable=True)
    mensaje = Column(Text, nullable=False)
    
    # Sistema de prioridad y gestión
    severidad = Column(SQLEnum(SeveridadNotificacion), default=SeveridadNotificacion.INFO, nullable=False, index=True)
    estado = Column(SQLEnum(EstadoNotificacion), default=EstadoNotificacion.PENDIENTE, nullable=False, index=True)

    # Campos específicos para notificaciones de markup
    markup_real = Column(Numeric(10, 2), nullable=True)
    markup_objetivo = Column(Numeric(10, 2), nullable=True)
    monto_venta = Column(Numeric(12, 2), nullable=True)
    fecha_venta = Column(DateTime(timezone=True), nullable=True)

    # Campos adicionales para detalle
    pm = Column(String(100), nullable=True)  # Product Manager asignado a la marca
    costo_operacion = Column(Numeric(12, 2), nullable=True)  # Costo al momento de la venta
    costo_actual = Column(Numeric(12, 2), nullable=True)  # Costo actual
    precio_venta_unitario = Column(Numeric(12, 2), nullable=True)  # Precio unitario
    precio_publicacion = Column(Numeric(12, 2), nullable=True)  # Precio en publicación ML
    tipo_publicacion = Column(String(50), nullable=True)  # classic, gold, premium
    comision_ml = Column(Numeric(12, 2), nullable=True)  # Comisión ML
    iva_porcentaje = Column(Numeric(5, 2), nullable=True)  # % de IVA
    cantidad = Column(Integer, nullable=True)  # Cantidad vendida
    costo_envio = Column(Numeric(12, 2), nullable=True)  # Costo de envío

    # Tipos de cambio usados
    tipo_cambio_operacion = Column(Numeric(12, 4), nullable=True)  # TC usado para costo_operacion
    tipo_cambio_actual = Column(Numeric(12, 4), nullable=True)  # TC usado para costo_actual

    # Control de lectura
    leida = Column(Boolean, default=False, nullable=False, index=True)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    fecha_lectura = Column(DateTime(timezone=True), nullable=True)
    
    # Fechas de gestión
    fecha_revision = Column(DateTime(timezone=True), nullable=True)
    fecha_descarte = Column(DateTime(timezone=True), nullable=True)
    fecha_resolucion = Column(DateTime(timezone=True), nullable=True)
    
    # Notas del usuario sobre la gestión
    notas_revision = Column(Text, nullable=True)

    # Relaciones
    usuario = relationship("Usuario", backref="notificaciones")
    
    @property
    def diferencia_markup(self) -> float:
        """Calcula la diferencia entre markup real y objetivo"""
        if self.markup_real is not None and self.markup_objetivo is not None:
            return float(self.markup_real - self.markup_objetivo)
        return 0.0
    
    @property
    def diferencia_markup_porcentual(self) -> float:
        """Calcula la diferencia porcentual respecto al objetivo"""
        if self.markup_objetivo and self.markup_objetivo != 0:
            return (float(self.markup_real - self.markup_objetivo) / float(self.markup_objetivo)) * 100
        return 0.0
    
    @property
    def es_critica(self) -> bool:
        """Verifica si la notificación es crítica"""
        return self.severidad in [SeveridadNotificacion.CRITICAL, SeveridadNotificacion.URGENT]
    
    @property
    def requiere_atencion(self) -> bool:
        """Verifica si requiere atención (no descartada ni resuelta)"""
        return self.estado in [EstadoNotificacion.PENDIENTE, EstadoNotificacion.REVISADA, EstadoNotificacion.EN_GESTION]
