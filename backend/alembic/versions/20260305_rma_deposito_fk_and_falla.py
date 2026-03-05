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


def upgrade():
    # 1. Drop FK constraint on deposito_destino_id
    # The constraint was auto-named by SQLAlchemy following PostgreSQL convention
    op.drop_constraint(
        "rma_caso_items_deposito_destino_id_fkey",
        "rma_caso_items",
        type_="foreignkey",
    )

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
