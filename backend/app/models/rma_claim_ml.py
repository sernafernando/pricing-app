"""
Claims de MercadoLibre — cache local de datos de la API de ML.

Almacena claims (reclamos, devoluciones, cambios) consultados vía la API
de ML para evitar llamadas HTTP repetidas. Se enriquece con data de 3+
endpoints: /claims/{id}, /claims/{id}/detail, /claims/reasons/{reason_id},
/claims/{id}/expected-resolutions, /v2/claims/{id}/returns, etc.

Relación: un rma_caso puede tener N claims (vía ml_id / order_id).
"""

from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Boolean,
    DateTime,
    Text,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.core.database import Base


class RmaClaimML(Base):
    """
    Cache local de un claim de MercadoLibre.
    Fuente de verdad: API de ML. Esta tabla es una copia local para consulta
    rápida sin depender de la disponibilidad de la API.
    """

    __tablename__ = "rma_claims_ml"

    id = Column(Integer, primary_key=True, index=True)

    # --- Identificadores ---
    claim_id = Column(BigInteger, unique=True, nullable=False, index=True)
    resource_id = Column(BigInteger, nullable=True, index=True)  # order_id de ML

    # --- Estado ---
    claim_type = Column(String(50), nullable=True)  # mediations, return, fulfillment
    claim_stage = Column(String(50), nullable=True)  # claim, dispute, recontact, stale
    status = Column(String(50), nullable=True)  # opened, closed

    # --- Motivo ---
    reason_id = Column(String(50), nullable=True)  # PDD9549, PNR3430, etc.
    reason_category = Column(String(10), nullable=True)  # PDD, PNR, CS
    reason_detail = Column(Text, nullable=True)  # Texto legible del motivo
    reason_name = Column(String(255), nullable=True)  # Nombre de la reason

    # --- Clasificación (de /reasons/{id}) ---
    triage_tags = Column(JSONB, nullable=True)  # ["defective", "repentant"]
    expected_resolutions = Column(JSONB, nullable=True)  # ["return_product", "refund"]

    # --- Detail legible (de /claims/{id}/detail) ---
    detail_title = Column(Text, nullable=True)  # "Devolución en preparación..."
    detail_description = Column(Text, nullable=True)  # Texto largo explicativo
    detail_problem = Column(Text, nullable=True)  # Problema reportado

    # --- Estado de entrega ---
    fulfilled = Column(Boolean, nullable=True)
    quantity_type = Column(String(20), nullable=True)  # total, partial
    claimed_quantity = Column(Integer, nullable=True)

    # --- Acciones (del array players.respondent.available_actions) ---
    seller_actions = Column(JSONB, nullable=True)  # ["refund", "allow_return", ...]
    mandatory_actions = Column(JSONB, nullable=True)  # acciones con mandatory=true
    nearest_due_date = Column(String(50), nullable=True)  # ISO date de la acción más urgente
    action_responsible = Column(String(20), nullable=True)  # seller, buyer, mediator

    # --- Resolución ---
    resolution_reason = Column(String(100), nullable=True)  # payment_refunded, item_returned...
    resolution_closed_by = Column(String(20), nullable=True)  # seller, buyer, mediator
    resolution_coverage = Column(Boolean, nullable=True)

    # --- Entidades relacionadas ---
    related_entities = Column(JSONB, nullable=True)  # ["return", "change", "reviews"]

    # --- Expected resolutions detalladas (de /expected-resolutions) ---
    expected_resolutions_detail = Column(JSONB, nullable=True)  # array completo

    # --- Devolución (de /v2/claims/{id}/returns) ---
    return_data = Column(JSONB, nullable=True)  # objeto completo de la devolución

    # --- Campos desnormalizados de return_data (para filtrar sin parsear JSONB) ---
    return_status = Column(
        String(50), nullable=True
    )  # pending, label_generated, shipped, delivered, expired, cancelled
    return_shipment_status = Column(String(50), nullable=True)  # pending, ready_to_ship, shipped, delivered, cancelled
    return_destination = Column(String(50), nullable=True)  # seller_address, warehouse
    return_tracking = Column(String(100), nullable=True)  # tracking number del correo
    return_shipment_type = Column(String(50), nullable=True)  # return, return_from_triage

    # --- Cambio (de /v1/claims/{id}/changes) ---
    change_data = Column(JSONB, nullable=True)  # objeto completo del cambio

    # --- Mensajes ---
    messages_total = Column(Integer, nullable=True)

    # --- Reputación ---
    affects_reputation = Column(Boolean, nullable=True)
    has_incentive = Column(Boolean, nullable=True)  # 48hs para resolver

    # --- Fechas de ML ---
    ml_date_created = Column(String(50), nullable=True)
    ml_last_updated = Column(String(50), nullable=True)

    # --- Data cruda completa (backup) ---
    raw_claim = Column(JSONB, nullable=True)  # /claims/{id} completo
    raw_detail = Column(JSONB, nullable=True)  # /claims/{id}/detail completo
    raw_reason = Column(JSONB, nullable=True)  # /claims/reasons/{reason_id}

    # --- Sistema ---
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_rma_claims_ml_resource_id", "resource_id"),
        Index("idx_rma_claims_ml_status", "status"),
        Index("idx_rma_claims_ml_reason_category", "reason_category"),
        Index("idx_rma_claims_ml_return_destination", "return_destination"),
        Index("idx_rma_claims_ml_return_status", "return_status"),
    )

    def __repr__(self) -> str:
        return f"<RmaClaimML(id={self.id}, claim_id={self.claim_id}, status='{self.status}')>"
