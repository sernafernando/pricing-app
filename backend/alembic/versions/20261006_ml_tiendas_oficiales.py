"""ml_tiendas_oficiales: official-store names editable from the Admin panel

Revision ID: 20261006_ml_tiendas_oficiales
Revises: 20261005_vfactvig_lookup
Create Date: 2026-10-06

Official-store names used to be hardcoded in the frontend (and duplicated in
`items_sin_mla.py`). This table holds them, keyed by MercadoLibre's
`official_store_id`, seeded with the four stores that were hardcoded so
nothing changes visually after deploy. Also seeds the
`admin.tiendas_oficiales` permission (ADMIN; SUPERADMIN short-circuits the
catalog, anyone else through the per-user overrides screen).

A brand-new table needs no `lock_timeout`: nothing else references it yet.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261006_ml_tiendas_oficiales"
down_revision: Union[str, None] = "20261005_vfactvig_lookup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "ml_tiendas_oficiales"

# (store_id, nombre, orden): order of the old `TIENDAS_OFICIALES_ORDER`.
# `clave` is the code-facing slug (see `MlTiendaOficial.clave`); only TP-Link
# has one today (the TP-Link dashboard and its metrics job resolve their store
# ids from it).
SEED = [
    (57997, "Gauss", 0, None),
    (2645, "TP-Link", 1, "tplink"),
    (144, "Forza/Verbatim", 2, None),
    (191942, "Multi-marca", 3, None),
]

CODIGO = "admin.tiendas_oficiales"
PERMISO_NOMBRE = "Administrar tiendas oficiales"
PERMISO_DESCRIPCION = (
    "Crear, renombrar, reordenar y desactivar los nombres de las tiendas oficiales de ML (panel Admin)"
)
PERMISO_CATEGORIA = "configuracion"
PERMISO_ORDEN = 90

_INSERT_STORE = sa.text(
    f"INSERT INTO {TABLE} (store_id, nombre, orden, clave) VALUES (:store_id, :nombre, :orden, :clave) ON CONFLICT (store_id) DO NOTHING"
)

_INSERT_PERMISO = sa.text("""
    INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
    VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, false, NOW())
    ON CONFLICT (codigo) DO NOTHING
""")

_INSERT_ROL_PERMISO = sa.text("""
    INSERT INTO roles_permisos_base (rol_id, permiso_id)
    SELECT r.id, p.id
    FROM roles r
    CROSS JOIN permisos p
    WHERE r.codigo = 'ADMIN'
      AND p.codigo = :codigo
    ON CONFLICT DO NOTHING
""")


def upgrade() -> None:
    conn = op.get_bind()
    if not sa.inspect(conn).has_table(TABLE):
        op.create_table(
            TABLE,
            sa.Column("store_id", sa.BigInteger(), primary_key=True, autoincrement=False),
            sa.Column("nombre", sa.String(100), nullable=False),
            sa.Column("clave", sa.String(50), nullable=True),
            sa.Column("orden", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_ml_tiendas_oficiales_clave", TABLE, ["clave"])
    for store_id, nombre, orden, clave in SEED:
        conn.execute(_INSERT_STORE, {"store_id": store_id, "nombre": nombre, "orden": orden, "clave": clave})

    conn.execute(
        _INSERT_PERMISO,
        {
            "codigo": CODIGO,
            "nombre": PERMISO_NOMBRE,
            "descripcion": PERMISO_DESCRIPCION,
            "categoria": PERMISO_CATEGORIA,
            "orden": PERMISO_ORDEN,
        },
    )
    conn.execute(_INSERT_ROL_PERMISO, {"codigo": CODIGO})


def downgrade() -> None:
    conn = op.get_bind()
    params = {"codigo": CODIGO}
    sub = "(SELECT id FROM permisos WHERE codigo = :codigo)"
    conn.execute(sa.text(f"DELETE FROM roles_permisos_base WHERE permiso_id IN {sub}"), params)
    conn.execute(sa.text(f"DELETE FROM usuarios_permisos_override WHERE permiso_id IN {sub}"), params)
    conn.execute(sa.text("DELETE FROM permisos WHERE codigo = :codigo"), params)
    op.drop_table(TABLE)
