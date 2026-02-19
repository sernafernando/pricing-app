"""Agregar tienda_oficial_id a tabla asignaciones

Las asignaciones de items sin MLA ahora son por tienda oficial de ML.
Se agrega la columna y se migran todas las asignaciones existentes a
tienda Gauss (57997) ya que históricamente era la única tienda
contemplada por el sistema.

Revision ID: 20260219_tienda_asig
Revises: 20260219_manual_envio
Create Date: 2026-02-19

"""

from alembic import op
import sqlalchemy as sa

revision = "20260219_tienda_asig"
down_revision = "20260219_manual_envio"
branch_labels = None
depends_on = None

# Gauss = tienda principal, todas las asignaciones pre-existentes van acá
GAUSS_STORE_ID = 57997


def upgrade():
    # 1. Agregar columna nullable
    op.add_column("asignaciones", sa.Column("tienda_oficial_id", sa.Integer(), nullable=True))

    # 2. Index simple para filtros por tienda
    op.create_index("idx_asignacion_tienda_oficial", "asignaciones", ["tienda_oficial_id"])

    # 3. Index compuesto tipo+ref+subtipo+tienda para verificar duplicados
    op.create_index(
        "idx_asignacion_tipo_ref_subtipo_tienda",
        "asignaciones",
        ["tipo", "referencia_id", "subtipo", "tienda_oficial_id"],
    )

    # 4. Migrar asignaciones existentes de items_sin_mla a Gauss
    op.execute(
        sa.text(
            """
            UPDATE asignaciones
            SET tienda_oficial_id = :store_id
            WHERE tipo = 'item_sin_mla'
              AND tienda_oficial_id IS NULL
            """
        ).bindparams(store_id=GAUSS_STORE_ID)
    )


def downgrade():
    op.drop_index("idx_asignacion_tipo_ref_subtipo_tienda", table_name="asignaciones")
    op.drop_index("idx_asignacion_tienda_oficial", table_name="asignaciones")
    op.drop_column("asignaciones", "tienda_oficial_id")
