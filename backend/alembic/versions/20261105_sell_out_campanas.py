"""sell out: campaigns, their product groups and the sell_out.* permissions

Revision ID: 20261105_sell_out_campanas
Revises: 20261104_pedido_lineas_facturadas
Create Date: 2026-11-04

Sell in / sell out, T6. New tables only; legacy offsets are untouched (a
campaign reuses `offset_grupos` as its product groups, read only, and a group
in use by a campaign cannot be deleted).

Reading campaigns (`sell_out.ver`) and loading, editing or voiding them
(`sell_out.gestionar`) are separate permissions, granted to ADMIN only like
`20261025_sell_in_permisos`. Currency defaults to USD; a USD campaign's FX
mode (`tc_modo`: al_cobro, fijo, dia_venta) is documented in
`app.models.sell_out`. `updated_at` is kept by its own BEFORE UPDATE
trigger function, independent of the sell-in one.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_sell_out_campanas"
down_revision: Union[str, None] = "20261104_pedido_lineas_facturadas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (codigo, nombre, descripcion, categoria, orden, es_critico)
PERMISOS = [
    (
        "sell_out.ver",
        "Ver campañas de sell out",
        "Ver las campañas de sell out (crédito por unidad vendida que suma a la ganancia).",
        "productos",
        82,
        False,
    ),
    (
        "sell_out.gestionar",
        "Gestionar campañas de sell out",
        "Cargar, editar y anular campañas de sell out. Suman ganancia a las ventas de sus grupos.",
        "productos",
        83,
        False,
    ),
]

_INSERT_PERMISO = sa.text("""
    INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
    VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, :es_critico, NOW())
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

_CREATE_UPDATED_AT_FUNCTION = """
CREATE OR REPLACE FUNCTION sell_out_set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

_CREATE_UPDATED_AT_TRIGGER = """
CREATE TRIGGER sell_out_campanas_updated_at
BEFORE UPDATE ON sell_out_campanas
FOR EACH ROW EXECUTE FUNCTION sell_out_set_updated_at()
"""


def upgrade() -> None:
    op.create_table(
        "sell_out_campanas",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("fecha_desde", sa.Date(), nullable=False),
        sa.Column("fecha_hasta", sa.Date(), nullable=False),
        sa.Column("tipo", sa.String(16), nullable=False),
        sa.Column("monto_unit", sa.Numeric(18, 2), nullable=True),
        sa.Column("porcentaje", sa.Numeric(7, 4), nullable=True),
        sa.Column("base_porcentaje", sa.String(16), nullable=False, server_default="costo"),
        sa.Column("moneda", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("tc_modo", sa.String(16), nullable=True),
        sa.Column("tipo_cambio", sa.Numeric(18, 6), nullable=True),
        sa.Column("tc_definido_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tope_unidades", sa.Integer(), nullable=True),
        sa.Column("tope_monto", sa.Numeric(18, 2), nullable=True),
        sa.Column("acumulable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("estado", sa.String(16), nullable=False, server_default="activa"),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("tipo IN ('por_unidad', 'porcentaje')", name="ck_sell_out_campanas_tipo"),
        sa.CheckConstraint(
            "(tipo = 'por_unidad' AND monto_unit IS NOT NULL AND monto_unit > 0 AND porcentaje IS NULL) OR "
            "(tipo = 'porcentaje' AND porcentaje IS NOT NULL AND porcentaje > 0 AND porcentaje <= 100 "
            "AND monto_unit IS NULL)",
            name="ck_sell_out_campanas_monto_segun_tipo",
        ),
        sa.CheckConstraint("base_porcentaje IN ('costo', 'precio_neto')", name="ck_sell_out_campanas_base_porcentaje"),
        sa.CheckConstraint("fecha_hasta >= fecha_desde", name="ck_sell_out_campanas_fechas"),
        sa.CheckConstraint("moneda IN ('ARS', 'USD')", name="ck_sell_out_campanas_moneda"),
        sa.CheckConstraint(
            "(moneda = 'ARS' AND tc_modo IS NULL AND tipo_cambio IS NULL) OR "
            "(moneda = 'USD' AND tc_modo IS NOT NULL AND ("
            "(tc_modo = 'fijo' AND tipo_cambio IS NOT NULL) OR "
            "(tc_modo = 'dia_venta' AND tipo_cambio IS NULL) OR "
            "tc_modo = 'al_cobro'))",
            name="ck_sell_out_campanas_tc_modo",
        ),
        sa.CheckConstraint(
            "(tc_definido_en IS NOT NULL) = (COALESCE(tc_modo, '') = 'al_cobro' AND tipo_cambio IS NOT NULL)",
            name="ck_sell_out_campanas_tc_definido_en",
        ),
        sa.CheckConstraint("tipo_cambio IS NULL OR tipo_cambio > 0", name="ck_sell_out_campanas_tc_positivo"),
        sa.CheckConstraint("tope_unidades IS NULL OR tope_unidades > 0", name="ck_sell_out_campanas_tope_unidades"),
        sa.CheckConstraint("tope_monto IS NULL OR tope_monto > 0", name="ck_sell_out_campanas_tope_monto"),
        sa.CheckConstraint("estado IN ('activa', 'anulada')", name="ck_sell_out_campanas_estado"),
    )
    op.create_table(
        "sell_out_campana_grupos",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "campana_id", sa.BigInteger(), sa.ForeignKey("sell_out_campanas.id", ondelete="CASCADE"), nullable=False
        ),
        # Same name as app.models.sell_out.FK_SELL_OUT_CAMPANA_GRUPOS_GRUPO_ID (the group-delete endpoint
        # matches it); the schema-vs-ORM test guards that the two stay equal.
        sa.Column(
            "grupo_id",
            sa.Integer(),
            sa.ForeignKey("offset_grupos.id", ondelete="RESTRICT", name="fk_sell_out_campana_grupos_grupo_id"),
            nullable=False,
        ),
        sa.UniqueConstraint("campana_id", "grupo_id", name="uq_sell_out_campana_grupos_campana_grupo"),
    )
    op.create_index("ix_sell_out_campana_grupos_grupo_id", "sell_out_campana_grupos", ["grupo_id"])
    op.execute(_CREATE_UPDATED_AT_FUNCTION)
    op.execute(_CREATE_UPDATED_AT_TRIGGER)

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
        conn.execute(_INSERT_ROL_PERMISO, {"codigo": codigo})


def downgrade() -> None:
    conn = op.get_bind()
    for codigo, *_ in PERMISOS:
        for statement in _DELETES:
            conn.execute(sa.text(statement), {"codigo": codigo})
    op.execute("DROP TRIGGER IF EXISTS sell_out_campanas_updated_at ON sell_out_campanas")
    op.execute("DROP FUNCTION IF EXISTS sell_out_set_updated_at()")
    op.drop_table("sell_out_campana_grupos")
    op.drop_table("sell_out_campanas")
