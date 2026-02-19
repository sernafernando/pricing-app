"""Agregar campos para envíos manuales (sin MercadoLibre)

Permite crear etiquetas de envío fuera de ML con datos de dirección,
receptor, estado y cliente del ERP directamente en etiquetas_envio.

Revision ID: 20260219_manual_envio
Revises: 20260219_idx_soh_mlship
Create Date: 2026-02-19

"""

from alembic import op
import sqlalchemy as sa

revision = "20260219_manual_envio"
down_revision = "20260219_idx_soh_mlship"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "etiquetas_envio",
        sa.Column("es_manual", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column("manual_receiver_name", sa.String(500), nullable=True),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column("manual_street_name", sa.String(500), nullable=True),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column("manual_street_number", sa.String(50), nullable=True),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column("manual_zip_code", sa.String(50), nullable=True),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column("manual_city_name", sa.String(500), nullable=True),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column("manual_status", sa.String(50), nullable=True),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column("manual_cust_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column("manual_bra_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column("manual_soh_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "etiquetas_envio",
        sa.Column("manual_comment", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_etiquetas_envio_es_manual",
        "etiquetas_envio",
        ["es_manual"],
    )


def downgrade():
    op.drop_index("idx_etiquetas_envio_es_manual", table_name="etiquetas_envio")
    op.drop_column("etiquetas_envio", "manual_comment")
    op.drop_column("etiquetas_envio", "manual_soh_id")
    op.drop_column("etiquetas_envio", "manual_bra_id")
    op.drop_column("etiquetas_envio", "manual_cust_id")
    op.drop_column("etiquetas_envio", "manual_status")
    op.drop_column("etiquetas_envio", "manual_city_name")
    op.drop_column("etiquetas_envio", "manual_zip_code")
    op.drop_column("etiquetas_envio", "manual_street_number")
    op.drop_column("etiquetas_envio", "manual_street_name")
    op.drop_column("etiquetas_envio", "manual_receiver_name")
    op.drop_column("etiquetas_envio", "es_manual")
