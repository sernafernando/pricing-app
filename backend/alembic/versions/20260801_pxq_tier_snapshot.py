"""ml-wholesale-pxq-pricing PR3a: snapshot de la última sincronización en ml_pxq_tier

Agrega `cantidad_sincronizada` / `precio_sincronizado`: lo que MercadoLibre
confirmó en el último sync exitoso.

Sin ese punto de referencia, el diff previo a la escritura solo podía comparar
local contra vivo, y esa comparación NO distingue quién movió el valor: una
edición nuestra y una edición hecha en ML se ven exactamente igual. La regla
anterior desempataba mirando `estado`, que es un proxy pobre — un tramo en
`listo` pisaba lo que hubiera en ML, en silencio, en el camino de plata.

Con el snapshot como base compartida el merge es a tres puntas y los cuatro
casos quedan sin ambigüedad: nadie movió (keep), movimos nosotros (modify),
movió ML (409), movieron los dos (409 con ambos lados).

Ambas columnas son NULLABLE: NULL significa "nunca sincronizado", y un tramo
que nunca se sincronizó no tiene de qué haber divergido.

Revision ID: 20260801_pxq_tier_snapshot
Revises: 20260801_pxq_permisos_backfill
Create Date: 2026-08-01

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260801_pxq_tier_snapshot"
down_revision = "20260801_pxq_permisos_backfill"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ml_pxq_tier", sa.Column("cantidad_sincronizada", sa.Integer(), nullable=True))
    op.add_column("ml_pxq_tier", sa.Column("precio_sincronizado", sa.Numeric(14, 2), nullable=True))


def downgrade():
    op.drop_column("ml_pxq_tier", "precio_sincronizado")
    op.drop_column("ml_pxq_tier", "cantidad_sincronizada")
