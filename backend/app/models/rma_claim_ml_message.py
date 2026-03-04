"""
Mensajes de claims de MercadoLibre — cache local.

Almacena los mensajes de la conversación de un reclamo ML (comprador, vendedor,
mediador). Se consultan vía /claims/{id}/messages y se guardan localmente
para análisis y para no depender de la API en cada consulta.
"""

from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class RmaClaimMLMessage(Base):
    """
    Un mensaje dentro de la conversación de un claim de ML.
    """

    __tablename__ = "rma_claims_ml_messages"

    id = Column(Integer, primary_key=True, index=True)

    # --- FK al claim local ---
    claim_id = Column(
        BigInteger,
        nullable=False,
        index=True,
    )  # claim_id de ML (no FK a rma_claims_ml.id, es el ID de ML)

    # --- Datos del mensaje ---
    sender_role = Column(String(30), nullable=True)  # complainant, respondent, mediator
    receiver_role = Column(String(30), nullable=True)  # complainant, respondent, mediator
    message = Column(Text, nullable=True)  # Contenido del mensaje
    status = Column(String(30), nullable=True)  # available, moderated, rejected
    stage = Column(String(30), nullable=True)  # claim, dispute

    # --- Adjuntos ---
    attachments = Column(JSONB, nullable=True)  # [{filename, original_filename, type}]

    # --- Moderación ---
    message_moderation = Column(JSONB, nullable=True)  # datos de moderación si fue moderado

    # --- Lectura ---
    date_read = Column(String(50), nullable=True)

    # --- Fechas de ML ---
    ml_date_created = Column(String(50), nullable=True)

    # --- Sistema ---
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_rma_claims_ml_msg_claim_id", "claim_id"),
        Index("idx_rma_claims_ml_msg_sender", "sender_role"),
    )

    def __repr__(self) -> str:
        return f"<RmaClaimMLMessage(id={self.id}, claim_id={self.claim_id}, sender='{self.sender_role}')>"
