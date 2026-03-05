"""Drop FK constraint on deposito_destino_id and add descripcion_falla column

deposito_destino_id now stores stor_id from tb_storage directly (no FK).
descripcion_falla is a free-text field for describing defects found during revision.

Revision ID: 20260305_rma_deposito_fk_falla
Revises: 20260305_permisos_rma
Create Date: 2026-03-05

"""

import sqlalchemy as sa
from alembic import op

revision = "20260305_rma_deposito_fk_falla"
down_revision = "20260305_permisos_rma"
branch_labels = None
depends_on = None


def _find_fk_constraint_name() -> str | None:
    """Find the actual FK constraint name on deposito_destino_id dynamically."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text("""
            SELECT con.conname
            FROM pg_catalog.pg_constraint con
            JOIN pg_catalog.pg_class rel ON rel.oid = con.conrelid
            JOIN pg_catalog.pg_namespace nsp ON nsp.oid = rel.relnamespace
            JOIN pg_catalog.pg_attribute att ON att.attrelid = rel.oid
                AND att.attnum = ANY(con.conkey)
            WHERE rel.relname = 'rma_caso_items'
              AND att.attname = 'deposito_destino_id'
              AND con.contype = 'f'
            LIMIT 1
        """)
    )
    row = result.fetchone()
    return row[0] if row else None


def upgrade():
    # 1. Drop FK constraint on deposito_destino_id (find actual name dynamically)
    fk_name = _find_fk_constraint_name()
    if fk_name:
        op.drop_constraint(fk_name, "rma_caso_items", type_="foreignkey")

    # 2. Add descripcion_falla text column for defect descriptions
    op.add_column(
        "rma_caso_items",
        sa.Column("descripcion_falla", sa.Text(), nullable=True),
    )


def downgrade():
    # 1. Remove descripcion_falla column
    op.drop_column("rma_caso_items", "descripcion_falla")

    # 2. Re-create FK constraint on deposito_destino_id
    op.create_foreign_key(
        "rma_caso_items_deposito_destino_id_fkey",
        "rma_caso_items",
        "rma_seguimiento_opciones",
        ["deposito_destino_id"],
        ["id"],
    )
