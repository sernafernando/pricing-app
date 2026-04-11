"""add indexes on producto.categoria, producto.subcategoria_id, oferta_ml.fecha_desde, oferta_ml.fecha_hasta

Revision ID: 20260410_perf_idx
Revises: 20260410_rma_reason
Create Date: 2026-04-10
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260410_perf_idx"
down_revision = "20260410_rma_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_productos_erp_categoria", "productos_erp", ["categoria"], if_not_exists=True)
    op.create_index("ix_productos_erp_subcategoria_id", "productos_erp", ["subcategoria_id"], if_not_exists=True)
    op.create_index("ix_ofertas_ml_fecha_desde", "ofertas_ml", ["fecha_desde"], if_not_exists=True)
    op.create_index("ix_ofertas_ml_fecha_hasta", "ofertas_ml", ["fecha_hasta"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_ofertas_ml_fecha_hasta", table_name="ofertas_ml", if_exists=True)
    op.drop_index("ix_ofertas_ml_fecha_desde", table_name="ofertas_ml", if_exists=True)
    op.drop_index("ix_productos_erp_subcategoria_id", table_name="productos_erp", if_exists=True)
    op.drop_index("ix_productos_erp_categoria", table_name="productos_erp", if_exists=True)
