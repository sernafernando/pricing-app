"""producto_categorias + producto_subcategorias + producto_marcas + productos.editar_categorias

Revision ID: 20261117_producto_categorias_marcas
Revises: 20261116_producto_specs
Create Date: 2026-11-17

abm-productos delivery 2+3 (S11, L10): the local categories, subcategories and brands masters, seeded from GBP's
`tb_category`, `tb_subcategory` and `tb_brand` with the same ids (the ERP master sync re-runs the same seed for new
ids). `nombre` NULL follows GBP's name; own rows take ids from 1,000,000 up. Categories and subcategories may link to a
Tienda Nube category. No foreign key to the GBP mirror tables (their sync owns them). The edit permission goes to ADMIN,
same pattern as `20261116_producto_specs`; reading needs `productos.ver`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261117_producto_categorias_marcas"
down_revision: Union[str, None] = "20261116_producto_specs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Same statements as `app.services.producto_categorias.SEED_SQL` (a test pins them equal): insert only missing ids.
SEED_SQL = (
    "INSERT INTO producto_categorias (id, activa, propia) "
    "SELECT DISTINCT cat_id, true, false FROM tb_category WHERE cat_id IS NOT NULL "
    "ON CONFLICT (id) DO NOTHING",
    "INSERT INTO producto_subcategorias (id, categoria_id, activa, propia) "
    "SELECT s.subcat_id, MIN(s.cat_id), true, false FROM tb_subcategory s "
    "JOIN producto_categorias c ON c.id = s.cat_id WHERE s.subcat_id IS NOT NULL GROUP BY s.subcat_id "
    "ON CONFLICT (id) DO NOTHING",
    "INSERT INTO producto_marcas (id, activa, propia) "
    "SELECT DISTINCT brand_id, true, false FROM tb_brand WHERE brand_id IS NOT NULL "
    "ON CONFLICT (id) DO NOTHING",
)

PERMISO = {
    "codigo": "productos.editar_categorias",
    "nombre": "Editar categorías y marcas",
    "descripcion": "Crear, renombrar y desactivar categorías, subcategorías y marcas, y vincularlas con Tienda Nube.",
    "categoria": "productos",
    "orden": 86,
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


def _common() -> list:
    return [
        sa.Column("nombre", sa.String(255)),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("propia", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("updated_by", sa.Integer()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        "producto_categorias",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("tn_category_id", sa.Integer()),
        *_common(),
    )
    op.create_table(
        "producto_subcategorias",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("categoria_id", sa.Integer(), sa.ForeignKey("producto_categorias.id"), nullable=False),
        sa.Column("tn_category_id", sa.Integer()),
        *_common(),
    )
    op.create_index("ix_producto_subcategorias_categoria_id", "producto_subcategorias", ["categoria_id"])
    op.create_table(
        "producto_marcas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        *_common(),
    )

    conn = op.get_bind()
    for statement in SEED_SQL:
        conn.execute(sa.text(statement))
    conn.execute(_INSERT_PERMISO, PERMISO)
    conn.execute(_INSERT_ROL_PERMISO, {"codigo": PERMISO["codigo"]})


def downgrade() -> None:
    conn = op.get_bind()
    for statement in _DELETES:
        conn.execute(sa.text(statement), {"codigo": PERMISO["codigo"]})
    op.drop_table("producto_marcas")
    op.drop_table("producto_subcategorias")
    op.drop_table("producto_categorias")
