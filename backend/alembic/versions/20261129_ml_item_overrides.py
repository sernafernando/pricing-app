"""ml_item_overrides (a publication's data overridden locally) + ml_publicaciones.editar_publicacion

Revision ID: 20261129_ml_item_overrides
Revises: 20261128_productos_propios_fuente
Create Date: 2026-10-26

Publicaciones ML T8: editing a publication stores an override per MLA, field by field (NULL follows ML), and never
writes to ML; the original stays in the publication store. No foreign key to `ml_items`: the store's sweeps own that
table and must never be blocked by a row here. The edit permission is granted to ADMIN, same pattern as
`20261127_productos_propios`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20261129_ml_item_overrides"
down_revision: Union[str, None] = "20261128_productos_propios_fuente"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISO = {
    "codigo": "ml_publicaciones.editar_publicacion",
    "nombre": "Editar datos de la publicación",
    "descripcion": "Sobrescribir el título, la descripción, las fotos y los atributos de una publicación desde "
    "Publicaciones ML, sin cambiarla en Mercado Libre.",
    "categoria": "ml_ops",
    "orden": 208,
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
        "ml_item_overrides",
        sa.Column("item_id", sa.Text(), primary_key=True),
        sa.Column("titulo", sa.Text(), nullable=True),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("fotos", JSONB(), nullable=True),
        sa.Column("atributos", JSONB(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    conn = op.get_bind()
    conn.execute(_INSERT_PERMISO, PERMISO)
    conn.execute(_INSERT_ROL_PERMISO, {"codigo": PERMISO["codigo"]})


def downgrade() -> None:
    conn = op.get_bind()
    for statement in _DELETES:
        conn.execute(sa.text(statement), {"codigo": PERMISO["codigo"]})
    op.drop_table("ml_item_overrides")
