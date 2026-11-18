"""MCP write actions: plans (plan -> confirm token -> apply), audit of applied rows + mcp.escribir

Revision ID: 20261124_mcp_write_actions
Revises: 20261123_ml_publicaciones_presets
Create Date: 2026-11-18

Delivery 2 of the MCP server: AI clients may change pricing (promos, list prices, cuotas, mayorista, pause/activate)
through the existing endpoints, always as plan -> confirmation -> apply. `mcp.escribir` is separate from
`mcp.conectar` and critical (it lets an outside app change prices as the user). Granted to ADMIN only; SUPERADMIN
gets it implicitly, anyone else by override. The parent revision is provisional (re-parented before the push).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261124_mcp_write_actions"
down_revision: Union[str, None] = "20261123_ml_publicaciones_presets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISO = {
    "codigo": "mcp.escribir",
    "nombre": "Modificar pricing desde IA (MCP)",
    "descripcion": (
        "Permitir que un cliente de IA conectado (Claude, Cursor, Gemini CLI, ChatGPT) modifique promos, precios, "
        "cuotas, mayoristas y estado de publicaciones, siempre con plan, confirmación y Deshacer en Acciones IA."
    ),
    "categoria": "administracion",
    "orden": 71,
}

_INSERT_PERMISO = sa.text("""
    INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
    VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, true, NOW())
    ON CONFLICT (codigo) DO NOTHING
""")

_INSERT_ROL_PERMISO = sa.text("""
    INSERT INTO roles_permisos_base (rol_id, permiso_id)
    SELECT r.id, p.id FROM roles r CROSS JOIN permisos p
    WHERE r.codigo = 'ADMIN' AND p.codigo = :codigo
    ON CONFLICT DO NOTHING
""")

_DELETES = [
    "DELETE FROM roles_permisos_base WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = :codigo)",
    "DELETE FROM usuarios_permisos_override WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = :codigo)",
    "DELETE FROM permisos WHERE codigo = :codigo",
]

_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "mcp_write_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.String(40), nullable=False, unique=True),
        sa.Column("confirm_token_hash", sa.String(64), nullable=False),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "connection_id", sa.Integer(), sa.ForeignKey("mcp_connections.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("origen", sa.String(10), nullable=False),
        sa.Column("cliente", sa.String(100), nullable=False),
        sa.Column("tool", sa.String(64), nullable=False),
        sa.Column("motivo", sa.String(500), nullable=False),
        sa.Column("limites", sa.JSON(), nullable=True),
        sa.Column("filas", sa.JSON(), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", _TS, nullable=False),
        sa.Column("used_at", _TS, nullable=True),
        sa.Column("resultado", sa.JSON(), nullable=True),
    )
    op.create_index("ix_mcp_write_plans_usuario_id", "mcp_write_plans", ["usuario_id"])

    op.create_table(
        "mcp_write_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_id", sa.String(40), nullable=False),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "connection_id", sa.Integer(), sa.ForeignKey("mcp_connections.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("cliente", sa.String(100), nullable=False),
        sa.Column("tool", sa.String(64), nullable=False),
        sa.Column("accion", sa.String(32), nullable=False),
        sa.Column("objetivo", sa.String(64), nullable=False),
        sa.Column("objetivo_label", sa.String(255), nullable=True),
        sa.Column("antes", sa.JSON(), nullable=True),
        sa.Column("despues", sa.JSON(), nullable=True),
        sa.Column("motivo", sa.String(500), nullable=False),
        sa.Column("resultado", sa.String(12), nullable=False),
        sa.Column("detalle", sa.String(500), nullable=True),
        sa.Column("criteria_version", sa.String(64), nullable=True),
        sa.Column(
            "undo_of_id", sa.Integer(), sa.ForeignKey("mcp_write_actions.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "deshecha_por_id", sa.Integer(), sa.ForeignKey("mcp_write_actions.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("plan_id", "objetivo", "accion", name="uq_mcp_write_actions_plan_objetivo_accion"),
    )
    op.create_index("ix_mcp_write_actions_usuario_id", "mcp_write_actions", ["usuario_id"])
    op.create_index("ix_mcp_write_actions_created_at", "mcp_write_actions", ["created_at"])
    op.create_index("ix_mcp_write_actions_plan_id", "mcp_write_actions", ["plan_id"])

    conn = op.get_bind()
    conn.execute(_INSERT_PERMISO, PERMISO)
    conn.execute(_INSERT_ROL_PERMISO, {"codigo": PERMISO["codigo"]})


def downgrade() -> None:
    conn = op.get_bind()
    for statement in _DELETES:
        conn.execute(sa.text(statement), {"codigo": PERMISO["codigo"]})
    op.drop_index("ix_mcp_write_actions_plan_id", table_name="mcp_write_actions")
    op.drop_index("ix_mcp_write_actions_created_at", table_name="mcp_write_actions")
    op.drop_index("ix_mcp_write_actions_usuario_id", table_name="mcp_write_actions")
    op.drop_table("mcp_write_actions")
    op.drop_index("ix_mcp_write_plans_usuario_id", table_name="mcp_write_plans")
    op.drop_table("mcp_write_plans")
