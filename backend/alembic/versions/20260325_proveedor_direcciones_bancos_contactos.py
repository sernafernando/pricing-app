"""Create proveedor_direcciones, proveedor_bancos, proveedor_contactos tables.
Migrate RMA delivery addresses to proveedor_direcciones.

Revision ID: c4a9e2f3b710
Revises: b7e2a4f01c38
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa

revision = "c4a9e2f3b710"
down_revision = "b7e2a4f01c38"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. proveedor_direcciones ──────────────────────────────────
    op.create_table(
        "proveedor_direcciones",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "proveedor_id",
            sa.Integer(),
            sa.ForeignKey("proveedores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("etiqueta", sa.String(100), nullable=False, server_default="Depósito"),
        sa.Column("direccion", sa.String(500), nullable=False),
        sa.Column("cp", sa.String(20), nullable=True),
        sa.Column("ciudad", sa.String(255), nullable=True),
        sa.Column("provincia", sa.String(255), nullable=True),
        sa.Column("horario_recepcion", sa.String(255), nullable=True),
        sa.Column("contacto_nombre", sa.String(255), nullable=True),
        sa.Column("contacto_telefono", sa.String(100), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("origen", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_proveedor_direcciones_proveedor_id", "proveedor_direcciones", ["proveedor_id"])

    # ── 2. proveedor_bancos ───────────────────────────────────────
    op.create_table(
        "proveedor_bancos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "proveedor_id",
            sa.Integer(),
            sa.ForeignKey("proveedores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("banco", sa.String(255), nullable=False),
        sa.Column("tipo_cuenta", sa.String(50), nullable=True),
        sa.Column("cbu", sa.String(30), nullable=True),
        sa.Column("alias", sa.String(100), nullable=True),
        sa.Column("numero_cuenta", sa.String(50), nullable=True),
        sa.Column("sucursal", sa.String(100), nullable=True),
        sa.Column("titular", sa.String(255), nullable=True),
        sa.Column("cuit_titular", sa.String(20), nullable=True),
        sa.Column("moneda", sa.String(10), nullable=True, server_default="ARS"),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_proveedor_bancos_proveedor_id", "proveedor_bancos", ["proveedor_id"])

    # ── 3. proveedor_contactos ────────────────────────────────────
    op.create_table(
        "proveedor_contactos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "proveedor_id",
            sa.Integer(),
            sa.ForeignKey("proveedores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nombre", sa.String(255), nullable=False),
        sa.Column("rol", sa.String(100), nullable=True),
        sa.Column("telefono", sa.String(100), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("cargo", sa.String(255), nullable=True),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_proveedor_contactos_proveedor_id", "proveedor_contactos", ["proveedor_id"])

    # ── 4. Migrar direcciones de entrega RMA a proveedor_direcciones ─
    op.execute("""
        INSERT INTO proveedor_direcciones (proveedor_id, etiqueta, direccion, cp, ciudad, provincia,
                                           horario_recepcion, contacto_nombre, notas, origen, activo, created_at)
        SELECT r.proveedor_id, 'Depósito (RMA)', r.direccion_entrega, r.cp_entrega,
               r.ciudad_entrega, r.provincia_entrega, r.horario_recepcion,
               r.representante_tecnico, r.notas_rma, 'rma', true, NOW()
        FROM rma_proveedores r
        WHERE r.proveedor_id IS NOT NULL
          AND r.direccion_entrega IS NOT NULL
          AND r.direccion_entrega != ''
    """)


def downgrade() -> None:
    op.drop_index("ix_proveedor_contactos_proveedor_id", table_name="proveedor_contactos")
    op.drop_table("proveedor_contactos")
    op.drop_index("ix_proveedor_bancos_proveedor_id", table_name="proveedor_bancos")
    op.drop_table("proveedor_bancos")
    op.drop_index("ix_proveedor_direcciones_proveedor_id", table_name="proveedor_direcciones")
    op.drop_table("proveedor_direcciones")
