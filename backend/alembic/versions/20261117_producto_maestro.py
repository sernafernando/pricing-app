"""productos_propios as the product master + productos.editar_maestro

Revision ID: 20261117_producto_maestro
Revises: 20261117_producto_categorias_marcas
Create Date: 2026-11-17

abm-productos T4 (delivery 1): `productos_propios` becomes the local product master (one row per ERP `item_id`). The
new columns are overrides of GBP (NULL = follow GBP; nothing is ever written back to the ERP) and the chosen source of
each text (NULL = the default source). No data moves: the table is empty in prod. The edit permission goes to ADMIN,
same pattern as `20261116_producto_specs`; reading needs `productos.ver`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261117_producto_maestro"
down_revision: Union[str, None] = "20261117_producto_categorias_marcas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = (
    ("nombre", sa.String(500)),
    ("codigo_fabricante", sa.String(100)),
    ("marca_id", sa.Integer()),
    ("categoria_id", sa.Integer()),
    ("subcategoria_id", sa.Integer()),
    ("garantia_dias", sa.Integer()),
    ("peso_g", sa.Numeric(12, 2)),
    ("ancho_cm", sa.Numeric(10, 2)),
    ("largo_cm", sa.Numeric(10, 2)),
    ("alto_cm", sa.Numeric(10, 2)),
    ("titulo_web", sa.Text()),
    ("descripcion_web", sa.Text()),
    ("fuente_titulo_ml", sa.String(20)),
    ("fuente_titulo_web", sa.String(20)),
    ("fuente_descripcion_ml", sa.String(20)),
    ("fuente_descripcion_web", sa.String(20)),
)

PERMISO = {
    "codigo": "productos.editar_maestro",
    "nombre": "Editar el maestro de productos",
    "descripcion": "Overridear los datos de GBP de un producto (nombre, EAN, marca, categoría, logística) y elegir "
    "sus títulos y descripciones.",
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


def upgrade() -> None:
    for name, type_ in COLUMNS:
        op.add_column("productos_propios", sa.Column(name, type_, nullable=True))
    conn = op.get_bind()
    conn.execute(_INSERT_PERMISO, PERMISO)
    conn.execute(_INSERT_ROL_PERMISO, {"codigo": PERMISO["codigo"]})


def downgrade() -> None:
    conn = op.get_bind()
    for statement in _DELETES:
        conn.execute(sa.text(statement), {"codigo": PERMISO["codigo"]})
    for name, _ in reversed(COLUMNS):
        op.drop_column("productos_propios", name)
