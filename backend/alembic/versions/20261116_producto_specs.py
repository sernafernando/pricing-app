"""producto_specs + producto_spec_valores + productos.editar_specs

Revision ID: 20261116_producto_specs
Revises: 20261114_hay_mejores_excluido
Create Date: 2026-11-16

abm-specs-productos T1: the technical specs of notebooks and PCs, one row per ERP `item_id` with one typed column per
field (numbers in a fixed unit, categorical values from a normalized list), each indexed so the later Publicaciones ML
view can filter and sort without parsing JSON. `origenes` remembers each field's source. No foreign key to
`productos_erp` (the ERP sync owns it). The normalized lists of the closed-vocabulary fields are seeded here; the
pre-load (worker handler `producto_specs.preload`) fills the rows. The edit permission goes to ADMIN, same pattern as
`20261127_productos_propios`; reading needs `productos.ver`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261116_producto_specs"
down_revision: Union[str, None] = "20261114_hay_mejores_excluido"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VALOR = 120

NUMERIC_COLUMNS = (
    ("ram_gb", sa.Integer()),
    ("pantalla_pulgadas", sa.Numeric(4, 1)),
    ("pantalla_hz", sa.Integer()),
    ("disco_gb", sa.Integer()),
    ("gpu_vram_gb", sa.Integer()),
    ("fuente_watts", sa.Integer()),
)
CATEGORICAL_COLUMNS = (
    "cpu_marca",
    "cpu_linea",
    "cpu_modelo",
    "ram_tipo",
    "pantalla_resolucion",
    "pantalla_panel",
    "disco_tipo",
    "so_nombre",
    "so_edicion",
    "gpu_tipo",
    "gpu_marca",
    "gpu_modelo",
    "gabinete_marca",
    "gabinete_modelo",
    "fuente_marca",
    "fuente_modelo",
    "mother_marca",
    "mother_modelo",
    "refrigeracion_tipo",
    "refrigeracion_marca",
    "refrigeracion_modelo",
)
INDEXED = ("tipo", *(name for name, _ in NUMERIC_COLUMNS), *CATEGORICAL_COLUMNS)

SEED = {
    "cpu_marca": ("Intel", "AMD", "Apple", "MediaTek", "Qualcomm"),
    "ram_tipo": ("DDR3", "DDR4", "DDR5", "LPDDR4", "LPDDR4X", "LPDDR5", "LPDDR5X"),
    "pantalla_panel": ("IPS", "OLED", "VA", "TN", "LED", "LCD"),
    "disco_tipo": ("SSD", "HDD", "Híbrido"),
    "so_nombre": ("Windows", "FreeDOS", "macOS", "Linux", "ChromeOS", "Sin sistema operativo"),
    "so_edicion": ("Home", "Pro", "Education", "Enterprise"),
    "gpu_tipo": ("Integrada", "Dedicada"),
    "gpu_marca": ("NVIDIA", "AMD", "Intel", "Apple"),
    "refrigeracion_tipo": ("Aire", "Líquida"),
}

PERMISO = {
    "codigo": "productos.editar_specs",
    "nombre": "Editar specs de productos",
    "descripcion": "Editar las especificaciones técnicas de notebooks y PCs y agregar valores a sus listas.",
    "categoria": "productos",
    "orden": 85,
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
        "producto_specs",
        sa.Column("item_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        *(sa.Column(name, type_) for name, type_ in NUMERIC_COLUMNS),
        *(sa.Column(name, sa.String(VALOR)) for name in CATEGORICAL_COLUMNS),
        sa.Column("origenes", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("fuente_mla", sa.Text()),
        sa.Column("precargado_at", sa.DateTime(timezone=True)),
        sa.Column("updated_by", sa.Integer()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("tipo IN ('notebook', 'pc')", name="ck_producto_specs_tipo"),
    )
    for column in INDEXED:
        op.create_index(f"ix_producto_specs_{column}", "producto_specs", [column])

    op.create_table(
        "producto_spec_valores",
        sa.Column("campo", sa.String(40), primary_key=True),
        sa.Column("clave", sa.String(VALOR), primary_key=True),
        sa.Column("valor", sa.String(VALOR), nullable=False),
        sa.Column("created_by", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    conn = op.get_bind()
    for campo, valores in SEED.items():
        for valor in valores:
            conn.execute(
                sa.text(
                    "INSERT INTO producto_spec_valores (campo, clave, valor) VALUES (:campo, :clave, :valor) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"campo": campo, "clave": valor.casefold(), "valor": valor},
            )

    conn.execute(_INSERT_PERMISO, PERMISO)
    conn.execute(_INSERT_ROL_PERMISO, {"codigo": PERMISO["codigo"]})


def downgrade() -> None:
    conn = op.get_bind()
    for statement in _DELETES:
        conn.execute(sa.text(statement), {"codigo": PERMISO["codigo"]})
    op.drop_table("producto_spec_valores")
    op.drop_table("producto_specs")
