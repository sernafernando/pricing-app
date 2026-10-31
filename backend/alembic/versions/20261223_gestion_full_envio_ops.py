"""gestion_full_envio + inbound reception ops

Revision ID: 20261223_gestion_full_envio_ops
Revises: 20261222_gestion_full_package
Create Date: 2026-10-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261223_gestion_full_envio_ops"
down_revision: Union[str, None] = "20261222_gestion_full_package"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gestion_full_envio",
        sa.Column("inbound_id", sa.Text(), nullable=False),
        sa.Column("package_id", sa.Integer(), nullable=False),
        sa.Column("week_monday", sa.Date(), nullable=False),
        sa.Column("reception_closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reception_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["gestion_full_package.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("inbound_id"),
    )
    op.create_index("ix_gestion_full_envio_package_id", "gestion_full_envio", ["package_id"])

    op.create_table(
        "gestion_full_inbound_reception_op",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("operation_id", sa.BigInteger(), nullable=False),
        sa.Column("inbound_id", sa.Text(), nullable=False),
        sa.Column("inventory_id", sa.Text(), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["inbound_id"],
            ["gestion_full_envio.inbound_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id", name="uq_gestion_full_inbound_reception_op_id"),
    )
    op.create_index(
        "ix_gestion_full_inbound_reception_op_inbound_id",
        "gestion_full_inbound_reception_op",
        ["inbound_id"],
    )
    op.create_index(
        "ix_gestion_full_inbound_reception_op_inventory_id",
        "gestion_full_inbound_reception_op",
        ["inventory_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_gestion_full_inbound_reception_op_inventory_id",
        table_name="gestion_full_inbound_reception_op",
    )
    op.drop_index(
        "ix_gestion_full_inbound_reception_op_inbound_id",
        table_name="gestion_full_inbound_reception_op",
    )
    op.drop_table("gestion_full_inbound_reception_op")
    op.drop_index("ix_gestion_full_envio_package_id", table_name="gestion_full_envio")
    op.drop_table("gestion_full_envio")
