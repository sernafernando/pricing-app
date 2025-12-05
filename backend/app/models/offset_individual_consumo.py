"""
Modelo para trackear el consumo de offsets individuales (sin grupo).
Registra cada venta que consume un offset individual con límite.
"""
from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Numeric, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class OffsetIndividualConsumo(Base):
    """
    Registro de consumo de un offset individual (sin grupo).
    Cada vez que una venta consume un offset individual con límite,
    se registra aquí para poder calcular el consumo acumulado.
    """
    __tablename__ = "offset_individual_consumo"

    id = Column(Integer, primary_key=True, index=True)

    # Referencia al offset
    offset_id = Column(Integer, ForeignKey('offsets_ganancia.id'), index=True, nullable=False)

    # Referencia a la venta (puede ser ML o fuera de ML)
    id_operacion = Column(BigInteger, index=True, nullable=True)  # Para ventas ML
    venta_fuera_id = Column(Integer, index=True, nullable=True)  # Para ventas fuera ML

    # Tipo de venta
    tipo_venta = Column(String(20), nullable=False)  # 'ml' o 'fuera_ml'

    # Datos de la venta al momento del consumo
    fecha_venta = Column(DateTime(timezone=True), index=True, nullable=False)
    item_id = Column(Integer, index=True)
    cantidad = Column(Integer, nullable=False)

    # Monto del offset aplicado
    monto_offset_aplicado = Column(Numeric(18, 2), nullable=False)  # Monto en ARS
    monto_offset_usd = Column(Numeric(18, 2), nullable=True)  # Monto en USD

    # Cotización usada
    cotizacion_dolar = Column(Numeric(10, 4), nullable=True)

    # Auditoría
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relaciones
    offset = relationship("OffsetGanancia", foreign_keys=[offset_id])


class OffsetIndividualResumen(Base):
    """
    Resumen de consumo por offset individual.
    Se actualiza cada vez que se agrega un consumo.
    Permite consultas rápidas del estado del offset.
    """
    __tablename__ = "offset_individual_resumen"

    id = Column(Integer, primary_key=True, index=True)

    # Referencia al offset
    offset_id = Column(Integer, ForeignKey('offsets_ganancia.id'), unique=True, index=True, nullable=False)

    # Totales acumulados (desde fecha_desde del offset hasta hoy)
    total_unidades = Column(Integer, default=0)
    total_monto_ars = Column(Numeric(18, 2), default=0)
    total_monto_usd = Column(Numeric(18, 2), default=0)

    # Cantidad de ventas
    cantidad_ventas = Column(Integer, default=0)

    # Estado
    limite_alcanzado = Column(String(20), nullable=True)  # 'unidades', 'monto', None
    fecha_limite_alcanzado = Column(DateTime(timezone=True), nullable=True)

    # Última actualización
    ultima_venta_fecha = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relaciones
    offset = relationship("OffsetGanancia", foreign_keys=[offset_id])
