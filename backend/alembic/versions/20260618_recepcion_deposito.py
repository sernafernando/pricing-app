"""Recepción de mercadería por depósito — tabla, estados y permiso.

Creates pedido_compra_ingresos, extends estado CHECK constraint on pedidos_compra,
and seeds deposito.recibir_mercaderia permission (SUPERADMIN only).

Revision ID: 20260618_recepcion_deposito
Revises: 20260618_add_oc_link_to_pedidos_compra
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa

revision = "20260618_recepcion_deposito"
down_revision = "20260618_add_oc_link_to_pedidos_compra"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ──────────────────────────────────────────────────────────────────
    # 1. CREATE TABLE pedido_compra_ingresos (append-only, grano pod_id)
    # ──────────────────────────────────────────────────────────────────
    op.create_table(
        "pedido_compra_ingresos",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "pedido_id",
            sa.BigInteger,
            sa.ForeignKey("pedidos_compra.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Snapshot of OC identity — logical FK, no physical constraint
        sa.Column("oc_comp_id", sa.Integer, nullable=True),
        sa.Column("oc_bra_id", sa.Integer, nullable=True),
        sa.Column("oc_poh_id", sa.BigInteger, nullable=True),
        # pod_id is NULL only for SIN-OC sentinel rows
        sa.Column("pod_id", sa.BigInteger, nullable=True),
        sa.Column("item_id", sa.Integer, nullable=True),
        sa.Column("stor_id", sa.Integer, nullable=True),
        sa.Column("cantidad_recibida", sa.Numeric(18, 6), nullable=False),
        sa.Column("fecha_ingreso", sa.Date, nullable=True, server_default=sa.text("CURRENT_DATE")),
        sa.Column(
            "usuario_id",
            sa.Integer,
            sa.ForeignKey("usuarios.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("observaciones", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint("cantidad_recibida > 0", name="ck_pci_cantidad_positiva"),
    )
    op.create_index("ix_pci_pedido", "pedido_compra_ingresos", ["pedido_id"])
    # Partial index on pod_id (excludes SIN-OC sentinel rows from saldo aggregation)
    op.create_index(
        "ix_pci_pod",
        "pedido_compra_ingresos",
        ["pod_id"],
        postgresql_where=sa.text("pod_id IS NOT NULL"),
    )
    op.create_index(
        "ix_pci_oc_linea",
        "pedido_compra_ingresos",
        ["oc_comp_id", "oc_bra_id", "oc_poh_id", "pod_id"],
    )

    # ──────────────────────────────────────────────────────────────────
    # 2. Extend pedidos_compra.estado CheckConstraint
    #    Drop existing constraint and recreate with the two new states.
    # ──────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE pedidos_compra DROP CONSTRAINT IF EXISTS ck_pedidos_compra_estado")
    op.execute(
        """
        ALTER TABLE pedidos_compra
        ADD CONSTRAINT ck_pedidos_compra_estado
        CHECK (estado IN (
            'borrador','pendiente_aprobacion','aprobado','rechazado',
            'cancelado','pagado_parcial','pagado','recibido','con_faltantes'
        ))
        """
    )

    # ──────────────────────────────────────────────────────────────────
    # 3. Seed permiso deposito.recibir_mercaderia
    #    Assigned ONLY to SUPERADMIN (operarios get it via usuarios_permisos_override).
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES (
            'deposito.recibir_mercaderia',
            'Recibir mercadería',
            'Registrar la recepción física de pedidos en depósito (recepción por ítem o '
            'confirmación a nivel pedido) y generar retiros de proveedor.',
            'deposito_sector',
            200,
            true,
            NOW()
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES (
            'deposito.despachar_retiro',
            'Despachar retiro de proveedor',
            'Generar y gestionar etiquetas de retiro de mercadería por proveedor.',
            'deposito_sector',
            201,
            false,
            NOW()
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r CROSS JOIN permisos p
        WHERE r.codigo = 'SUPERADMIN'
          AND p.codigo IN ('deposito.recibir_mercaderia', 'deposito.despachar_retiro')
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    # Remove permission assignments and seeded permisos
    op.execute(
        "DELETE FROM roles_permisos_base WHERE permiso_id IN "
        "(SELECT id FROM permisos WHERE codigo IN "
        "('deposito.recibir_mercaderia','deposito.despachar_retiro'))"
    )
    op.execute("DELETE FROM permisos WHERE codigo IN ('deposito.recibir_mercaderia','deposito.despachar_retiro')")

    # Revert estado CheckConstraint to original 7-state set
    op.execute("ALTER TABLE pedidos_compra DROP CONSTRAINT IF EXISTS ck_pedidos_compra_estado")
    op.execute(
        """
        ALTER TABLE pedidos_compra
        ADD CONSTRAINT ck_pedidos_compra_estado
        CHECK (estado IN (
            'borrador','pendiente_aprobacion','aprobado','rechazado',
            'cancelado','pagado_parcial','pagado'
        ))
        """
    )

    # Drop table (cascade-safe since FK is RESTRICT, not CASCADE)
    op.drop_index("ix_pci_oc_linea", table_name="pedido_compra_ingresos")
    op.drop_index("ix_pci_pod", table_name="pedido_compra_ingresos")
    op.drop_index("ix_pci_pedido", table_name="pedido_compra_ingresos")
    op.drop_table("pedido_compra_ingresos")
