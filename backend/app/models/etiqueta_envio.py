from sqlalchemy import Column, Integer, BigInteger, String, Date, DateTime, Float, ForeignKey, Numeric, Text, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class EtiquetaEnvio(Base):
    """
    Etiquetas de envío extraídas de archivos ZPL de MercadoEnvíos.
    Cada etiqueta tiene un shipping_id único (del QR de la etiqueta)
    que se cruza con tb_mercadolibre_orders_shipping.mlshippingid
    para obtener datos del envío (destinatario, dirección, CP, etc.)

    El campo fecha_envio es la fecha programada del envío y es EDITABLE
    por si se reprograma (ej: "lo llevamos mañana en vez de hoy").

    Pistoleado: operador escanea QR de etiqueta → se graban pistoleado_at,
    pistoleado_caja y pistoleado_operador_id. Validaciones de duplicado y logística.

    TODO: Constantes de valor por cordón — agregar tabla/config con
    costo por cordón (CABA=$X, C1=$Y, C2=$Z, C3=$W) para exportación.

    TODO: Exportación por rango de fechas — endpoint que agrupe
    etiquetas por fecha_envio + cordón y calcule costo total.
    """

    __tablename__ = "etiquetas_envio"

    id = Column(Integer, primary_key=True, index=True)
    shipping_id = Column(String(50), unique=True, nullable=False, index=True)
    sender_id = Column(BigInteger, nullable=True)
    hash_code = Column(Text, nullable=True)
    nombre_archivo = Column(String(255), nullable=True)  # De qué archivo .zip/.txt vino

    fecha_envio = Column(Date, nullable=False)  # Fecha programada del envío (editable)
    logistica_id = Column(Integer, ForeignKey("logisticas.id"), nullable=True)

    # Costo manual — override del costo calculado por logistica_costo_cordon.
    # Si no es NULL, prevalece sobre el costo automático.
    costo_override = Column(Numeric(12, 2), nullable=True)

    # Datos enriquecidos del ML webhook (background enrichment post-upload)
    latitud = Column(Float, nullable=True)
    longitud = Column(Float, nullable=True)
    direccion_completa = Column(String(500), nullable=True)
    direccion_comentario = Column(String(500), nullable=True)  # "Puerta negra", "Timbre 3B", etc.

    # Pistoleado — escaneo de paquetes con asignación a cajas
    pistoleado_at = Column(DateTime(timezone=True), nullable=True)
    pistoleado_caja = Column(String(50), nullable=True)
    pistoleado_operador_id = Column(Integer, ForeignKey("operadores.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    logistica = relationship("Logistica", lazy="joined")
    pistoleado_operador = relationship("Operador", lazy="joined")

    __table_args__ = (
        Index("idx_etiquetas_envio_fecha", "fecha_envio"),
        Index("idx_etiquetas_envio_logistica", "logistica_id"),
        Index("idx_etiquetas_pistoleado_operador", "pistoleado_operador_id"),
    )

    def __repr__(self) -> str:
        return f"<EtiquetaEnvio(shipping_id={self.shipping_id}, fecha={self.fecha_envio})>"
