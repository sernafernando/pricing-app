"""compras 002 — tb_sale_document (estructura, seed separado)

Revision ID: compras_002_sd
Revises: compras_001_num
Create Date: 2026-04-17

Catálogo de tipos de documento del ERP. Seed estático se inserta en
migración posterior (Batch 1B — COMPRAS-1.2b). NO incluye `synced_at`:
la tabla NO se sincroniza (refinement 2026-04-17, Engram obs #121).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "compras_002_sd"
down_revision: Union[str, None] = "compras_001_num"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tb_sale_document",
        sa.Column("sd_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("sd_desc", sa.String(length=200), nullable=False),
        sa.Column(
            "sd_iscredit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "sd_isquotation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "sd_isreceipt",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "sd_istaxable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "sd_isinbalance",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "sd_issales",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "sd_ispurchase",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "sd_isbanking",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "sd_ispackinglist",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "sd_iscreditnote",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "sd_isdebitnote",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "sd_isannulment",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("sd_plusorminus", sa.SmallInteger(), nullable=False),
        sa.Column("hacc_group", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("sd_id", name="pk_tb_sale_document"),
        sa.CheckConstraint("sd_plusorminus IN (1, -1)", name="ck_tb_sale_document_plusorminus"),
    )
    op.create_index(
        "ix_tb_sale_document_ispurchase",
        "tb_sale_document",
        ["sd_ispurchase"],
        postgresql_where=sa.text("sd_ispurchase = true"),
    )
    op.create_index(
        "ix_tb_sale_document_isannul",
        "tb_sale_document",
        ["sd_isannulment"],
        postgresql_where=sa.text("sd_isannulment = true"),
    )
    op.create_index(
        "ix_tb_sale_document_hacc",
        "tb_sale_document",
        ["hacc_group"],
        postgresql_where=sa.text("hacc_group IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_tb_sale_document_hacc", table_name="tb_sale_document")
    op.drop_index("ix_tb_sale_document_isannul", table_name="tb_sale_document")
    op.drop_index("ix_tb_sale_document_ispurchase", table_name="tb_sale_document")
    op.drop_table("tb_sale_document")
