"""Add dynamic estado_caso to rma_casos via rma_seguimiento_opciones

Seeds estado_caso options, adds estado_caso_id FK to rma_casos,
and migrates existing hardcoded estado values to their option IDs.
Keeps the old `estado` column for backward compatibility (read-only).

Revision ID: 20260305_rma_estado_caso
Revises: 20260305_rma_proveedores
Create Date: 2026-03-05

"""

import sqlalchemy as sa
from alembic import op

revision = "20260305_rma_estado_caso"
down_revision = "20260305_rma_proveedores"
branch_labels = None
depends_on = None

# Seed values: (valor, orden, color)
ESTADOS_CASO = [
    ("Abierto", 1, "yellow"),
    ("En proceso", 2, "blue"),
    ("Listo para enviar a proveedor", 3, "orange"),
    ("Enviado a proveedor", 4, "purple"),
    ("Listo para enviar a cliente", 5, "blue"),
    ("Listo para retiro de cliente", 6, "green"),
    ("Cerrado", 7, "green"),
]

# Map old hardcoded values to new option valores
OLD_TO_NEW = {
    "abierto": "Abierto",
    "en_espera": "En proceso",
    "cerrado": "Cerrado",
}


def upgrade():
    # 1. Seed estado_caso options
    opciones_table = sa.table(
        "rma_seguimiento_opciones",
        sa.column("id", sa.Integer),
        sa.column("categoria", sa.String),
        sa.column("valor", sa.String),
        sa.column("orden", sa.Integer),
        sa.column("activo", sa.Boolean),
        sa.column("color", sa.String),
    )

    for valor, orden, color in ESTADOS_CASO:
        op.execute(
            opciones_table.insert().values(
                categoria="estado_caso",
                valor=valor,
                orden=orden,
                activo=True,
                color=color,
            )
        )

    # 2. Add estado_caso_id column to rma_casos
    op.add_column(
        "rma_casos",
        sa.Column(
            "estado_caso_id",
            sa.Integer(),
            sa.ForeignKey("rma_seguimiento_opciones.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_rma_casos_estado_caso_id", "rma_casos", ["estado_caso_id"])

    # 3. Migrate existing data: map old estado string to new option IDs
    conn = op.get_bind()
    for old_val, new_val in OLD_TO_NEW.items():
        # Get the option ID for the new value
        result = conn.execute(
            sa.text(
                "SELECT id FROM rma_seguimiento_opciones "
                "WHERE categoria = 'estado_caso' AND valor = :valor"
            ),
            {"valor": new_val},
        )
        row = result.fetchone()
        if row:
            option_id = row[0]
            conn.execute(
                sa.text(
                    "UPDATE rma_casos SET estado_caso_id = :option_id "
                    "WHERE estado = :old_val"
                ),
                {"option_id": option_id, "old_val": old_val},
            )

    # 4. Set any remaining NULL estado_caso_id to "Abierto"
    result = conn.execute(
        sa.text(
            "SELECT id FROM rma_seguimiento_opciones "
            "WHERE categoria = 'estado_caso' AND valor = 'Abierto'"
        )
    )
    abierto_row = result.fetchone()
    if abierto_row:
        conn.execute(
            sa.text(
                "UPDATE rma_casos SET estado_caso_id = :option_id "
                "WHERE estado_caso_id IS NULL"
            ),
            {"option_id": abierto_row[0]},
        )


def downgrade():
    op.drop_index("ix_rma_casos_estado_caso_id", table_name="rma_casos")
    op.drop_column("rma_casos", "estado_caso_id")
    op.execute(
        sa.text(
            "DELETE FROM rma_seguimiento_opciones WHERE categoria = 'estado_caso'"
        )
    )
