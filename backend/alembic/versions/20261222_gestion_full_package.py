"""gestion_full_package + lines + qty_export audit

Revision ID: 20261222_gestion_full_package
Revises: 20261221_gestion_full_pm_ready
Create Date: 2026-10-31

Shared weekly send package (open → exported → locked), lines keyed by
ERP+MLAU with qty_pm/qty_export, and optional-reason audit on qty_export.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261222_gestion_full_package"
down_revision: Union[str, None] = "20261221_gestion_full_pm_ready"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gestion_full_package",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("week_monday", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('open', 'exported', 'locked')",
            name="ck_gestion_full_package_status",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["usuarios.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_gestion_full_package_week_monday",
        "gestion_full_package",
        ["week_monday"],
    )
    op.create_index(
        "ix_gestion_full_package_created_by_id",
        "gestion_full_package",
        ["created_by_id"],
    )
    # At most one non-locked working package (D4b shared listado).
    op.execute(
        """
        CREATE UNIQUE INDEX uq_gestion_full_package_one_active
        ON gestion_full_package ((1))
        WHERE status IN ('open', 'exported')
        """
    )

    op.create_table(
        "gestion_full_package_line",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("package_id", sa.Integer(), nullable=False),
        sa.Column("producto_item_id", sa.Integer(), nullable=False),
        sa.Column("user_product_id", sa.Text(), nullable=False),
        sa.Column("inventory_id", sa.Text(), nullable=False),
        sa.Column("qty_pm", sa.Integer(), nullable=False),
        sa.Column("qty_export", sa.Integer(), nullable=False),
        sa.Column("qty_export_reason", sa.Text(), nullable=True),
        sa.Column("qty_export_updated_by_id", sa.Integer(), nullable=True),
        sa.Column("qty_export_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inbound_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("qty_pm >= 0", name="ck_gestion_full_package_line_qty_pm"),
        sa.CheckConstraint(
            "qty_export >= 0",
            name="ck_gestion_full_package_line_qty_export",
        ),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["gestion_full_package.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["producto_item_id"],
            ["productos_erp.item_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["qty_export_updated_by_id"],
            ["usuarios.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "package_id",
            "producto_item_id",
            "user_product_id",
            name="uq_gestion_full_package_line_key",
        ),
    )
    op.create_index(
        "ix_gestion_full_package_line_package_id",
        "gestion_full_package_line",
        ["package_id"],
    )
    op.create_index(
        "ix_gestion_full_package_line_producto_item_id",
        "gestion_full_package_line",
        ["producto_item_id"],
    )
    op.create_index(
        "ix_gestion_full_package_line_qty_export_updated_by_id",
        "gestion_full_package_line",
        ["qty_export_updated_by_id"],
    )
    op.create_index(
        "ix_gestion_full_package_line_inbound_id",
        "gestion_full_package_line",
        ["inbound_id"],
    )

    op.create_table(
        "gestion_full_qty_export_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("package_line_id", sa.Integer(), nullable=False),
        sa.Column("old_qty", sa.Integer(), nullable=False),
        sa.Column("new_qty", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["package_line_id"],
            ["gestion_full_package_line.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["usuarios.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_gestion_full_qty_export_audit_package_line_id",
        "gestion_full_qty_export_audit",
        ["package_line_id"],
    )
    op.create_index(
        "ix_gestion_full_qty_export_audit_updated_by_id",
        "gestion_full_qty_export_audit",
        ["updated_by_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_gestion_full_qty_export_audit_updated_by_id",
        table_name="gestion_full_qty_export_audit",
    )
    op.drop_index(
        "ix_gestion_full_qty_export_audit_package_line_id",
        table_name="gestion_full_qty_export_audit",
    )
    op.drop_table("gestion_full_qty_export_audit")

    op.drop_index(
        "ix_gestion_full_package_line_inbound_id",
        table_name="gestion_full_package_line",
    )
    op.drop_index(
        "ix_gestion_full_package_line_qty_export_updated_by_id",
        table_name="gestion_full_package_line",
    )
    op.drop_index(
        "ix_gestion_full_package_line_producto_item_id",
        table_name="gestion_full_package_line",
    )
    op.drop_index(
        "ix_gestion_full_package_line_package_id",
        table_name="gestion_full_package_line",
    )
    op.drop_table("gestion_full_package_line")

    op.execute("DROP INDEX IF EXISTS uq_gestion_full_package_one_active")
    op.drop_index(
        "ix_gestion_full_package_created_by_id",
        table_name="gestion_full_package",
    )
    op.drop_index(
        "ix_gestion_full_package_week_monday",
        table_name="gestion_full_package",
    )
    op.drop_table("gestion_full_package")
