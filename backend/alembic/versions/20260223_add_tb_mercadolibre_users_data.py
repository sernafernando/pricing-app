"""add tb_mercadolibre_users_data table

Revision ID: 20260223_ml_users_data
Revises: 20260220_costo_turbo
Create Date: 2026-02-23
"""

from alembic import op
import sqlalchemy as sa

revision = "20260223_ml_users_data"
down_revision = "20260220_costo_turbo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tb_mercadolibre_users_data",
        sa.Column("mluser_id", sa.BigInteger(), nullable=False),
        sa.Column("nickname", sa.String(255), nullable=True),
        sa.Column("identification_type", sa.String(255), nullable=True),
        sa.Column("identification_number", sa.String(255), nullable=True),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("citi", sa.String(255), nullable=True),
        sa.Column("zip_code", sa.String(50), nullable=True),
        sa.Column("state", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(255), nullable=True),
        sa.Column("alternative_phone", sa.String(255), nullable=True),
        sa.Column("secure_email", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("receiver_name", sa.String(255), nullable=True),
        sa.Column("receiver_phone", sa.String(255), nullable=True),
        sa.Column("mlu_cd", sa.String(255), nullable=True),
        sa.Column("billing_state_name", sa.String(255), nullable=True),
        sa.Column("billing_doc_number", sa.String(255), nullable=True),
        sa.Column("billing_street_name", sa.String(500), nullable=True),
        sa.Column("billing_city_name", sa.String(255), nullable=True),
        sa.Column("billing_zip_code", sa.String(50), nullable=True),
        sa.Column("billing_street_number", sa.String(255), nullable=True),
        sa.Column("billing_doc_type", sa.String(255), nullable=True),
        sa.Column("billing_first_name", sa.String(255), nullable=True),
        sa.Column("billing_last_name", sa.String(255), nullable=True),
        sa.Column("billing_site_id", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("mluser_id"),
    )
    op.create_index(
        op.f("ix_tb_mercadolibre_users_data_mluser_id"),
        "tb_mercadolibre_users_data",
        ["mluser_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tb_mercadolibre_users_data_nickname"),
        "tb_mercadolibre_users_data",
        ["nickname"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tb_mercadolibre_users_data_nickname"),
        table_name="tb_mercadolibre_users_data",
    )
    op.drop_index(
        op.f("ix_tb_mercadolibre_users_data_mluser_id"),
        table_name="tb_mercadolibre_users_data",
    )
    op.drop_table("tb_mercadolibre_users_data")
