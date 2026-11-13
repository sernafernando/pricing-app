"""marcas_visibles_excepciones: brands kept visible without stock (Admin panel)

Revision ID: 20261114_marcas_visibles_excepciones
Revises: 20261113_permiso_mejores_ofertas_pms
Create Date: 2026-11-14

A brand with no product in stock is hidden from every brand filter and selector
unless an admin lists it here (`app.services.marcas_visibles`). One row per brand:
the name, who added it and when. Also seeds the `admin.marcas_visibles` permission
(ADMIN; SUPERADMIN short-circuits the catalog), like `admin.tiendas_oficiales`.

A brand-new table needs no `lock_timeout`: nothing else references it yet.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261114_marcas_visibles_excepciones"
down_revision: Union[str, None] = "20261113_permiso_mejores_ofertas_pms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "marcas_visibles_excepciones"

CODIGO = "admin.marcas_visibles"
PERMISO_NOMBRE = "Administrar marcas sin stock visibles"
PERMISO_DESCRIPCION = "Elegir qué marcas sin stock se siguen mostrando en filtros y selectores (panel Admin)"
PERMISO_CATEGORIA = "configuracion"
PERMISO_ORDEN = 91

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
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("marca", sa.String(100), nullable=False),
            sa.Column("creado_por_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("marca", name="uq_marcas_visibles_excepciones_marca"),
        )
        op.create_index("ix_marcas_visibles_excepciones_creado_por_id", TABLE, ["creado_por_id"])
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
