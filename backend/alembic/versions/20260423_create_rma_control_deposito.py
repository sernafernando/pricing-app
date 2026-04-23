"""Create rma_control_deposito_items table + permissions

Revision ID: 20260423_rma_control_deposito
Revises: 20260422_rma_estado_prov_envio
Create Date: 2026-04-23

New table for tracking physical verification of RMA items received by depósito.
State machine: pendiente → rma → deposito | pendiente/rma → no_baja

Permissions:
- rma.control_deposito: view the control page
- rma.control_deposito_no_baja: mark items as "no baja" (critical)
"""

from alembic import op
import sqlalchemy as sa

revision = "20260423_rma_control_deposito"
down_revision = "20260422_rma_estado_prov_envio"
branch_labels = None
depends_on = None

PERMISOS = [
    (
        "rma.control_deposito",
        "Control Depósito RMA",
        "Ver la pantalla de control de bajada a depósito de items RMA",
        "rma",
        70,
        False,
    ),
    (
        "rma.control_deposito_no_baja",
        "Marcar No Baja a Depósito",
        "Marcar items RMA como excepción que no baja a depósito (ej: Outlet)",
        "rma",
        71,
        True,
    ),
]

ROL_PERMISOS = {
    "ADMIN": ["rma.control_deposito", "rma.control_deposito_no_baja"],
    "GERENTE": ["rma.control_deposito"],
    "VENTAS": ["rma.control_deposito"],
    "LOGISTICA": ["rma.control_deposito"],
}


def upgrade() -> None:
    # 1. Create table
    op.create_table(
        "rma_control_deposito_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        # FK to source RMA item (unique — one checklist entry per RMA item)
        sa.Column(
            "rma_caso_item_id",
            sa.Integer(),
            sa.ForeignKey("rma_caso_items.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        # Denormalized for fast scan lookup
        sa.Column("caso_id", sa.Integer(), sa.ForeignKey("rma_casos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("numero_caso", sa.String(20), nullable=False),
        sa.Column("serial_number", sa.String(100), nullable=True),
        sa.Column("ean", sa.String(50), nullable=True),
        sa.Column("item_id", sa.BigInteger(), nullable=True),
        sa.Column("producto_desc", sa.String(500), nullable=True),
        # State machine
        sa.Column(
            "estado",
            sa.String(20),
            nullable=False,
            server_default="pendiente",
        ),
        sa.CheckConstraint(
            "estado IN ('pendiente', 'rma', 'deposito', 'no_baja')",
            name="ck_control_depo_estado",
        ),
        # RMA team scan
        sa.Column("pistoleado_rma_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("pistoleado_rma_fecha", sa.DateTime(timezone=True), nullable=True),
        # Depósito team scan (requires operador PIN)
        sa.Column("pistoleado_depo_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("pistoleado_depo_operador_id", sa.Integer(), sa.ForeignKey("operadores.id"), nullable=True),
        sa.Column("pistoleado_depo_fecha", sa.DateTime(timezone=True), nullable=True),
        # No baja exception
        sa.Column("no_baja_confirmado_por", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("no_baja_fecha", sa.DateTime(timezone=True), nullable=True),
        sa.Column("no_baja_motivo", sa.Text(), nullable=True),
        # System
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now(), nullable=True),
    )

    # 2. Indexes for scan hot path (partial — only active items)
    op.execute(
        "CREATE INDEX idx_control_depo_serial "
        "ON rma_control_deposito_items(serial_number) "
        "WHERE estado IN ('pendiente', 'rma')"
    )
    op.execute(
        "CREATE INDEX idx_control_depo_ean ON rma_control_deposito_items(ean) WHERE estado IN ('pendiente', 'rma')"
    )
    op.create_index("idx_control_depo_estado", "rma_control_deposito_items", ["estado"])
    op.create_index("idx_control_depo_created", "rma_control_deposito_items", ["created_at"])
    op.create_index("idx_control_depo_caso", "rma_control_deposito_items", ["caso_id"])

    # 3. Insert permissions
    for codigo, nombre, desc, cat, orden, critico in PERMISOS:
        critico_str = "true" if critico else "false"
        op.execute(
            f"INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at) "
            f"VALUES ('{codigo}', '{nombre}', '{desc}', '{cat}', {orden}, {critico_str}, NOW()) "
            f"ON CONFLICT (codigo) DO NOTHING"
        )

    # 4. Assign to roles
    for rol, codigos in ROL_PERMISOS.items():
        for codigo in codigos:
            op.execute(
                f"INSERT INTO roles_permisos_base (rol_id, permiso_id) "
                f"SELECT r.id, p.id FROM roles r CROSS JOIN permisos p "
                f"WHERE r.codigo = '{rol}' AND p.codigo = '{codigo}' "
                f"ON CONFLICT DO NOTHING"
            )


def downgrade() -> None:
    # Remove role assignments
    codigos = [p[0] for p in PERMISOS]
    codigos_str = ", ".join(f"'{c}'" for c in codigos)

    op.execute(
        f"DELETE FROM roles_permisos_base WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo IN ({codigos_str}))"
    )
    op.execute(
        f"DELETE FROM usuarios_permisos_override "
        f"WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo IN ({codigos_str}))"
    )
    op.execute(f"DELETE FROM permisos WHERE codigo IN ({codigos_str})")

    # Drop indexes (partial indexes need explicit drop)
    op.execute("DROP INDEX IF EXISTS idx_control_depo_serial")
    op.execute("DROP INDEX IF EXISTS idx_control_depo_ean")
    op.drop_index("idx_control_depo_estado", table_name="rma_control_deposito_items")
    op.drop_index("idx_control_depo_created", table_name="rma_control_deposito_items")
    op.drop_index("idx_control_depo_caso", table_name="rma_control_deposito_items")

    op.drop_table("rma_control_deposito_items")
