"""ventas por fuera PDF lines: manual fixes that survive re-uploads, remembered mappings, "sin producto" re-resolved

Revision ID: 20261120_vpf_operaciones_overrides
Revises: 20261122_producto_stock_diario
Create Date: 2026-11-18

Feature vpf-operaciones (S3, S3a-S3c, S4-L2):

- `ventas_fuera_operacion_lineas`: + `precio_costo_pdf` (the PDF's cost, backfilled = `precio_costo`; a manual cost
  replaces `precio_costo`), + `item_origen` ('codigo' | 'prefijo' | 'mapeo' | 'manual'; NULL = sin producto),
  + `override_estado` (NULL | 'aplicado' | 'revisar').
- `ventas_fuera_linea_overrides`: the manual fixes (product and / or cost per unit) keyed by the document's natural
  key + `renglon`, apart from the PDF rows a re-upload replaces (owner L2: "se perdía la data que cargaban ahí").
- `ventas_fuera_codigo_mapeos`: a product remembered for a PDF code (or article text of a line without code).
- data: the lines already loaded with a product get `item_origen` 'codigo'; the lines without one are resolved again
  with the load's rules (`app.services.ventas_fuera_pdf.resolucion`, mirrored in `RESOLVER_SQL`): the code trimmed on
  both sides against `productos_erp.codigo` (S3a: prod codes padded with trailing spaces), then
  `tb_item.item_code`; a line without code by the FIRST whitespace token of its article, trimmed and case-insensitive,
  against `productos_erp.codigo`, then `tb_item.item_code` (S3b). More than one product = ambiguous = still sin
  producto. The table of mappings is new and empty, so that step of the load has nothing to apply here. The UPDATE
  fires T4's `trg_sell_dirty_pdf_update` (20261119_vpf_offsets_sell_pdf): every line that gets a product is queued
  for offsets and sell in / sell out. The number of lines fixed is logged.

Tables are small (hundreds of PDF lines), so everything runs in the migration's single transaction. Downgrade puts
the PDF cost back on manually costed lines, clears the products that only the dropped tables justified ('manual',
'mapeo') and drops the columns and tables; the products found by code or prefix stay (they are right).
"""

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261120_vpf_operaciones_overrides"
down_revision: Union[str, None] = "20261122_producto_stock_diario"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LINEAS = "ventas_fuera_operacion_lineas"
MONTO = sa.Numeric(18, 2)
log = logging.getLogger("alembic.runtime.migration")

# The automatic resolution of `resolucion.resolver` for the lines without product: a unique productos_erp match, else
# a unique tb_item match; codes trimmed (btrim) on both sides; a line without code by the first whitespace token of
# its article, upper-cased on both sides. Ambiguous (more than one item) = unresolved.
RESOLVER_SQL = r"""
WITH candidatas AS (
    SELECT l.id,
           NULLIF(btrim(l.codigo), '') AS codigo,
           upper(substring(l.articulo from '^\s*(\S+)')) AS token
    FROM ventas_fuera_operacion_lineas AS l
    WHERE l.item_id IS NULL
),
resueltas AS (
    SELECT c.id,
           CASE WHEN pe.n = 1 THEN pe.item_id WHEN pe.n = 0 AND ti.n = 1 THEN ti.item_id END AS item_id,
           CASE WHEN c.codigo IS NOT NULL THEN 'codigo' ELSE 'prefijo' END AS origen
    FROM candidatas AS c
    CROSS JOIN LATERAL (
        SELECT count(DISTINCT p.item_id) AS n, min(p.item_id) AS item_id
        FROM productos_erp AS p
        WHERE CASE WHEN c.codigo IS NOT NULL THEN btrim(p.codigo) = c.codigo
                   ELSE upper(btrim(p.codigo)) = c.token END
    ) AS pe
    CROSS JOIN LATERAL (
        SELECT count(DISTINCT t.item_id) AS n, min(t.item_id) AS item_id
        FROM tb_item AS t
        WHERE CASE WHEN c.codigo IS NOT NULL THEN btrim(t.item_code) = c.codigo
                   ELSE upper(btrim(t.item_code)) = c.token END
    ) AS ti
)
UPDATE ventas_fuera_operacion_lineas AS l
SET item_id = r.item_id, item_origen = r.origen
FROM resueltas AS r
WHERE r.id = l.id AND r.item_id IS NOT NULL
"""


def upgrade() -> None:
    op.add_column(LINEAS, sa.Column("precio_costo_pdf", MONTO, nullable=True))
    op.add_column(LINEAS, sa.Column("item_origen", sa.String(20), nullable=True))
    op.add_column(LINEAS, sa.Column("override_estado", sa.String(20), nullable=True))
    op.create_table(
        "ventas_fuera_linea_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("empresa", sa.String(200), nullable=False),
        sa.Column("tipo", sa.String(2), nullable=False),
        sa.Column("letra", sa.String(1), nullable=False),
        sa.Column("punto_venta", sa.Integer(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("renglon", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("costo_unitario", sa.Numeric(18, 6), nullable=True),
        sa.Column("codigo", sa.String(100), nullable=True),
        sa.Column("articulo", sa.String(255), nullable=False),
        sa.Column("cantidad", MONTO, nullable=False),
        sa.Column("precio", MONTO, nullable=False),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "empresa", "tipo", "letra", "punto_venta", "numero", "renglon", name="uq_ventas_fuera_linea_overrides_linea"
        ),
    )
    op.create_index("ix_ventas_fuera_linea_overrides_usuario_id", "ventas_fuera_linea_overrides", ["usuario_id"])
    op.create_table(
        "ventas_fuera_codigo_mapeos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clave", sa.String(300), nullable=False, unique=True),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ventas_fuera_codigo_mapeos_usuario_id", "ventas_fuera_codigo_mapeos", ["usuario_id"])

    bind = op.get_bind()
    bind.execute(sa.text(f"UPDATE {LINEAS} SET precio_costo_pdf = precio_costo WHERE precio_costo_pdf IS NULL"))
    bind.execute(
        sa.text(f"UPDATE {LINEAS} SET item_origen = 'codigo' WHERE item_id IS NOT NULL AND item_origen IS NULL")
    )
    sin_producto = bind.execute(sa.text(f"SELECT count(*) FROM {LINEAS} WHERE item_id IS NULL")).scalar_one()
    resueltas = bind.execute(sa.text(RESOLVER_SQL)).rowcount
    log.info("vpf_operaciones_overrides: %s of %s 'sin producto' lines got a product", resueltas, sin_producto)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            f"UPDATE {LINEAS} SET precio_costo = precio_costo_pdf "
            "WHERE precio_costo_pdf IS NOT NULL AND precio_costo IS DISTINCT FROM precio_costo_pdf"
        )
    )
    bind.execute(sa.text(f"UPDATE {LINEAS} SET item_id = NULL WHERE item_origen IN ('manual', 'mapeo')"))
    op.drop_index("ix_ventas_fuera_codigo_mapeos_usuario_id", table_name="ventas_fuera_codigo_mapeos")
    op.drop_table("ventas_fuera_codigo_mapeos")
    op.drop_index("ix_ventas_fuera_linea_overrides_usuario_id", table_name="ventas_fuera_linea_overrides")
    op.drop_table("ventas_fuera_linea_overrides")
    op.drop_column(LINEAS, "override_estado")
    op.drop_column(LINEAS, "item_origen")
    op.drop_column(LINEAS, "precio_costo_pdf")
