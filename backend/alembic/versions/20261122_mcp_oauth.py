"""MCP server: OAuth connections, pending authorizations, opaque tokens, tool-call log + mcp.conectar

Revision ID: 20261122_mcp_oauth
Revises: 20261121_ml_publicaciones_auditoria_stock_perm
Create Date: 2026-11-18

ChatGPT (and later other AI clients) connect to /api/mcp through OAuth 2.1 with the existing login. Tokens are
opaque and stored hashed. `mcp.conectar` lets a user approve such a connection; critical because it hands the
user's data to an outside app. Granted to ADMIN only; SUPERADMIN gets it implicitly, anyone else by override.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261122_mcp_oauth"
down_revision: Union[str, None] = "20261121_ml_publicaciones_auditoria_stock_perm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISO = {
    "codigo": "mcp.conectar",
    "nombre": "Conectar ChatGPT (MCP)",
    "descripcion": "Autorizar a ChatGPT u otro cliente de IA a consultar pricing (solo lectura) con los permisos propios.",
    "categoria": "administracion",
    "orden": 70,
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
        "mcp_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(512), nullable=False),
        sa.Column("client_name", sa.String(100), nullable=False),
        sa.Column("scope", sa.String(255), nullable=False),
        sa.Column("resource", sa.String(512), nullable=False),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", _TS, nullable=True),
        sa.Column("revoked_at", _TS, nullable=True),
        sa.Column("revoked_by_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_mcp_connections_usuario_id", "mcp_connections", ["usuario_id"])

    op.create_table(
        "mcp_oauth_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("client_id", sa.String(512), nullable=False),
        sa.Column("redirect_uri", sa.String(512), nullable=False),
        sa.Column("state", sa.String(512), nullable=True),
        sa.Column("code_challenge", sa.String(128), nullable=False),
        sa.Column("scope", sa.String(255), nullable=False),
        sa.Column("resource", sa.String(512), nullable=False),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", _TS, nullable=False),
        sa.Column("decided_at", _TS, nullable=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=True),
        sa.Column("code_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("code_expires_at", _TS, nullable=True),
        sa.Column("used_at", _TS, nullable=True),
        sa.Column(
            "connection_id", sa.Integer(), sa.ForeignKey("mcp_connections.id", ondelete="CASCADE"), nullable=True
        ),
    )
    op.create_index("ix_mcp_oauth_requests_expires_at", "mcp_oauth_requests", ["expires_at"])

    op.create_table(
        "mcp_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id", sa.Integer(), sa.ForeignKey("mcp_connections.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", _TS, nullable=False),
        sa.Column("rotated_at", _TS, nullable=True),
        sa.Column("revoked_at", _TS, nullable=True),
    )
    op.create_index("ix_mcp_tokens_connection_id", "mcp_tokens", ["connection_id"])

    op.create_table(
        "mcp_tool_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "connection_id", sa.Integer(), sa.ForeignKey("mcp_connections.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("tool", sa.String(64), nullable=False),
        sa.Column("args_summary", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("result_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mcp_tool_calls_usuario_id", "mcp_tool_calls", ["usuario_id"])
    op.create_index("ix_mcp_tool_calls_created_at", "mcp_tool_calls", ["created_at"])

    conn = op.get_bind()
    conn.execute(_INSERT_PERMISO, PERMISO)
    conn.execute(_INSERT_ROL_PERMISO, {"codigo": PERMISO["codigo"]})


def downgrade() -> None:
    conn = op.get_bind()
    for statement in _DELETES:
        conn.execute(sa.text(statement), {"codigo": PERMISO["codigo"]})
    op.drop_table("mcp_tool_calls")
    op.drop_table("mcp_tokens")
    op.drop_table("mcp_oauth_requests")
    op.drop_table("mcp_connections")
