"""productos_propios (manual SKU and EAN of an ERP product) + ml_publicaciones.editar_producto

Revision ID: 20261127_productos_propios
Revises: 20261126_ml_publicaciones_pausar_perm
Create Date: 2026-10-26

Publicaciones ML T6: our own product is keyed by the ERP `item_id`; only what an operator types is stored (the EAN
defaults to the ERP `codigo`, the SKU to the one its linked publications share). No foreign key to `productos_erp`:
the ERP sync owns that table and must never be blocked by a row here. The edit permission is granted to ADMIN, same
pattern as `20261126_ml_publicaciones_pausar_perm`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261127_productos_propios"
down_revision: Union[str, None] = "20261126_ml_publicaciones_pausar_perm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISO = {
    "codigo": "ml_publicaciones.editar_producto",
    "nombre": "Editar SKU y EAN del producto",
    "descripcion": "Editar el SKU y el EAN de un producto desde Publicaciones ML.",
    "categoria": "ml_ops",
    "orden": 207,
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
        "productos_propios",
        sa.Column("item_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("sku", sa.String(100), nullable=True),
        sa.Column("ean", sa.String(100), nullable=True),
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
    op.drop_table("productos_propios")
