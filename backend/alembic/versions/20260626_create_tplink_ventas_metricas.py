"""Create tplink_ventas_metricas table

Revision ID: 20260626_create_tplink_ventas_metricas
Revises: 20260624_permisos_dashboard_tplink
Create Date: 2026-06-26

Additive migration: creates tplink_ventas_metricas as a dedicated pre-calculated
metrics table for TP-Link store (id=2645) sales, using cost list 8 (coslis_id=8).
Mirrors the schema of ml_ventas_metricas exactly. ml_ventas_metricas is untouched.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260626_create_tplink_ventas_metricas"
down_revision = "20260624_permisos_dashboard_tplink"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tplink_ventas_metricas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("id_operacion", sa.BigInteger(), nullable=False),
        sa.Column("ml_order_id", sa.String(length=50), nullable=True),
        sa.Column("pack_id", sa.BigInteger(), nullable=True),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("codigo", sa.String(length=100), nullable=True),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("marca", sa.String(length=255), nullable=True),
        sa.Column("categoria", sa.String(length=255), nullable=True),
        sa.Column("subcategoria", sa.String(length=255), nullable=True),
        sa.Column("fecha_venta", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fecha_calculo", sa.Date(), nullable=True),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("monto_unitario", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("monto_total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("cotizacion_dolar", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("costo_unitario_sin_iva", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("costo_total_sin_iva", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("moneda_costo", sa.String(length=10), nullable=True),
        sa.Column("tipo_lista", sa.String(length=50), nullable=True),
        sa.Column("porcentaje_comision_ml", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("comision_ml", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("costo_envio_ml", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("tipo_logistica", sa.String(length=50), nullable=True),
        sa.Column("monto_limpio", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("costo_total", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("ganancia", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("markup_porcentaje", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("offset_flex", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("prli_id", sa.Integer(), nullable=True),
        sa.Column("mla_id", sa.String(length=50), nullable=True),
        sa.Column("mlp_official_store_id", sa.Integer(), nullable=True),
        sa.Column(
            "is_cancelled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("fecha_cancelacion", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id_operacion", name="uq_tplink_ventas_metricas_id_operacion"),
    )

    # Indexes mirroring ml_ventas_metricas naming convention
    op.create_index(op.f("ix_tplink_ventas_metricas_id"), "tplink_ventas_metricas", ["id"], unique=False)
    op.create_index(
        op.f("ix_tplink_ventas_metricas_id_operacion"), "tplink_ventas_metricas", ["id_operacion"], unique=True
    )
    op.create_index(
        op.f("ix_tplink_ventas_metricas_ml_order_id"), "tplink_ventas_metricas", ["ml_order_id"], unique=False
    )
    op.create_index(op.f("ix_tplink_ventas_metricas_pack_id"), "tplink_ventas_metricas", ["pack_id"], unique=False)
    op.create_index(op.f("ix_tplink_ventas_metricas_item_id"), "tplink_ventas_metricas", ["item_id"], unique=False)
    op.create_index(op.f("ix_tplink_ventas_metricas_marca"), "tplink_ventas_metricas", ["marca"], unique=False)
    op.create_index(op.f("ix_tplink_ventas_metricas_categoria"), "tplink_ventas_metricas", ["categoria"], unique=False)
    op.create_index(
        op.f("ix_tplink_ventas_metricas_fecha_venta"), "tplink_ventas_metricas", ["fecha_venta"], unique=False
    )
    op.create_index(
        op.f("ix_tplink_ventas_metricas_fecha_calculo"), "tplink_ventas_metricas", ["fecha_calculo"], unique=False
    )
    op.create_index(
        op.f("ix_tplink_ventas_metricas_mlp_official_store_id"),
        "tplink_ventas_metricas",
        ["mlp_official_store_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tplink_ventas_metricas_is_cancelled"), "tplink_ventas_metricas", ["is_cancelled"], unique=False
    )


def downgrade() -> None:
    # Drop indexes first, then the table. ml_ventas_metricas is untouched.
    op.drop_index(op.f("ix_tplink_ventas_metricas_is_cancelled"), table_name="tplink_ventas_metricas")
    op.drop_index(
        op.f("ix_tplink_ventas_metricas_mlp_official_store_id"), table_name="tplink_ventas_metricas"
    )
    op.drop_index(op.f("ix_tplink_ventas_metricas_fecha_calculo"), table_name="tplink_ventas_metricas")
    op.drop_index(op.f("ix_tplink_ventas_metricas_fecha_venta"), table_name="tplink_ventas_metricas")
    op.drop_index(op.f("ix_tplink_ventas_metricas_categoria"), table_name="tplink_ventas_metricas")
    op.drop_index(op.f("ix_tplink_ventas_metricas_marca"), table_name="tplink_ventas_metricas")
    op.drop_index(op.f("ix_tplink_ventas_metricas_item_id"), table_name="tplink_ventas_metricas")
    op.drop_index(op.f("ix_tplink_ventas_metricas_pack_id"), table_name="tplink_ventas_metricas")
    op.drop_index(op.f("ix_tplink_ventas_metricas_ml_order_id"), table_name="tplink_ventas_metricas")
    op.drop_index(op.f("ix_tplink_ventas_metricas_id_operacion"), table_name="tplink_ventas_metricas")
    op.drop_index(op.f("ix_tplink_ventas_metricas_id"), table_name="tplink_ventas_metricas")
    op.drop_table("tplink_ventas_metricas")
