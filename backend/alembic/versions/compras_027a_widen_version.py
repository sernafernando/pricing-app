"""compras 027a — ensancha alembic_version.version_num

Revision ID: compras_027a_widen_version
Revises: compras_027_pedido_corregido
Create Date: 2026-05-20

Las migraciones compras_028 y compras_029 tienen revision ids de 35 y 39
caracteres, más largos que el varchar(32) por defecto de la columna
alembic_version.version_num. En PostgreSQL eso provoca StringDataRightTruncation
al registrar la migración (invisible en los tests, que corren sobre SQLite).

Esta migración ensancha la columna a varchar(128) ANTES de compras_028, para
que Alembic pueda registrar esos revision ids.
"""

from alembic import op


# revision identifiers
revision = "compras_027a_widen_version"
down_revision = "compras_027_pedido_corregido"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")


def downgrade() -> None:
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(32)")
