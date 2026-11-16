"""copy the TN publisher measurements into the product master

Revision ID: 20261118_tn_medidas_maestro
Revises: 20261116_producto_tn_vinculos
Create Date: 2026-11-16

abm-productos T7 (delivery 5, L8 Q3): the TN publisher stops using `tn_publish_override` (one row per EAN and field, in
TN units) and reads and writes the product master (`productos_propios`). This copies the stored values once, by the
GBP `Código` (`productos_erp.codigo`, only a code of exactly one product), in the master's units:
- weight kg -> `peso_g` (x 1000);
- TN width = GBP large -> `largo_cm`; TN depth = GBP wide -> `ancho_cm`; height -> `alto_cm`.

A value the master already holds is kept (an ABM edit wins). A value equal to GBP (`tb_item`, lowest comp_id) is not
stored, since NULL already means "follow GBP". A value that is not a positive number in the column's range is skipped.
`updated_by` of a new row is the operator who last saved that EAN's measurements.

The downgrade leaves the copy in place: the master owns those values now and cannot tell them from ABM edits. The old
table stays untouched; a later PR drops it once nothing reads it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261118_tn_medidas_maestro"
down_revision: Union[str, None] = "20261116_producto_tn_vinculos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COPY = sa.text(r"""
    WITH productos AS (
        SELECT codigo, min(item_id) AS item_id FROM productos_erp
        WHERE codigo IS NOT NULL GROUP BY codigo HAVING count(*) = 1
    ),
    numeros AS (
        -- The cast only runs on a plain decimal: a CASE, since a WHERE does not fix the evaluation order.
        SELECT p.item_id, o.campo, o.usuario_id, o.fecha_actualizacion,
               CASE WHEN btrim(o.valor) ~ '^[0-9]+(\.[0-9]+)?$'
                    THEN btrim(o.valor)::numeric * CASE o.campo WHEN 'weight' THEN 1000 ELSE 1 END
               END AS valor
        FROM tn_publish_override o
        JOIN productos p ON p.codigo = o.ean
        WHERE o.campo IN ('weight', 'width', 'depth', 'height')
    ),
    valores AS (
        SELECT * FROM numeros WHERE valor > 0 AND valor < 100000000
    ),
    por_item AS (
        SELECT v.item_id,
               max(v.valor) FILTER (WHERE v.campo = 'weight') AS peso_g,
               max(v.valor) FILTER (WHERE v.campo = 'width') AS largo_cm,
               max(v.valor) FILTER (WHERE v.campo = 'depth') AS ancho_cm,
               max(v.valor) FILTER (WHERE v.campo = 'height') AS alto_cm,
               (array_agg(v.usuario_id ORDER BY v.fecha_actualizacion DESC NULLS LAST))[1] AS usuario_id
        FROM valores v GROUP BY v.item_id
    ),
    sin_gbp AS (
        SELECT i.item_id, i.usuario_id,
               NULLIF(i.peso_g, t.item_weight) AS peso_g,
               NULLIF(i.largo_cm, t.item_large) AS largo_cm,
               NULLIF(i.ancho_cm, t.item_wide) AS ancho_cm,
               NULLIF(i.alto_cm, t.item_higth) AS alto_cm
        FROM por_item i
        LEFT JOIN LATERAL (
            SELECT * FROM tb_item ti WHERE ti.item_id = i.item_id ORDER BY ti.comp_id LIMIT 1
        ) t ON true
    )
    INSERT INTO productos_propios (item_id, peso_g, largo_cm, ancho_cm, alto_cm, updated_by)
    SELECT item_id, peso_g, largo_cm, ancho_cm, alto_cm, usuario_id FROM sin_gbp
    WHERE COALESCE(peso_g, largo_cm, ancho_cm, alto_cm) IS NOT NULL
    ON CONFLICT (item_id) DO UPDATE SET
        peso_g = COALESCE(productos_propios.peso_g, EXCLUDED.peso_g),
        largo_cm = COALESCE(productos_propios.largo_cm, EXCLUDED.largo_cm),
        ancho_cm = COALESCE(productos_propios.ancho_cm, EXCLUDED.ancho_cm),
        alto_cm = COALESCE(productos_propios.alto_cm, EXCLUDED.alto_cm),
        updated_at = now()
""")


def upgrade() -> None:
    op.get_bind().execute(_COPY)


def downgrade() -> None:
    # The copied values stay in the master (see the module docstring); `tn_publish_override` was never changed.
    pass
