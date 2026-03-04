"""Tablas rma_claims_ml y rma_claims_ml_messages — cache local de claims ML

Cache de reclamos, devoluciones, cambios y mensajes de MercadoLibre.
Evita llamadas HTTP repetidas a la API de ML y permite análisis histórico.

Revision ID: 20260304_rma_claims_ml
Revises: 20260303_turbo_lluvia_perm
Create Date: 2026-03-04

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260304_rma_claims_ml"
down_revision = "20260303_turbo_lluvia_perm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- rma_claims_ml: cache de claims de MercadoLibre --
    op.create_table(
        "rma_claims_ml",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # Identificadores
        sa.Column("claim_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("resource_id", sa.BigInteger(), nullable=True),
        # Estado
        sa.Column("claim_type", sa.String(50), nullable=True),
        sa.Column("claim_stage", sa.String(50), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        # Motivo
        sa.Column("reason_id", sa.String(50), nullable=True),
        sa.Column("reason_category", sa.String(10), nullable=True),
        sa.Column("reason_detail", sa.Text(), nullable=True),
        sa.Column("reason_name", sa.String(255), nullable=True),
        # Clasificación
        sa.Column("triage_tags", postgresql.JSONB(), nullable=True),
        sa.Column("expected_resolutions", postgresql.JSONB(), nullable=True),
        # Detail legible
        sa.Column("detail_title", sa.Text(), nullable=True),
        sa.Column("detail_description", sa.Text(), nullable=True),
        sa.Column("detail_problem", sa.Text(), nullable=True),
        # Entrega
        sa.Column("fulfilled", sa.Boolean(), nullable=True),
        sa.Column("quantity_type", sa.String(20), nullable=True),
        sa.Column("claimed_quantity", sa.Integer(), nullable=True),
        # Acciones
        sa.Column("seller_actions", postgresql.JSONB(), nullable=True),
        sa.Column("mandatory_actions", postgresql.JSONB(), nullable=True),
        sa.Column("nearest_due_date", sa.String(50), nullable=True),
        sa.Column("action_responsible", sa.String(20), nullable=True),
        # Resolución
        sa.Column("resolution_reason", sa.String(100), nullable=True),
        sa.Column("resolution_closed_by", sa.String(20), nullable=True),
        sa.Column("resolution_coverage", sa.Boolean(), nullable=True),
        # Entidades relacionadas
        sa.Column("related_entities", postgresql.JSONB(), nullable=True),
        # Expected resolutions detalladas
        sa.Column("expected_resolutions_detail", postgresql.JSONB(), nullable=True),
        # Devolución y cambio (JSONB completo)
        sa.Column("return_data", postgresql.JSONB(), nullable=True),
        sa.Column("change_data", postgresql.JSONB(), nullable=True),
        # Mensajes y reputación
        sa.Column("messages_total", sa.Integer(), nullable=True),
        sa.Column("affects_reputation", sa.Boolean(), nullable=True),
        sa.Column("has_incentive", sa.Boolean(), nullable=True),
        # Fechas ML
        sa.Column("ml_date_created", sa.String(50), nullable=True),
        sa.Column("ml_last_updated", sa.String(50), nullable=True),
        # Data cruda (backup)
        sa.Column("raw_claim", postgresql.JSONB(), nullable=True),
        sa.Column("raw_detail", postgresql.JSONB(), nullable=True),
        sa.Column("raw_reason", postgresql.JSONB(), nullable=True),
        # Sistema
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    op.create_index("ix_rma_claims_ml_id", "rma_claims_ml", ["id"])
    op.create_index("ix_rma_claims_ml_claim_id", "rma_claims_ml", ["claim_id"], unique=True)
    op.create_index("idx_rma_claims_ml_resource_id", "rma_claims_ml", ["resource_id"])
    op.create_index("idx_rma_claims_ml_status", "rma_claims_ml", ["status"])
    op.create_index("idx_rma_claims_ml_reason_category", "rma_claims_ml", ["reason_category"])

    # -- rma_claims_ml_messages: mensajes de claims --
    op.create_table(
        "rma_claims_ml_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # FK al claim (claim_id de ML, no FK real)
        sa.Column("claim_id", sa.BigInteger(), nullable=False),
        # Datos del mensaje
        sa.Column("sender_role", sa.String(30), nullable=True),
        sa.Column("receiver_role", sa.String(30), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=True),
        sa.Column("stage", sa.String(30), nullable=True),
        # Adjuntos y moderación
        sa.Column("attachments", postgresql.JSONB(), nullable=True),
        sa.Column("message_moderation", postgresql.JSONB(), nullable=True),
        # Lectura
        sa.Column("date_read", sa.String(50), nullable=True),
        # Fechas ML
        sa.Column("ml_date_created", sa.String(50), nullable=True),
        # Sistema
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_index("ix_rma_claims_ml_messages_id", "rma_claims_ml_messages", ["id"])
    op.create_index("idx_rma_claims_ml_msg_claim_id", "rma_claims_ml_messages", ["claim_id"])
    op.create_index("idx_rma_claims_ml_msg_sender", "rma_claims_ml_messages", ["sender_role"])


def downgrade() -> None:
    op.drop_table("rma_claims_ml_messages")
    op.drop_table("rma_claims_ml")
