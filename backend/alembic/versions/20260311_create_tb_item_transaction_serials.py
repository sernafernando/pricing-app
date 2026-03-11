"""Create tb_item_transaction_serials table

Bridge table between tb_item_serials (is_id) and sale transactions
(it_transaction / ct_transaction). GBP uses this table to show all
movements (purchase + sale) for a serial number in the Traza view.

Revision ID: 20260311_item_trx_serials
Revises: 20260310_return_denorm
Create Date: 2026-03-11

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "20260311_item_trx_serials"
down_revision = "20260310_return_denorm"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tb_item_transaction_serials",
        sa.Column("comp_id", sa.Integer(), nullable=False),
        sa.Column("bra_id", sa.Integer(), nullable=False),
        sa.Column("its_id", sa.BigInteger(), nullable=False),
        sa.Column("it_transaction", sa.BigInteger(), nullable=True),
        sa.Column("is_id", sa.BigInteger(), nullable=True),
        sa.Column("ct_transaction", sa.BigInteger(), nullable=True),
        sa.Column("impdata_id", sa.BigInteger(), nullable=True),
        sa.Column("import_id", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("comp_id", "bra_id", "its_id"),
    )
    op.create_index("ix_tits_it_transaction", "tb_item_transaction_serials", ["it_transaction"])
    op.create_index("ix_tits_is_id", "tb_item_transaction_serials", ["is_id"])
    op.create_index("ix_tits_ct_transaction", "tb_item_transaction_serials", ["ct_transaction"])
    op.create_index(
        "idx_its_is_id_it_transaction",
        "tb_item_transaction_serials",
        ["is_id", "it_transaction"],
    )


def downgrade():
    op.drop_index("idx_its_is_id_it_transaction", table_name="tb_item_transaction_serials")
    op.drop_index("ix_tits_ct_transaction", table_name="tb_item_transaction_serials")
    op.drop_index("ix_tits_is_id", table_name="tb_item_transaction_serials")
    op.drop_index("ix_tits_it_transaction", table_name="tb_item_transaction_serials")
    op.drop_table("tb_item_transaction_serials")
