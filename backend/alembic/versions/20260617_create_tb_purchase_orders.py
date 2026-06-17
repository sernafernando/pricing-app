"""create tb_purchase_order_header and tb_purchase_order_detail tables

Revision ID: 20260617_purchase_orders
Revises: 20260605_ml_cancel_metricas
Create Date: 2026-06-17

"""

from alembic import op
import sqlalchemy as sa

revision = "20260617_purchase_orders"
down_revision = "20260605_ml_cancel_metricas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tabla cabecera de órdenes de compra
    op.create_table(
        "tb_purchase_order_header",
        sa.Column("comp_id", sa.Integer(), nullable=False),
        sa.Column("bra_id", sa.Integer(), nullable=False),
        sa.Column("poh_id", sa.BigInteger(), nullable=False),
        sa.Column("poh_cd", sa.DateTime(), nullable=True),
        sa.Column("poh_estdeliverydate", sa.DateTime(), nullable=True),
        sa.Column("poh_deliverydate", sa.DateTime(), nullable=True),
        sa.Column("poh_observation1", sa.Text(), nullable=True),
        sa.Column("poh_observation2", sa.Text(), nullable=True),
        sa.Column("poh_observation3", sa.Text(), nullable=True),
        sa.Column("poh_observation4", sa.Text(), nullable=True),
        sa.Column("supp_id", sa.Integer(), nullable=True),
        sa.Column("poh_quotation", sa.String(100), nullable=True),
        sa.Column("pt_id", sa.Integer(), nullable=True),
        sa.Column("poh_isediting", sa.Boolean(), nullable=True),
        sa.Column("poh_iseditingcd", sa.DateTime(), nullable=True),
        sa.Column("ptr_id", sa.Integer(), nullable=True),
        sa.Column("poh_acurrency", sa.Integer(), nullable=True),
        sa.Column("poh_acurrencyexchange", sa.Numeric(18, 6), nullable=True),
        sa.Column("poh_perceptions", sa.Numeric(18, 6), nullable=True),
        sa.Column("poh_taxes", sa.Numeric(18, 6), nullable=True),
        sa.Column("poh_charges", sa.Numeric(18, 6), nullable=True),
        sa.Column("poh_discount1", sa.Numeric(18, 6), nullable=True),
        sa.Column("poh_discount2", sa.Numeric(18, 6), nullable=True),
        sa.Column("poh_discount3", sa.Numeric(18, 6), nullable=True),
        sa.Column("poh_discount4", sa.Numeric(18, 6), nullable=True),
        sa.Column("pho_selectedinrecepcion", sa.Boolean(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("poh_validup2date", sa.DateTime(), nullable=True),
        sa.Column("poa_id", sa.Integer(), nullable=True),
        sa.Column("poh_pendingcoeficient", sa.Numeric(18, 6), nullable=True),
        sa.Column("poh_taxcoeficient", sa.Numeric(18, 6), nullable=True),
        sa.Column("simi_id", sa.Integer(), nullable=True),
        sa.Column("pro_id", sa.Integer(), nullable=True),
        sa.Column("poh_total", sa.Numeric(18, 6), nullable=True),
        sa.Column("poh_totalinsuppcurrency", sa.Numeric(18, 6), nullable=True),
        sa.Column("poh_isemailenvied", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("comp_id", "bra_id", "poh_id"),
    )
    op.create_index("idx_poh_comp_id", "tb_purchase_order_header", ["comp_id"])
    op.create_index("idx_poh_bra_id", "tb_purchase_order_header", ["bra_id"])
    op.create_index("idx_poh_poh_id", "tb_purchase_order_header", ["poh_id"])
    op.create_index("idx_poh_cd", "tb_purchase_order_header", ["poh_cd"])
    op.create_index("idx_poh_supp_id", "tb_purchase_order_header", ["supp_id"])
    op.create_index("idx_poh_iseditingcd", "tb_purchase_order_header", ["poh_iseditingcd"])

    # Tabla detalle de órdenes de compra
    op.create_table(
        "tb_purchase_order_detail",
        sa.Column("comp_id", sa.Integer(), nullable=False),
        sa.Column("bra_id", sa.Integer(), nullable=False),
        sa.Column("poh_id", sa.BigInteger(), nullable=False),
        sa.Column("pod_id", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("curr_id", sa.Integer(), nullable=True),
        sa.Column("cont_id", sa.Integer(), nullable=True),
        sa.Column("pod_qty", sa.Numeric(18, 6), nullable=True),
        sa.Column("pod_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("tax_id", sa.Integer(), nullable=True),
        sa.Column("pod_isprocessed", sa.Boolean(), nullable=True),
        sa.Column("pod_isediting", sa.Boolean(), nullable=True),
        sa.Column("pod_iseditingcd", sa.DateTime(), nullable=True),
        sa.Column("pod_obs", sa.Text(), nullable=True),
        sa.Column("pod_priceb", sa.Numeric(18, 6), nullable=True),
        sa.Column("pod_custom", sa.Boolean(), nullable=True),
        sa.Column("pod_customnumber", sa.String(100), nullable=True),
        sa.Column("pod_discount1", sa.Numeric(18, 6), nullable=True),
        sa.Column("pod_discount2", sa.Numeric(18, 6), nullable=True),
        sa.Column("pod_discount3", sa.Numeric(18, 6), nullable=True),
        sa.Column("pod_discount4", sa.Numeric(18, 6), nullable=True),
        sa.Column("djai_id", sa.Integer(), nullable=True),
        sa.Column("pod_initqty", sa.Numeric(18, 6), nullable=True),
        sa.Column("pod_confirmedqty", sa.Numeric(18, 6), nullable=True),
        sa.Column("pod_surcharge1", sa.Numeric(18, 6), nullable=True),
        sa.Column("pod_surcharge2", sa.Numeric(18, 6), nullable=True),
        sa.Column("pod_surcharge3", sa.Numeric(18, 6), nullable=True),
        sa.Column("pod_surcharge4", sa.Numeric(18, 6), nullable=True),
        sa.Column("pod_pricewithdiscountandcharges", sa.Numeric(18, 6), nullable=True),
        sa.Column("simi_id", sa.Integer(), nullable=True),
        sa.Column("simid_id", sa.Integer(), nullable=True),
        sa.Column("pod_origin", sa.String(100), nullable=True),
        sa.Column("pod_from", sa.String(100), nullable=True),
        sa.Column("pod_stamp", sa.String(100), nullable=True),
        sa.Column("pod_lotnumber", sa.String(100), nullable=True),
        sa.Column("pod_expirationdate", sa.DateTime(), nullable=True),
        sa.Column("pod_includeinavailablestock", sa.Boolean(), nullable=True),
        sa.Column("pod_id_from", sa.BigInteger(), nullable=True),
        sa.Column("pod_id_from_cd", sa.DateTime(), nullable=True),
        sa.Column("stor_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("comp_id", "bra_id", "poh_id", "pod_id"),
    )
    op.create_index("idx_pod_comp_id", "tb_purchase_order_detail", ["comp_id"])
    op.create_index("idx_pod_bra_id", "tb_purchase_order_detail", ["bra_id"])
    op.create_index("idx_pod_poh_id", "tb_purchase_order_detail", ["poh_id"])
    op.create_index("idx_pod_pod_id", "tb_purchase_order_detail", ["pod_id"])
    op.create_index("idx_pod_item_id", "tb_purchase_order_detail", ["item_id"])
    op.create_index("idx_pod_iseditingcd", "tb_purchase_order_detail", ["pod_iseditingcd"])


def downgrade() -> None:
    # Eliminar índices del detalle
    op.drop_index("idx_pod_iseditingcd", table_name="tb_purchase_order_detail")
    op.drop_index("idx_pod_item_id", table_name="tb_purchase_order_detail")
    op.drop_index("idx_pod_pod_id", table_name="tb_purchase_order_detail")
    op.drop_index("idx_pod_poh_id", table_name="tb_purchase_order_detail")
    op.drop_index("idx_pod_bra_id", table_name="tb_purchase_order_detail")
    op.drop_index("idx_pod_comp_id", table_name="tb_purchase_order_detail")
    op.drop_table("tb_purchase_order_detail")

    # Eliminar índices de la cabecera
    op.drop_index("idx_poh_iseditingcd", table_name="tb_purchase_order_header")
    op.drop_index("idx_poh_supp_id", table_name="tb_purchase_order_header")
    op.drop_index("idx_poh_cd", table_name="tb_purchase_order_header")
    op.drop_index("idx_poh_poh_id", table_name="tb_purchase_order_header")
    op.drop_index("idx_poh_bra_id", table_name="tb_purchase_order_header")
    op.drop_index("idx_poh_comp_id", table_name="tb_purchase_order_header")
    op.drop_table("tb_purchase_order_header")
