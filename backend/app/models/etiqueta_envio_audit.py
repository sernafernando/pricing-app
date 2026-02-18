"""
Auditoría de etiquetas de envío eliminadas.

Antes de borrar una etiqueta de etiquetas_envio, se copia acá
con el usuario que la borró y el timestamp. Así nunca se pierde data.
"""

from sqlalchemy import Column, Integer, BigInteger, String, Date, DateTime, Float, Text, Index
from sqlalchemy.sql import func
from app.core.database import Base


class EtiquetaEnvioAudit(Base):
    """Copia de etiquetas borradas con datos de auditoría."""

    __tablename__ = "etiquetas_envio_audit"

    id = Column(Integer, primary_key=True, index=True)

    # Datos originales de la etiqueta
    shipping_id = Column(String(50), nullable=False, index=True)
    sender_id = Column(BigInteger, nullable=True)
    hash_code = Column(Text, nullable=True)
    nombre_archivo = Column(String(255), nullable=True)
    fecha_envio = Column(Date, nullable=False)
    logistica_id = Column(Integer, nullable=True)
    latitud = Column(Float, nullable=True)
    longitud = Column(Float, nullable=True)
    direccion_completa = Column(String(500), nullable=True)
    direccion_comentario = Column(String(500), nullable=True)
    pistoleado_at = Column(DateTime(timezone=True), nullable=True)
    pistoleado_caja = Column(String(50), nullable=True)
    original_created_at = Column(DateTime(timezone=True), nullable=True)
    original_updated_at = Column(DateTime(timezone=True), nullable=True)

    # Auditoría
    deleted_by = Column(Integer, nullable=False)  # user id que borró
    deleted_at = Column(DateTime(timezone=True), server_default=func.now())
    delete_comment = Column(String(500), nullable=True)  # "se cargaron por error", etc.

    __table_args__ = (
        Index("idx_audit_shipping_id", "shipping_id"),
        Index("idx_audit_deleted_at", "deleted_at"),
        Index("idx_audit_deleted_by", "deleted_by"),
    )

    def __repr__(self) -> str:
        return f"<EtiquetaEnvioAudit(shipping_id={self.shipping_id}, deleted_by={self.deleted_by})>"
