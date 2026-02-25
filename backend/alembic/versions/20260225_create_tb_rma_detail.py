"""create tb_rma_detail table

Revision ID: 20260225_rma_detail
Revises: 20260225_storage
Create Date: 2026-02-25

"""

from alembic import op
import sqlalchemy as sa

revision = "20260225_rma_detail"
down_revision = "20260225_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tb_rma_detail",
        # PK
        sa.Column("comp_id", sa.Integer(), nullable=False),
        sa.Column("rmad_id", sa.BigInteger(), nullable=False),
        sa.Column("bra_id", sa.Integer(), nullable=False),
        # Foreign keys
        sa.Column("rmah_id", sa.BigInteger(), nullable=True),
        sa.Column("item_id", sa.BigInteger(), nullable=True),
        sa.Column("it_transaction", sa.BigInteger(), nullable=True),
        sa.Column("stor_id", sa.Integer(), nullable=True),
        sa.Column("curr_id", sa.Integer(), nullable=True),
        sa.Column("is_id", sa.BigInteger(), nullable=True),
        sa.Column("supp_id", sa.BigInteger(), nullable=True),
        sa.Column("rmas_id", sa.Integer(), nullable=True),
        sa.Column("rmap_id", sa.Integer(), nullable=True),
        sa.Column("rmafp_id", sa.Integer(), nullable=True),
        sa.Column("rmamt_id", sa.Integer(), nullable=True),
        sa.Column("rmaw_id", sa.Integer(), nullable=True),
        sa.Column("rmafailP_id", sa.Integer(), nullable=True),
        sa.Column("srpt_id", sa.Integer(), nullable=True),
        sa.Column("case_id", sa.BigInteger(), nullable=True),
        sa.Column("rmafp_tax_id", sa.Integer(), nullable=True),
        # Item replacement
        sa.Column("item_id4Replacement", sa.BigInteger(), nullable=True),
        sa.Column("stor_id4Replacement", sa.Integer(), nullable=True),
        # Credit note
        sa.Column("it_transaction_CN", sa.BigInteger(), nullable=True),
        sa.Column("df_id4CreditNote", sa.BigInteger(), nullable=True),
        sa.Column("it_transaction_Origin", sa.BigInteger(), nullable=True),
        # Manual / serial
        sa.Column("rmad_Manual", sa.String(255), nullable=True),
        sa.Column("rmad_serial", sa.String(255), nullable=True),
        # Precios
        sa.Column("rmad_originalPrice", sa.Numeric(18, 6), nullable=True),
        sa.Column("rmad_qty", sa.Numeric(18, 5), nullable=True),
        sa.Column("rmafp_Price", sa.Numeric(18, 6), nullable=True),
        sa.Column("rmafp_curr_id", sa.Integer(), nullable=True),
        sa.Column("rmad_up2Price", sa.Numeric(18, 6), nullable=True),
        # Reception
        sa.Column("user_id_Reception", sa.BigInteger(), nullable=True),
        sa.Column("rmad_Date_Reception", sa.DateTime(), nullable=True),
        sa.Column("rmad_ReceptionNote", sa.String(2000), nullable=True),
        # Diagnostic
        sa.Column("user_id_Diagnostic", sa.BigInteger(), nullable=True),
        sa.Column("rmad_Date_Diagnostic", sa.DateTime(), nullable=True),
        sa.Column("rmad_DiagnosticNote", sa.String(2000), nullable=True),
        # Processing
        sa.Column("user_id_Proc", sa.BigInteger(), nullable=True),
        sa.Column("rmad_Date_Proc", sa.DateTime(), nullable=True),
        sa.Column("rmad_ProcNote", sa.String(2000), nullable=True),
        # Delivery
        sa.Column("user_id_Delivery", sa.BigInteger(), nullable=True),
        sa.Column("rmad_Date_Delivery", sa.DateTime(), nullable=True),
        sa.Column("rmad_DelioveryNote", sa.String(2000), nullable=True),
        # Flags
        sa.Column("rmad_isNewItem", sa.Boolean(), nullable=True),
        sa.Column("rmad_IncludeInPotentialStock", sa.Boolean(), nullable=True),
        sa.Column("rmad_isAvailable4DeliverySheet", sa.Boolean(), nullable=True),
        # Import data
        sa.Column("impData_Custom_local", sa.String(255), nullable=True),
        sa.Column("impData_Number_local", sa.String(255), nullable=True),
        # Related
        sa.Column("rmad_relatedID", sa.BigInteger(), nullable=True),
        sa.Column("bra_id_original", sa.Integer(), nullable=True),
        # Warranty
        sa.Column("rmad_insertWarrantyDetail", sa.String(4000), nullable=True),
        sa.Column("rmad_insertWarrantyCertificates", sa.String(4000), nullable=True),
        # Delivery sheet / picking
        sa.Column("sds_id4Picking", sa.BigInteger(), nullable=True),
        sa.Column("dsd_id4Picking", sa.BigInteger(), nullable=True),
        sa.Column("sds_id4Delivery", sa.BigInteger(), nullable=True),
        sa.Column("dsd_id4Delivery", sa.BigInteger(), nullable=True),
        sa.Column("dl_id4Picking", sa.BigInteger(), nullable=True),
        sa.Column("dl_id4delivery", sa.BigInteger(), nullable=True),
        # Dates
        sa.Column("rmad_deliveryDate4Picking", sa.DateTime(), nullable=True),
        sa.Column("rmad_deliveryDate4Delivery", sa.DateTime(), nullable=True),
        sa.Column("rmad_Date_estimatedFinalization", sa.DateTime(), nullable=True),
        sa.Column("rmad_handOverDate", sa.DateTime(), nullable=True),
        sa.Column("rmad_handOver_user_id", sa.BigInteger(), nullable=True),
        # GUID
        sa.Column("rmad_guid", sa.String(100), nullable=True),
        # PK
        sa.PrimaryKeyConstraint("comp_id", "rmad_id", "bra_id"),
    )
    # Indexes
    op.create_index("idx_rmad_rmah_id", "tb_rma_detail", ["rmah_id"])
    op.create_index("idx_rmad_item_id", "tb_rma_detail", ["item_id"])
    op.create_index("idx_rmad_is_id", "tb_rma_detail", ["is_id"])
    op.create_index("idx_rmad_it_transaction", "tb_rma_detail", ["it_transaction"])
    op.create_index("idx_rmad_rmas_id", "tb_rma_detail", ["rmas_id"])
    op.create_index("idx_rmad_supp_id", "tb_rma_detail", ["supp_id"])
    op.create_index("idx_rmad_date_reception", "tb_rma_detail", ["rmad_Date_Reception"])
    op.create_index("idx_rmad_serial", "tb_rma_detail", ["rmad_serial"])


def downgrade() -> None:
    op.drop_index("idx_rmad_serial", table_name="tb_rma_detail")
    op.drop_index("idx_rmad_date_reception", table_name="tb_rma_detail")
    op.drop_index("idx_rmad_supp_id", table_name="tb_rma_detail")
    op.drop_index("idx_rmad_rmas_id", table_name="tb_rma_detail")
    op.drop_index("idx_rmad_it_transaction", table_name="tb_rma_detail")
    op.drop_index("idx_rmad_is_id", table_name="tb_rma_detail")
    op.drop_index("idx_rmad_item_id", table_name="tb_rma_detail")
    op.drop_index("idx_rmad_rmah_id", table_name="tb_rma_detail")
    op.drop_table("tb_rma_detail")
