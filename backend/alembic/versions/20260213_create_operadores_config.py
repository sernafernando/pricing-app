"""Crear tablas operadores, operador_config_tab, operador_actividad, logistica_costo_cordon

Sistema de micro-usuarios (operadores con PIN 4 dígitos) para trazabilidad
en depósito, config de tabs que requieren PIN, log de actividad, y costos
de envío por logística × cordón.

Revision ID: 20260213_operadores
Revises: 20260213_etiq_audit
Create Date: 2026-02-13

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260213_operadores"
down_revision = "20260213_etiq_audit"
branch_labels = None
depends_on = None


def upgrade():
    # Operadores
    op.create_table(
        "operadores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("pin", sa.String(4), unique=True, nullable=False),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("activo", sa.Boolean(), default=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_operadores_pin", "operadores", ["pin"], unique=True)

    # Config de tabs que requieren operador
    op.create_table(
        "operador_config_tab",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tab_key", sa.String(50), nullable=False),
        sa.Column("page_path", sa.String(100), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("timeout_minutos", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("activo", sa.Boolean(), default=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "idx_config_tab_key_page", "operador_config_tab",
        ["tab_key", "page_path"], unique=True,
    )

    # Log de actividad de operadores
    op.create_table(
        "operador_actividad",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("operador_id", sa.Integer(), sa.ForeignKey("operadores.id"), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("tab_key", sa.String(50), nullable=False),
        sa.Column("accion", sa.String(100), nullable=False),
        sa.Column("detalle", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_actividad_operador", "operador_actividad", ["operador_id"])
    op.create_index("idx_actividad_created", "operador_actividad", ["created_at"])
    op.create_index("idx_actividad_accion", "operador_actividad", ["accion"])
    op.create_index("idx_actividad_tab", "operador_actividad", ["tab_key"])

    # Costos de envío por logística × cordón
    op.create_table(
        "logistica_costo_cordon",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("logistica_id", sa.Integer(), sa.ForeignKey("logisticas.id"), nullable=False),
        sa.Column("cordon", sa.String(20), nullable=False),
        sa.Column("costo", sa.Numeric(12, 2), nullable=False),
        sa.Column("vigente_desde", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_costo_logistica_cordon", "logistica_costo_cordon", ["logistica_id", "cordon"])
    op.create_index("idx_costo_vigente", "logistica_costo_cordon", ["vigente_desde"])


def downgrade():
    op.drop_table("logistica_costo_cordon")
    op.drop_table("operador_actividad")
    op.drop_table("operador_config_tab")
    op.drop_table("operadores")
