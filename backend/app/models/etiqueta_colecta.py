from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Date,
    DateTime,
    Text,
    Index,
)
from sqlalchemy.sql import func
from app.core.database import Base


class EtiquetaColecta(Base):
    """
    Etiquetas de colecta — importadas desde ZPL para checkeo de estados.

    A diferencia de etiquetas_envio (flex), estas solo se usan para
    verificar el estado ERP y ML de los envíos de colecta.
    No tienen logística, transporte, cordón, costos, ni pistoleado.

    shipping_id viene del QR de la etiqueta y se cruza con
    tb_mercadolibre_orders_shipping.mlshippingid para obtener
    datos del envío (destinatario, estado ML).

    El estado ERP se obtiene cruzando con tb_sale_order_header
    y tb_sale_order_status (mismo mecanismo que etiquetas_envio).
    """

    __tablename__ = "etiquetas_colecta"

    id = Column(Integer, primary_key=True, index=True)
    shipping_id = Column(String(50), unique=True, nullable=False, index=True)
    sender_id = Column(BigInteger, nullable=True)
    hash_code = Column(Text, nullable=True)
    nombre_archivo = Column(String(255), nullable=True)

    fecha_carga = Column(Date, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("idx_etiquetas_colecta_fecha", "fecha_carga"),)
