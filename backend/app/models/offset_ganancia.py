from sqlalchemy import Column, Integer, String, Float, DateTime, Date, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class OffsetGanancia(Base):
    """
    Offset de ganancia que se suma al limpio para calcular rentabilidad real.
    Puede aplicar a nivel marca, categoría, subcategoría o producto individual.
    """

    __tablename__ = "offsets_ganancia"

    id = Column(Integer, primary_key=True, index=True)

    # Nivel de aplicación (solo uno debe tener valor, los demás NULL)
    marca = Column(String(100), index=True, nullable=True)
    categoria = Column(String(100), index=True, nullable=True)
    subcategoria_id = Column(Integer, index=True, nullable=True)
    item_id = Column(Integer, ForeignKey("productos_erp.item_id"), index=True, nullable=True)

    # Monto del offset
    monto = Column(Float, nullable=True)  # Para monto_fijo y monto_por_unidad

    # Tipo de offset
    tipo_offset = Column(String(20), default="monto_fijo")  # 'monto_fijo', 'monto_por_unidad', 'porcentaje_costo'

    # Moneda (para monto_fijo y monto_por_unidad)
    moneda = Column(String(3), default="ARS")  # 'ARS', 'USD'

    # Tipo de cambio (para conversión USD -> ARS)
    tipo_cambio = Column(Float, nullable=True)

    # Porcentaje (para porcentaje_costo)
    porcentaje = Column(Float, nullable=True)

    # Descripción/concepto del offset (ej: "Rebate Q4 2024")
    descripcion = Column(String(255), nullable=True)

    # Período de aplicación
    fecha_desde = Column(Date, nullable=False)
    fecha_hasta = Column(Date, nullable=True)  # NULL = sin fecha fin

    # Grupo de offsets (para límites compartidos)
    grupo_id = Column(Integer, ForeignKey("offset_grupos.id"), index=True, nullable=True)

    # Límites para offsets tipo monto_por_unidad
    max_unidades = Column(Integer, nullable=True)  # Máximo de unidades que aplica el offset
    max_monto_usd = Column(Float, nullable=True)  # Máximo monto en USD que aplica el offset

    # Monto consumido (calculado, se actualiza periódicamente)
    monto_consumido = Column(Float, nullable=True, default=0)  # Monto total consumido en ARS

    # Aplicación por canal
    aplica_ml = Column(Boolean, default=True)  # Aplica a Métricas ML
    aplica_fuera = Column(Boolean, default=True)  # Aplica a Ventas por Fuera de ML
    aplica_tienda_nube = Column(Boolean, default=True)  # Aplica a Tienda Nube

    # Auditoría
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())
    fecha_modificacion = Column(DateTime(timezone=True), onupdate=func.now())

    # Relaciones
    usuario = relationship("Usuario", foreign_keys=[usuario_id])
    producto = relationship("ProductoERP", foreign_keys=[item_id])
    grupo = relationship("OffsetGrupo", back_populates="offsets")
