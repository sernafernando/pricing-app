"""Publicaciones ML column layouts and presets + ml_publicaciones.presets_compartidos

Revision ID: 20261123_ml_publicaciones_presets
Revises: 20261122_mcp_oauth
Create Date: 2026-11-18

- `ml_publicaciones_layouts`: one row per user and view with the column layout (visibility + order, NULL = the
  view's defaults) and the remembered preset (ON DELETE SET NULL).
- `ml_publicaciones_presets`: named column + URL param presets; `usuario_id` NULL = shared. Names unique
  case-insensitively per owner and view (personal) and per view (shared), by two partial unique indexes.
- Permission `ml_publicaciones.presets_compartidos` (create/edit/delete shared presets), granted to ADMIN;
  SUPERADMIN gets it implicitly, anyone else through a per-user override.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261123_ml_publicaciones_presets"
down_revision: Union[str, None] = "20261122_mcp_oauth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISO = {
    "codigo": "ml_publicaciones.presets_compartidos",
    "nombre": "Gestionar presets compartidos",
    "descripcion": "Crear, editar y borrar los presets de columnas y filtros compartidos de Publicaciones ML.",
    "categoria": "ml_ops",
    "orden": 210,
}

_INSERT_PERMISO = sa.text("""
    INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
    VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, false, NOW())
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


def upgrade() -> None:
    op.create_table(
        "ml_publicaciones_presets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=True),
        sa.Column("vista", sa.String(20), nullable=False),
        sa.Column("nombre", sa.String(60), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "uq_ml_publicaciones_presets_personal_nombre",
        "ml_publicaciones_presets",
        ["usuario_id", "vista", sa.text("lower(nombre)")],
        unique=True,
        postgresql_where=sa.text("usuario_id IS NOT NULL"),
    )
    op.create_index(
        "uq_ml_publicaciones_presets_compartido_nombre",
        "ml_publicaciones_presets",
        ["vista", sa.text("lower(nombre)")],
        unique=True,
        postgresql_where=sa.text("usuario_id IS NULL"),
    )
    op.create_index("ix_ml_publicaciones_presets_vista_usuario", "ml_publicaciones_presets", ["vista", "usuario_id"])

    op.create_table(
        "ml_publicaciones_layouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vista", sa.String(20), nullable=False),
        sa.Column("columns", postgresql.JSONB(), nullable=True),
        sa.Column(
            "preset_activo_id",
            sa.Integer(),
            sa.ForeignKey("ml_publicaciones_presets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("usuario_id", "vista", name="uq_ml_publicaciones_layouts_usuario_vista"),
    )
    op.create_index("ix_ml_publicaciones_layouts_preset_activo_id", "ml_publicaciones_layouts", ["preset_activo_id"])

    conn = op.get_bind()
    conn.execute(_INSERT_PERMISO, PERMISO)
    conn.execute(_INSERT_ROL_PERMISO, {"codigo": PERMISO["codigo"]})


def downgrade() -> None:
    conn = op.get_bind()
    for statement in _DELETES:
        conn.execute(sa.text(statement), {"codigo": PERMISO["codigo"]})
    op.drop_index("ix_ml_publicaciones_layouts_preset_activo_id", table_name="ml_publicaciones_layouts")
    op.drop_table("ml_publicaciones_layouts")
    op.drop_index("ix_ml_publicaciones_presets_vista_usuario", table_name="ml_publicaciones_presets")
    op.drop_index("uq_ml_publicaciones_presets_compartido_nombre", table_name="ml_publicaciones_presets")
    op.drop_index("uq_ml_publicaciones_presets_personal_nombre", table_name="ml_publicaciones_presets")
    op.drop_table("ml_publicaciones_presets")
