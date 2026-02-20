from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    BigInteger,
    String,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Numeric,
    Text,
    Index,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class EtiquetaEnvio(Base):
    """
    Etiquetas de envío — tanto las importadas desde ZPL de MercadoEnvíos
    como las creadas manualmente para envíos fuera de ML.

    Envíos ML:
      shipping_id viene del QR de la etiqueta y se cruza con
      tb_mercadolibre_orders_shipping.mlshippingid para obtener
      datos del envío (destinatario, dirección, CP, etc.)

    Envíos manuales (es_manual=True):
      shipping_id se genera como "MAN_{timestamp}_{seq}". Los datos de
      dirección, receptor y estado se guardan en los campos manual_*.
      No tienen registro en tb_mercadolibre_orders_shipping.

    Las queries del listado usan COALESCE(manual_*, ml_shipping_*)
    para que ambos tipos de etiqueta se muestren igual.

    El campo fecha_envio es la fecha programada del envío y es EDITABLE
    por si se reprograma (ej: "lo llevamos mañana en vez de hoy").

    Pistoleado: operador escanea QR de etiqueta → se graban pistoleado_at,
    pistoleado_caja y pistoleado_operador_id. Validaciones de duplicado y logística.
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

    # ── Envío manual (sin ML) ────────────────────────────────────
    # Cuando es_manual=True, los datos de dirección/receptor/estado
    # viven acá en vez de en tb_mercadolibre_orders_shipping.
    es_manual = Column(Boolean, server_default="false", nullable=False)
    manual_receiver_name = Column(String(500), nullable=True)  # Destinatario
    manual_street_name = Column(String(500), nullable=True)  # Calle
    manual_street_number = Column(String(50), nullable=True)  # Número
    manual_zip_code = Column(String(50), nullable=True)  # Código postal
    manual_city_name = Column(String(500), nullable=True)  # Ciudad
    manual_status = Column(String(50), nullable=True)  # ready_to_ship, shipped, delivered
    manual_cust_id = Column(Integer, nullable=True)  # Cliente del ERP (tb_customer.cust_id)
    manual_bra_id = Column(Integer, nullable=True)  # Sucursal (tb_branch.bra_id)
    manual_soh_id = Column(BigInteger, nullable=True)  # N° pedido ERP (PK con comp_id+bra_id)
    manual_comment = Column(Text, nullable=True)  # Observaciones

    # Datos enriquecidos del ML webhook (background enrichment post-upload)
    latitud = Column(Float, nullable=True)
    longitud = Column(Float, nullable=True)
    direccion_completa = Column(String(500), nullable=True)
    direccion_comentario = Column(String(500), nullable=True)  # "Puerta negra", "Timbre 3B", etc.
    es_outlet = Column(Boolean, server_default="false", nullable=False)  # Título de item contiene "outlet"
    es_turbo = Column(Boolean, server_default="false", nullable=False)  # mlshipping_method_id == "515282"

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
        Index("idx_etiquetas_envio_es_manual", "es_manual"),
    )

    def __repr__(self) -> str:
        return f"<EtiquetaEnvio(shipping_id={self.shipping_id}, fecha={self.fecha_envio}, manual={self.es_manual})>"
