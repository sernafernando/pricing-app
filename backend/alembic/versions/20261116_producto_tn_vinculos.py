"""producto_tn_vinculos + tienda_nube_producto_textos + productos.editar_maestro

Revision ID: 20261116_producto_tn_vinculos
Revises: 20261117_producto_maestro
Create Date: 2026-11-16

abm-productos T6 (S12): `producto_tn_vinculos` holds the links between an ERP product and its Tienda Nube product set
by hand (NULL = explicitly not linked); the TN catalog sync applies them after its SKU match, so a manual link always
wins. `tienda_nube_producto_textos` stores each TN product's name and description (HTML and plain text), filled by the
same sync pass. No foreign keys: the ERP and TN syncs own those tables.

`productos.editar_maestro` (ADMIN) gates the product master's general section, the TN link included. The product
master migration (T4) seeds the same permission, so the seed here does nothing when it already exists, and the
downgrade leaves the permission in place for that migration to own.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261116_producto_tn_vinculos"
down_revision: Union[str, None] = "20261117_producto_maestro"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISO = {
    "codigo": "productos.editar_maestro",
    "nombre": "Editar maestro de productos",
    "descripcion": "Editar los datos generales de un producto en el ABM de productos, incluido su vínculo con Tienda Nube.",
    "categoria": "productos",
    "orden": 84,
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


def upgrade() -> None:
    op.create_table(
        "producto_tn_vinculos",
        sa.Column("item_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("tn_product_id", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tn_product_id", name="uq_producto_tn_vinculos_tn_product_id"),
    )
    op.create_table(
        "tienda_nube_producto_textos",
        sa.Column("product_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("nombre", sa.String(500), nullable=True),
        sa.Column("descripcion_html", sa.Text(), nullable=True),
        sa.Column("descripcion_texto", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    conn = op.get_bind()
    conn.execute(_INSERT_PERMISO, PERMISO)
    conn.execute(_INSERT_ROL_PERMISO, {"codigo": PERMISO["codigo"]})


def downgrade() -> None:
    op.drop_table("tienda_nube_producto_textos")
    op.drop_table("producto_tn_vinculos")
