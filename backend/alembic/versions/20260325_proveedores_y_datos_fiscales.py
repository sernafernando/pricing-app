"""Create proveedores and proveedor_datos_fiscales tables, add proveedor_id FK to rma_proveedores

Revision ID: b7e2a4f01c38
Revises: a3f5c8d91e02
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b7e2a4f01c38"
down_revision = "a3f5c8d91e02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Crear tabla proveedores ────────────────────────────────
    op.create_table(
        "proveedores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("supp_id", sa.BigInteger(), nullable=True),
        sa.Column("comp_id", sa.Integer(), nullable=True, server_default="1"),
        sa.Column("nombre", sa.String(255), nullable=False),
        sa.Column("cuit", sa.String(20), nullable=True),
        sa.Column("origen", sa.String(10), nullable=False, server_default="erp"),
        sa.Column("direccion", sa.String(500), nullable=True),
        sa.Column("cp", sa.String(20), nullable=True),
        sa.Column("ciudad", sa.String(255), nullable=True),
        sa.Column("provincia", sa.String(255), nullable=True),
        sa.Column("telefono", sa.String(100), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("representante", sa.String(255), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_proveedores_id", "proveedores", ["id"])
    op.create_index("ix_proveedores_nombre", "proveedores", ["nombre"])
    op.create_index("ix_proveedores_cuit", "proveedores", ["cuit"])
    op.create_index("ix_proveedores_supp_id", "proveedores", ["supp_id"])

    # ── 2. Crear tabla proveedor_datos_fiscales ───────────────────
    op.create_table(
        "proveedor_datos_fiscales",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "proveedor_id",
            sa.Integer(),
            sa.ForeignKey("proveedores.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("condicion_iva", sa.String(100), nullable=True),
        sa.Column("inscripto_ganancias", sa.Boolean(), nullable=True),
        sa.Column("estado_clave", sa.String(50), nullable=True),
        sa.Column("tipo_persona", sa.String(20), nullable=True),
        sa.Column("forma_juridica", sa.String(100), nullable=True),
        sa.Column("razon_social_afip", sa.String(500), nullable=True),
        sa.Column("actividad_principal", sa.String(500), nullable=True),
        sa.Column("actividad_principal_id", sa.Integer(), nullable=True),
        sa.Column("domicilio_fiscal", sa.String(500), nullable=True),
        sa.Column("domicilio_fiscal_cp", sa.String(20), nullable=True),
        sa.Column("domicilio_fiscal_provincia", sa.String(100), nullable=True),
        sa.Column("domicilio_fiscal_localidad", sa.String(255), nullable=True),
        sa.Column("padron_a4_raw", postgresql.JSONB(), nullable=True),
        sa.Column("cuit_consultado", sa.String(20), nullable=True),
        sa.Column("ultima_consulta_afip", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_error_afip", sa.Text(), nullable=True),
        sa.Column("wsid_consultado", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_proveedor_datos_fiscales_id", "proveedor_datos_fiscales", ["id"])
    op.create_index(
        "ix_proveedor_datos_fiscales_proveedor_id",
        "proveedor_datos_fiscales",
        ["proveedor_id"],
    )

    # ── 3. Agregar proveedor_id FK a rma_proveedores ─────────────
    op.add_column(
        "rma_proveedores",
        sa.Column(
            "proveedor_id",
            sa.Integer(),
            sa.ForeignKey("proveedores.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_rma_proveedores_proveedor_id",
        "rma_proveedores",
        ["proveedor_id"],
        unique=True,
    )

    # ── 4. Agregar columnas de extensión RMA (nuevos nombres) ────
    op.add_column("rma_proveedores", sa.Column("direccion_entrega", sa.String(500), nullable=True))
    op.add_column("rma_proveedores", sa.Column("cp_entrega", sa.String(20), nullable=True))
    op.add_column("rma_proveedores", sa.Column("ciudad_entrega", sa.String(255), nullable=True))
    op.add_column("rma_proveedores", sa.Column("provincia_entrega", sa.String(255), nullable=True))
    op.add_column("rma_proveedores", sa.Column("representante_tecnico", sa.String(255), nullable=True))
    op.add_column("rma_proveedores", sa.Column("horario_recepcion", sa.String(255), nullable=True))
    op.add_column("rma_proveedores", sa.Column("notas_rma", sa.Text(), nullable=True))

    # ── 5. Copiar datos de rma_proveedores a los nuevos campos RMA ─
    # Detect notes column name: some DBs have "notas", others "observaciones"
    conn = op.get_bind()
    result = conn.execute(
        sa.text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'rma_proveedores' AND column_name IN ('notas', 'observaciones')
    """)
    )
    notes_col = result.scalar() or "notas"

    op.execute(f"""
        UPDATE rma_proveedores
        SET direccion_entrega = direccion,
            cp_entrega = cp,
            ciudad_entrega = ciudad,
            provincia_entrega = provincia,
            representante_tecnico = representante,
            horario_recepcion = horario,
            notas_rma = {notes_col}
    """)

    # ── 6. Poblar proveedores desde rma_proveedores existentes ───
    op.execute(f"""
        INSERT INTO proveedores (supp_id, comp_id, nombre, cuit, origen,
                                 direccion, cp, ciudad, provincia,
                                 telefono, email, representante, notas,
                                 activo, created_at, updated_at)
        SELECT supp_id, comp_id, nombre, cuit, 'erp',
               direccion, cp, ciudad, provincia,
               telefono, email, representante, {notes_col},
               COALESCE(activo::boolean, true),
               created_at, updated_at
        FROM rma_proveedores
        WHERE supp_id IS NOT NULL
    """)

    # ── 7. Vincular rma_proveedores con proveedores recién creados ─
    op.execute("""
        UPDATE rma_proveedores r
        SET proveedor_id = p.id
        FROM proveedores p
        WHERE r.supp_id = p.supp_id
          AND r.comp_id = p.comp_id
          AND r.proveedor_id IS NULL
    """)


def downgrade() -> None:
    # Quitar columnas nuevas de rma_proveedores
    op.drop_index("ix_rma_proveedores_proveedor_id", table_name="rma_proveedores")
    op.drop_column("rma_proveedores", "notas_rma")
    op.drop_column("rma_proveedores", "horario_recepcion")
    op.drop_column("rma_proveedores", "representante_tecnico")
    op.drop_column("rma_proveedores", "provincia_entrega")
    op.drop_column("rma_proveedores", "ciudad_entrega")
    op.drop_column("rma_proveedores", "cp_entrega")
    op.drop_column("rma_proveedores", "direccion_entrega")
    op.drop_column("rma_proveedores", "proveedor_id")

    # Borrar tablas
    op.drop_index("ix_proveedor_datos_fiscales_proveedor_id", table_name="proveedor_datos_fiscales")
    op.drop_index("ix_proveedor_datos_fiscales_id", table_name="proveedor_datos_fiscales")
    op.drop_table("proveedor_datos_fiscales")

    op.drop_index("ix_proveedores_supp_id", table_name="proveedores")
    op.drop_index("ix_proveedores_cuit", table_name="proveedores")
    op.drop_index("ix_proveedores_nombre", table_name="proveedores")
    op.drop_index("ix_proveedores_id", table_name="proveedores")
    op.drop_table("proveedores")
