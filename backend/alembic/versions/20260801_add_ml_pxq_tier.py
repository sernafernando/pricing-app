"""ml-wholesale-pxq-pricing PR2: ml_pxq_tier table

Revision ID: 20260801_add_ml_pxq_tier
Revises: 20260731_ml_catalog_competition
Create Date: 2026-08-01

Local mirror table for MercadoLibre PxQ (price-by-quantity, wholesale)
tiers, the sole source of truth for the array-replace diff against
`/prices/standard/quantity` (PR 3). `cantidad_minima > 1` is a DB
CheckConstraint; max 5 tiers per publication is a SERVICE-layer rule
(422), deliberately NOT a DB constraint.

`item_id` is the MercadoLibre item id (MLA), denormalized from
`publicaciones_ml.mla` for the live-vs-mirror compare in PR 3 — not the
ERP `productos_erp.item_id` integer.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260801_add_ml_pxq_tier"
down_revision = "20260731_ml_catalog_competition"
branch_labels = None
depends_on = None

TABLE_NAME = "ml_pxq_tier"


def upgrade():
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "publicacion_ml_id",
            sa.Integer(),
            sa.ForeignKey("publicaciones_ml.id"),
            nullable=False,
        ),
        sa.Column("item_id", sa.String(32), nullable=False),
        sa.Column("cantidad_minima", sa.Integer(), nullable=False),
        sa.Column("precio_unitario", sa.Numeric(14, 2), nullable=False),
        sa.Column("costo_envio_total", sa.Numeric(14, 2), nullable=True),
        sa.Column("ml_price_id", sa.String(64), nullable=True),
        sa.Column("estado", sa.String(16), nullable=False, server_default="incompleto"),
        sa.Column(
            "usuario_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.CheckConstraint("cantidad_minima > 1", name="ck_ml_pxq_tier_cantidad_minima_gt_1"),
        sa.CheckConstraint(
            "estado IN ('incompleto', 'listo', 'sincronizado', 'desconocido')",
            name="ck_ml_pxq_tier_estado_valido",
        ),
        sa.UniqueConstraint("publicacion_ml_id", "cantidad_minima", name="uq_ml_pxq_tier_publicacion_cantidad_minima"),
    )
    op.create_index("ix_ml_pxq_tier_publicacion_ml_id", TABLE_NAME, ["publicacion_ml_id"])
    op.create_index("ix_ml_pxq_tier_item_id", TABLE_NAME, ["item_id"])
    op.create_index("ix_ml_pxq_tier_usuario_id", TABLE_NAME, ["usuario_id"])


def downgrade():
    op.drop_index("ix_ml_pxq_tier_usuario_id", table_name=TABLE_NAME)
    op.drop_index("ix_ml_pxq_tier_item_id", table_name=TABLE_NAME)
    op.drop_index("ix_ml_pxq_tier_publicacion_ml_id", table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
