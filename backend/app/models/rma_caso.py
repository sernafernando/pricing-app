"""
Caso de RMA Seguimiento — entidad principal del módulo.

Un caso agrupa uno o más artículos devueltos por un mismo cliente/pedido.
Es la fuente de verdad del ciclo de vida del RMA; el ERP se usa solo
para gestión contable (NC, movimientos de depósito).

Flujo:
1. Operador busca por serie o ID ML → se auto-completan datos de la traza
2. Se crea el caso con los artículos devueltos
3. Cada artículo pasa por etapas: recepción → revisión → proceso interno
4. A nivel caso se gestiona: reclamo ML, pedidos sin factura, observaciones
"""

from sqlalchemy import Column, Integer, BigInteger, String, Boolean, Date, DateTime, Numeric, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class RmaCaso(Base):
    """
    Header del caso RMA. Un caso = un cliente/pedido con N artículos devueltos.
    """

    __tablename__ = "rma_casos"

    id = Column(Integer, primary_key=True, index=True)

    # Número de caso auto-generado (RMA-YYYY-NNNN)
    numero_caso = Column(String(20), unique=True, nullable=False, index=True)

    # --- Datos del cliente (desnormalizados de la traza) ---
    cust_id = Column(BigInteger, nullable=True, index=True)
    cliente_nombre = Column(String(255), nullable=True)
    cliente_dni = Column(String(20), nullable=True)
    cliente_numero = Column(Integer, nullable=True)

    # --- Datos del pedido ---
    ml_id = Column(String(50), nullable=True, index=True)
    origen = Column(String(50), nullable=True)  # "mercadolibre", "tienda_nube", "mostrador"

    # Estado general del caso
    estado = Column(String(50), default="abierto", nullable=False, index=True)

    # --- Flag de proceso (se setea cuando el transporte pasa a "BORRAR PEDIDO" en ERP) ---
    marcado_borrar_pedido = Column(Boolean, nullable=True)

    # --- Tab: Reclamo Mercadolibre (a nivel caso) ---
    estado_reclamo_ml_id = Column(Integer, ForeignKey("rma_seguimiento_opciones.id"), nullable=True, index=True)
    cobertura_ml_id = Column(Integer, ForeignKey("rma_seguimiento_opciones.id"), nullable=True, index=True)
    monto_cubierto = Column(Numeric(15, 2), nullable=True)

    # --- Tab: Observaciones ---
    observaciones = Column(Text, nullable=True)

    # --- Tab: Auditoría ---
    corroborar_nc = Column(String(100), nullable=True)
    fecha_caso = Column(Date, nullable=True)

    # --- Soft delete ---
    activo = Column(Boolean, nullable=False, default=True, server_default="true", index=True)
    eliminado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    eliminado_at = Column(DateTime(timezone=True), nullable=True)
    eliminado_motivo = Column(Text, nullable=True)

    # --- Sistema ---
    creado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # --- Relaciones ---
    items = relationship("RmaCasoItem", back_populates="caso", cascade="all, delete-orphan")
    historial = relationship("RmaCasoHistorial", back_populates="caso", cascade="all, delete-orphan")
    creado_por = relationship("Usuario", foreign_keys=[creado_por_id])
    eliminado_por = relationship("Usuario", foreign_keys=[eliminado_por_id])
    estado_reclamo_ml = relationship("RmaSeguimientoOpcion", foreign_keys=[estado_reclamo_ml_id])
    cobertura_ml = relationship("RmaSeguimientoOpcion", foreign_keys=[cobertura_ml_id])

    def __repr__(self) -> str:
        return f"<RmaCaso(id={self.id}, numero_caso='{self.numero_caso}', estado='{self.estado}')>"
