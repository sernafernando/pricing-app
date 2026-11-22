"""Costo SI: suspicious purchase prices held out of the average until reviewed (owner L29)

Revision ID: 20261129_costo_si_compras_sospechosas
Revises: 20261128_costo_si_t4_recalculo
Create Date: 2026-11-22

A purchase whose net unit price, in the product's cost currency, is below 1/10 or above 10x the costo SI right
before it (or the list cost when there is none) is held out of the average. The recompute lists it in
`costo_si_compras_sospechosas`, where a reviewer accepts it or keeps it excluded.

The migration does four things:

1. Creates the table.
2. Creates its trigger: a change of `estado` requeues the product from the invoice date. The SQL is a frozen copy of
   `app.services.costo_si.sospechas.UPGRADE_SQL` at this revision.
3. Seeds `costo_si.revisar`, the permission to decide on a suspicious purchase, granted to ADMIN; SUPERADMIN has
   every permission. Reading the list needs `sell_in.ver`, like the rest of costo SI.
4. Queues for a whole-history recompute the products whose stored history already has a purchase out of range
   against the average stored right before it. On prod (read-only count on 2026-11-22, purchases since 10-01) that
   is item 23 alone, invoice 00128199. The first purchase of a product without an average (where the reference
   would be the list cost) is left to the next daily requeue: none was out of range then.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261129_costo_si_compras_sospechosas"
down_revision: Union[str, None] = "20261128_costo_si_t4_recalculo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLA = "costo_si_compras_sospechosas"

# Frozen copy of `app.services.costo_si.sospechas.UPGRADE_SQL` / `DOWNGRADE_SQL` at this revision.
UPGRADE_SQL = [
    """
CREATE OR REPLACE FUNCTION costo_si_trg_sospechosa() RETURNS TRIGGER AS $t$
BEGIN
    PERFORM costo_si_encolar(NEW.item_id, NEW.fecha);
    RETURN NULL;
END
$t$ LANGUAGE plpgsql
""",
    "CREATE TRIGGER costo_si_sospechosa AFTER UPDATE OF estado ON costo_si_compras_sospechosas FOR EACH ROW "
    "WHEN (OLD.estado IS DISTINCT FROM NEW.estado) EXECUTE FUNCTION costo_si_trg_sospechosa()",
]

DOWNGRADE_SQL = [
    "DROP TRIGGER IF EXISTS costo_si_sospechosa ON costo_si_compras_sospechosas",
    "DROP FUNCTION IF EXISTS costo_si_trg_sospechosa()",
]

# The products whose stored history has a purchase out of [1/10, 10x] the average stored right before it.
ENCOLAR_SQL = """
SELECT costo_si_encolar(x.item_id, NULL)
FROM (
    SELECT DISTINCT s.item_id
    FROM (
        SELECT item_id, tipo, costo_neto_usd,
               lag(promedio_usd) OVER (PARTITION BY item_id ORDER BY orden) AS previo
        FROM costo_si_pasos
    ) s
    WHERE s.tipo = 'compra' AND s.previo > 0
      AND (s.costo_neto_usd * 10 < s.previo OR s.costo_neto_usd > s.previo * 10)
) x
"""

# (codigo, nombre, descripcion, categoria, orden, es_critico)
PERMISOS = [
    (
        "costo_si.revisar",
        "Revisar compras con precio sospechoso",
        "Aceptar o mantener excluida una compra cuyo precio es menor a 1/10 o mayor a 10 veces el costo SI. "
        "Aceptarla la hace entrar al costo promedio y recalcula la historia del producto.",
        "productos",
        84,
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
        TABLA,
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("ct_transaction", sa.BigInteger(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("precio", sa.Numeric(18, 5), nullable=False),
        sa.Column("moneda", sa.String(3), nullable=False),
        sa.Column("referencia", sa.Numeric(18, 5), nullable=False),
        sa.Column("fuente_ref", sa.String(8), nullable=False),
        sa.Column("ratio", sa.Numeric(18, 6), nullable=False),
        sa.Column("estado", sa.String(10), nullable=False, server_default=sa.text("'pendiente'")),
        sa.Column("detectada_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revisado_por", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True),
        sa.Column("revisado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("nota", sa.Text(), nullable=True),
        sa.UniqueConstraint("item_id", "ct_transaction", name="uq_costo_si_compras_sospechosas_item_ct"),
        sa.CheckConstraint(
            "estado IN ('pendiente', 'aceptada', 'excluida')", name="ck_costo_si_compras_sospechosas_estado"
        ),
    )
    op.create_index("ix_costo_si_compras_sospechosas_estado_fecha", TABLA, ["estado", "fecha"])
    op.create_index("ix_costo_si_compras_sospechosas_revisado_por", TABLA, ["revisado_por"])
    conn = op.get_bind()
    for statement in UPGRADE_SQL:
        conn.execute(sa.text(statement))
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
    conn.execute(sa.text(ENCOLAR_SQL))


def downgrade() -> None:
    conn = op.get_bind()
    for codigo, *_ in PERMISOS:
        conn.execute(_DELETE_ROLES_PERMISOS_BASE, {"codigo": codigo})
        conn.execute(_DELETE_USUARIOS_PERMISOS_OVERRIDE, {"codigo": codigo})
        conn.execute(_DELETE_PERMISO, {"codigo": codigo})
    for statement in DOWNGRADE_SQL:
        conn.execute(sa.text(statement))
    op.drop_table(TABLA)
    # Products whose history now holds an 'excluido' step: requeue them so they average every purchase again.
    conn.execute(
        sa.text(
            "SELECT costo_si_encolar(item_id, NULL) FROM (SELECT DISTINCT item_id FROM costo_si_pasos WHERE tipo = 'excluido') x"
        )
    )
