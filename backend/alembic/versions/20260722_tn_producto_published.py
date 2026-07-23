"""add nullable published column to tienda_nube_productos (DESPUBLICAR bugfix)

`activo` only means "present in the last full sync" — the TN sync sets it
true for every product returned by /products, including unpublished/draft
ones. The reconciliation service's DESPUBLICAR verdict was over-flagging
because it used `activo` as a "visible in storefront" proxy. This adds TN's
real product-level `published` flag so the service can key off the correct
field. Nullable, no backfill — existing rows stay `NULL` (unknown) until the
next sync run populates it; `published IS NULL` is treated as "unknown, not
published" by the reconciliation service's fail-safe.

Revision ID: 20260722_tn_producto_published
Revises: 20260722_tn_reconcile_tables
Create Date: 2026-07-22 18:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260722_tn_producto_published"
down_revision = "20260722_tn_reconcile_tables"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tienda_nube_productos", sa.Column("published", sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column("tienda_nube_productos", "published")
