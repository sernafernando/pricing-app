"""gestion_full_unidades_caja + depositos/gestor permissions

Revision ID: 20261220_gestion_full_unidades_caja
Revises: 20261219_ml_fulfillment_last_inbound
Create Date: 2026-10-31

Units-per-closed-box master keyed by ERP product (producto_item_id).
Seeds gestion_full.depositos (write caja) and gestion_full.gestor (export /
assign / unlock) for ADMIN; SUPERADMIN short-circuits the catalog.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261220_gestion_full_unidades_caja"
down_revision: Union[str, None] = "20261219_ml_fulfillment_last_inbound"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISOS = [
    (
        "gestion_full.depositos",
        "Gestión Full — unidades por caja",
        "Cargar y editar unidades por caja cerrada para envíos Full.",
        "productos",
        90,
        False,
    ),
    (
        "gestion_full.gestor",
        "Gestión Full — gestor de envíos",
        "Exportar Excel, ajustar qty de export, desbloquear PMs y asignar inbound_id.",
        "productos",
        91,
        False,
    ),
]

ROL_PERMISOS = {"ADMIN": [p[0] for p in PERMISOS]}

_INSERT_PERMISO = sa.text("""
    INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
    VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, :es_critico, NOW())
    ON CONFLICT (codigo) DO NOTHING
""")

_INSERT_ROL_PERMISO = sa.text("""
    INSERT INTO roles_permisos_base (rol_id, permiso_id)
    SELECT r.id, p.id
    FROM roles r
    CROSS JOIN permisos p
    WHERE r.codigo = :rol_codigo
      AND p.codigo = :permiso_codigo
    ON CONFLICT DO NOTHING
""")

_DELETE_ROLES_PERMISOS_BASE = sa.text("""
    DELETE FROM roles_permisos_base
    WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = :codigo)
""")

_DELETE_USUARIOS_PERMISOS_OVERRIDE = sa.text("""
    DELETE FROM usuarios_permisos_override
    WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = :codigo)
""")

_DELETE_PERMISO = sa.text("DELETE FROM permisos WHERE codigo = :codigo")


def upgrade() -> None:
    op.create_table(
        "gestion_full_unidades_caja",
        sa.Column("producto_item_id", sa.Integer(), primary_key=True),
        sa.Column("unidades", sa.Integer(), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["producto_item_id"],
            ["productos_erp.item_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["usuarios.id"],
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("unidades >= 1", name="ck_gestion_full_unidades_caja_ge_1"),
    )
    op.create_index(
        "ix_gestion_full_unidades_caja_updated_by_id",
        "gestion_full_unidades_caja",
        ["updated_by_id"],
    )

    conn = op.get_bind()
    for codigo, nombre, descripcion, categoria, orden, es_critico in PERMISOS:
        conn.execute(
            _INSERT_PERMISO,
            {
                "codigo": codigo,
                "nombre": nombre,
                "descripcion": descripcion,
                "categoria": categoria,
                "orden": orden,
                "es_critico": es_critico,
            },
        )
    for rol, codigos in ROL_PERMISOS.items():
        for codigo in codigos:
            conn.execute(_INSERT_ROL_PERMISO, {"rol_codigo": rol, "permiso_codigo": codigo})


def downgrade() -> None:
    conn = op.get_bind()
    for codigo, *_ in PERMISOS:
        conn.execute(_DELETE_ROLES_PERMISOS_BASE, {"codigo": codigo})
        conn.execute(_DELETE_USUARIOS_PERMISOS_OVERRIDE, {"codigo": codigo})
        conn.execute(_DELETE_PERMISO, {"codigo": codigo})

    op.drop_index(
        "ix_gestion_full_unidades_caja_updated_by_id",
        table_name="gestion_full_unidades_caja",
    )
    op.drop_table("gestion_full_unidades_caja")
