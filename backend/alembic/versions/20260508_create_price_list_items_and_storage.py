"""Create tb_price_list_items and tb_item_storage

Revision ID: 20260508_pli_storage
Revises: 20260507_batch_id
Create Date: 2026-05-08

Tablas espejo del ERP necesarias para reescribir el sync de productos
como query 100% local en PostgreSQL.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260508_pli_storage"
down_revision = "20260507_batch_id"
branch_labels = None
depends_on = None


def upgrade():
    # tb_price_list_items
    op.create_table(
        "tb_price_list_items",
        sa.Column("comp_id", sa.Integer(), nullable=False),
        sa.Column("prli_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("prli_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("curr_id", sa.Integer(), nullable=True),
        sa.Column("bra_id", sa.Integer(), nullable=True),
        sa.Column("prli_price_PreLastUpdate", sa.Numeric(18, 4), nullable=True),
        sa.Column("curr_id_PreLastUpdate", sa.Integer(), nullable=True),
        sa.Column("prli_cd", sa.DateTime(), nullable=True),
        sa.Column("prli_updatedAt", sa.DateTime(), nullable=True),
        sa.Column("prli_triggerUpdateCD", sa.DateTime(), nullable=True),
        sa.Column("prli_lastModuleUpdate", sa.Integer(), nullable=True),
        sa.Column("prli_lastRuleUpdate", sa.DateTime(), nullable=True),
        sa.Column("user_id_lastUpdate", sa.Integer(), nullable=True),
        sa.Column("prli_disabled4Rules", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("comp_id", "prli_id", "item_id"),
    )
    op.create_index("ix_tb_price_list_items_prli_id", "tb_price_list_items", ["prli_id"], unique=False)
    op.create_index("ix_tb_price_list_items_item_id", "tb_price_list_items", ["item_id"], unique=False)
    op.create_index("ix_tb_price_list_items_prli_cd", "tb_price_list_items", ["prli_cd"], unique=False)
    op.create_index("ix_tb_price_list_items_prli_updatedAt", "tb_price_list_items", ["prli_updatedAt"], unique=False)

    # tb_item_storage
    op.create_table(
        "tb_item_storage",
        sa.Column("comp_id", sa.Integer(), nullable=False),
        sa.Column("stor_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("itst_cant", sa.Numeric(18, 4), nullable=True),
        sa.Column("itst_PickingLocation", sa.String(100), nullable=True),
        sa.Column("itst_StorageLocation", sa.String(100), nullable=True),
        sa.Column("itst_cd", sa.DateTime(), nullable=True),
        sa.Column("itst_updateByInTransitStock", sa.DateTime(), nullable=True),
        sa.Column("itst_LastAvailableInRelalculation", sa.DateTime(), nullable=True),
        sa.Column("itst_LastQTYAtQuery", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("comp_id", "stor_id", "item_id"),
    )
    op.create_index("ix_tb_item_storage_stor_id", "tb_item_storage", ["stor_id"], unique=False)
    op.create_index("ix_tb_item_storage_item_id", "tb_item_storage", ["item_id"], unique=False)
    op.create_index(
        "ix_tb_item_storage_LastAvailableInRelalculation",
        "tb_item_storage",
        ["itst_LastAvailableInRelalculation"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_tb_item_storage_LastAvailableInRelalculation", table_name="tb_item_storage")
    op.drop_index("ix_tb_item_storage_item_id", table_name="tb_item_storage")
    op.drop_index("ix_tb_item_storage_stor_id", table_name="tb_item_storage")
    op.drop_table("tb_item_storage")

    op.drop_index("ix_tb_price_list_items_prli_updatedAt", table_name="tb_price_list_items")
    op.drop_index("ix_tb_price_list_items_prli_cd", table_name="tb_price_list_items")
    op.drop_index("ix_tb_price_list_items_item_id", table_name="tb_price_list_items")
    op.drop_index("ix_tb_price_list_items_prli_id", table_name="tb_price_list_items")
    op.drop_table("tb_price_list_items")
