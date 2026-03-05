"""
Artículo dentro de un caso RMA.

Cada item representa un producto devuelto con su propio ciclo de vida
independiente (recepción, revisión, proceso interno).
Un caso puede tener N items, incluso del mismo producto con distintas series.
"""

from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, Numeric, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class RmaCasoItem(Base):
    """
    Línea de detalle del caso RMA. Cada artículo tiene sus propias etapas.
    """

    __tablename__ = "rma_caso_items"

    id = Column(Integer, primary_key=True, index=True)
    caso_id = Column(Integer, ForeignKey("rma_casos.id", ondelete="CASCADE"), nullable=False, index=True)

    # --- Datos del artículo (auto-completados de la traza) ---
    serial_number = Column(String(100), nullable=True, index=True)
    item_id = Column(BigInteger, nullable=True, index=True)
    is_id = Column(BigInteger, nullable=True)  # FK lógica a tb_item_serials
    it_transaction = Column(BigInteger, nullable=True)  # para vincular con factura
    ean = Column(String(50), nullable=True)
    producto_desc = Column(String(500), nullable=True)
    precio = Column(Numeric(15, 2), nullable=True)
    estado_facturacion = Column(String(50), nullable=True)  # "Facturado", "Sin facturar"
    link_ml = Column(String(500), nullable=True)

    # --- Tab: Recepción (operador que recibe) ---
    estado_recepcion_id = Column(Integer, ForeignKey("rma_seguimiento_opciones.id"), nullable=True, index=True)
    costo_envio = Column(Numeric(15, 2), nullable=True)
    causa_devolucion_id = Column(Integer, ForeignKey("rma_seguimiento_opciones.id"), nullable=True, index=True)
    recepcion_usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    recepcion_fecha = Column(DateTime(timezone=True), nullable=True)

    # --- Tab: Revisión (operador técnico) ---
    apto_venta_id = Column(Integer, ForeignKey("rma_seguimiento_opciones.id"), nullable=True, index=True)
    requirio_reacondicionamiento = Column(Boolean, nullable=True)
    estado_revision_id = Column(Integer, ForeignKey("rma_seguimiento_opciones.id"), nullable=True, index=True)
    descripcion_falla = Column(Text, nullable=True)  # texto libre: qué falla tiene el producto
    revision_usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    revision_fecha = Column(DateTime(timezone=True), nullable=True)

    # --- Tab: Proceso Interno ---
    estado_proceso_id = Column(Integer, ForeignKey("rma_seguimiento_opciones.id"), nullable=True, index=True)
    deposito_destino_id = Column(Integer, nullable=True, index=True)  # stor_id de tb_storage (sin FK)
    enviado_fisicamente_deposito = Column(Boolean, nullable=True)
    corroborar_nc = Column(Boolean, nullable=True)
    requirio_rma_interno = Column(Boolean, nullable=True)

    # --- Devolución parcial ---
    requiere_nota_credito = Column(Boolean, nullable=True)
    debe_facturarse = Column(Boolean, nullable=True)

    # --- Tab: Envío a proveedor ---
    supp_id = Column(BigInteger, nullable=True, index=True)  # FK lógica a tb_supplier
    proveedor_nombre = Column(String(255), nullable=True)  # desnormalizado
    enviado_proveedor = Column(Boolean, nullable=True)
    fecha_envio_proveedor = Column(DateTime(timezone=True), nullable=True)
    fecha_respuesta_proveedor = Column(DateTime(timezone=True), nullable=True)
    estado_proveedor_id = Column(Integer, ForeignKey("rma_seguimiento_opciones.id"), nullable=True, index=True)
    nc_proveedor = Column(String(100), nullable=True)  # nro de NC del proveedor
    monto_nc_proveedor = Column(Numeric(15, 2), nullable=True)

    # --- Observaciones por artículo ---
    observaciones = Column(Text, nullable=True)

    # --- Vinculación con ERP (cuando se genera RMA en el ERP) ---
    rmah_id = Column(BigInteger, nullable=True)
    rmad_id = Column(BigInteger, nullable=True)

    # --- Sistema ---
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # --- Relaciones ---
    caso = relationship("RmaCaso", back_populates="items")
    estado_recepcion = relationship("RmaSeguimientoOpcion", foreign_keys=[estado_recepcion_id])
    causa_devolucion = relationship("RmaSeguimientoOpcion", foreign_keys=[causa_devolucion_id])
    apto_venta = relationship("RmaSeguimientoOpcion", foreign_keys=[apto_venta_id])
    estado_revision = relationship("RmaSeguimientoOpcion", foreign_keys=[estado_revision_id])
    estado_proceso = relationship("RmaSeguimientoOpcion", foreign_keys=[estado_proceso_id])
    # deposito_destino: almacena stor_id de tb_storage directamente (sin FK ni relationship)
    estado_proveedor = relationship("RmaSeguimientoOpcion", foreign_keys=[estado_proveedor_id])
    recepcion_usuario = relationship("Usuario", foreign_keys=[recepcion_usuario_id])
    revision_usuario = relationship("Usuario", foreign_keys=[revision_usuario_id])

    def __repr__(self) -> str:
        return (
            f"<RmaCasoItem(id={self.id}, caso_id={self.caso_id}, "
            f"serial='{self.serial_number}', item_id={self.item_id})>"
        )
