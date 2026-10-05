"""v_facturas_compra_vigentes: correlated anti-joins + (supp_id, ct_docnumber) index

Revision ID: 20261005_vfactvig_lookup
Revises: 20261002_autovacuum_tablas_calientes
Create Date: 2026-10-05

Measured in production 2026-10-05: `v_facturas_compra_vigentes` (compras_014)
was the top CPU consumer. A single-row lookup
`... FROM v_facturas_compra_vigentes v WHERE v.ct_transaction = :ct`
(erp_matching_service, once per invoice inside the loop of
`app.scripts.sync_commercial_transactions_guid`) ran as a parallel query on
~3 of the server's 4 cores. compras_014 builds `base` and references it three
times, so Postgres materializes it; `contrapartes` self-joins EVERY purchase
row and `anuladas` DISTINCTs every annulment. A filter on the view can't be
pushed into those CTEs, so every lookup paid for the whole table.

Same rows, same columns (names, order, types), written so the outer filter
reaches `tb_commercial_transactions` and the exclusions become per-row probes:

  * annulled tuple: `LEFT JOIN anuladas ... WHERE a.supp_id IS NULL` becomes a
    correlated `NOT EXISTS` on (supp_id, ct_docnumber) against rows whose
    sd_isannulment is TRUE. `anuladas.supp_id` is filtered NOT NULL, so the
    original `IS NULL` is true only when there was no match: an exact anti-join.
    As before, the annulment is NOT restricted to purchase documents nor to
    `ct_kindof` (a sales annulment with the same supplier/doc annuls too).
  * counterpart: `ct_transaction NOT IN (SELECT ct_transaction FROM
    contrapartes)` becomes a correlated `NOT EXISTS` against another row that
    passes the SAME `base` filters (not the annulment one -- compras_014 builds
    `contrapartes` from `base`, before excluding annulled tuples) with the same
    supp_id/ct_docnumber/comp_id/bra_id/hacc_group, opposite sd_plusorminus,
    another ct_transaction and a LOWER sd_id. `NOT IN` and `NOT EXISTS` differ
    only when the subquery can yield NULL; `ct_transaction` is the primary key
    (NOT NULL), so they are equivalent here. The equalities keep SQL NULL
    semantics on both sides: a NULL comp_id/bra_id/hacc_group never pairs, so
    such a row is never a counterpart -- exactly as the compras_014 JOIN.
  * `tb_sale_document.sd_id` is its primary key, so the JOIN never duplicates a
    transaction, and a per-row `NOT EXISTS` matches the per-ct `NOT IN`.

Same column list and expressions, so `CREATE OR REPLACE VIEW` applies (no DROP;
nothing else in the schema depends on this view).

Index: both probes and the callers that filter by supplier
(`erp_matching_service._buscar_ct_vigente`: comp/bra/supp/docnumber; the
`facturas-erp-vigentes` and `facturas-candidatas` endpoints: supp_id ORDER BY
ct_date) look up `(supp_id, ct_docnumber)`. `tb_commercial_transactions` only
has single-column indexes on ct_docnumber/ct_kindof/ct_date/cust_id and
(sd_id, df_id, ct_date). Built CONCURRENTLY outside the transaction
(`autocommit_block`) so the ERP sync keeps writing; an INVALID leftover of an
interrupted build is dropped and rebuilt (`IF NOT EXISTS` would keep it) -- same
precedent as 20261001_ix_mlp_publicationid. `tb_sale_document.sd_id` is
already the primary key.

Parity, plans and old-vs-new timings per caller pattern:
tests/unit/test_v_facturas_compra_vigentes_postgres.py and
odd/tasks/vista-facturas-compra-vigentes.md.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261005_vfactvig_lookup"
down_revision: Union[str, None] = "20261002_autovacuum_tablas_calientes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX = "ix_tb_commercial_transactions_supp_docnumber"

_VALIDITY = sa.text(
    "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
    "WHERE c.relname = :name AND pg_table_is_visible(c.oid)"
)

VIEW_DEFINITION: str = """
CREATE OR REPLACE VIEW v_facturas_compra_vigentes AS
SELECT
    ct.ct_transaction,
    ct.comp_id,
    ct.bra_id,
    ct.supp_id,
    ct.ct_docnumber,
    ct.ct_total,
    ct.curr_id_transaction,
    ct.ct_date,
    ct.sd_id,
    sd.sd_desc,
    sd.hacc_group,
    sd.sd_plusorminus,
    CASE
        WHEN sd.sd_iscreditnote  THEN 'NC'
        WHEN sd.sd_isdebitnote   THEN 'ND'
        WHEN sd.sd_isreceipt     THEN 'ORDEN_PAGO'
        WHEN sd.sd_isinbalance AND sd.sd_istaxable THEN 'FACTURA'
        ELSE 'OTRO'
    END AS clasificacion
FROM tb_commercial_transactions ct
JOIN tb_sale_document sd ON sd.sd_id = ct.sd_id
WHERE sd.sd_ispurchase = TRUE
  AND sd.sd_isannulment = FALSE
  AND sd.sd_ispackinglist = FALSE
  AND sd.sd_isquotation = FALSE
  AND COALESCE(ct.ct_kindof, '') <> 'X'
  AND ct.supp_id IS NOT NULL
  AND ct.ct_docnumber IS NOT NULL
  -- Not annulled: no annulment document (of any kind) for the same (supp_id, ct_docnumber).
  AND NOT EXISTS (
      SELECT 1
      FROM tb_commercial_transactions a
      JOIN tb_sale_document asd ON asd.sd_id = a.sd_id
      WHERE a.supp_id = ct.supp_id
        AND a.ct_docnumber = ct.ct_docnumber
        AND asd.sd_isannulment = TRUE
  )
  -- Not an accounting counterpart: no other base row with the same keys and
  -- hacc_group, inverted sign and a LOWER sd_id (the lower one stays as base).
  AND NOT EXISTS (
      SELECT 1
      FROM tb_commercial_transactions o
      JOIN tb_sale_document osd ON osd.sd_id = o.sd_id
      WHERE o.supp_id = ct.supp_id
        AND o.ct_docnumber = ct.ct_docnumber
        AND o.comp_id = ct.comp_id
        AND o.bra_id = ct.bra_id
        AND osd.hacc_group = sd.hacc_group
        AND sd.sd_plusorminus = -osd.sd_plusorminus
        AND o.ct_transaction <> ct.ct_transaction
        AND ct.sd_id > o.sd_id
        AND osd.sd_ispurchase = TRUE
        AND osd.sd_isannulment = FALSE
        AND osd.sd_ispackinglist = FALSE
        AND osd.sd_isquotation = FALSE
        AND COALESCE(o.ct_kindof, '') <> 'X'
        AND o.supp_id IS NOT NULL
        AND o.ct_docnumber IS NOT NULL
  );
"""

# compras_014's definition, verbatim, for the downgrade.
_COMPRAS_014_VIEW_DEFINITION: str = """
CREATE OR REPLACE VIEW v_facturas_compra_vigentes AS
WITH anuladas AS (
    -- Tuplas (supp_id, ct_docnumber) que tienen al menos una anulación asociada
    SELECT DISTINCT ct.supp_id, ct.ct_docnumber
    FROM tb_commercial_transactions ct
    JOIN tb_sale_document sd ON sd.sd_id = ct.sd_id
    WHERE sd.sd_isannulment = TRUE
      AND ct.supp_id IS NOT NULL
      AND ct.ct_docnumber IS NOT NULL
),
base AS (
    -- Documentos principales de compra (no anulaciones, no contrapartes, no remitos, no presupuestos)
    SELECT
        ct.ct_transaction,
        ct.comp_id,
        ct.bra_id,
        ct.supp_id,
        ct.ct_docnumber,
        ct.ct_total,
        ct.curr_id_transaction,
        ct.ct_date,
        ct.sd_id,
        sd.sd_desc,
        sd.hacc_group,
        sd.sd_plusorminus,
        CASE
            WHEN sd.sd_iscreditnote  THEN 'NC'
            WHEN sd.sd_isdebitnote   THEN 'ND'
            WHEN sd.sd_isreceipt     THEN 'ORDEN_PAGO'
            WHEN sd.sd_isinbalance AND sd.sd_istaxable THEN 'FACTURA'
            ELSE 'OTRO'
        END AS clasificacion
    FROM tb_commercial_transactions ct
    JOIN tb_sale_document sd ON sd.sd_id = ct.sd_id
    WHERE sd.sd_ispurchase = TRUE
      AND sd.sd_isannulment = FALSE
      AND sd.sd_ispackinglist = FALSE
      AND sd.sd_isquotation = FALSE
      AND COALESCE(ct.ct_kindof, '') <> 'X'
      AND ct.supp_id IS NOT NULL
      AND ct.ct_docnumber IS NOT NULL
),
contrapartes AS (
    -- Filas de `base` que son contrapartes de otra con mismo hacc_group y signo invertido.
    -- Convenio operativo: la de sd_id mayor es la contraparte; la menor queda como base.
    SELECT b1.ct_transaction
    FROM base b1
    JOIN base b2
      ON b1.supp_id        = b2.supp_id
     AND b1.ct_docnumber   = b2.ct_docnumber
     AND b1.comp_id        = b2.comp_id
     AND b1.bra_id         = b2.bra_id
     AND b1.hacc_group     = b2.hacc_group
     AND b1.sd_plusorminus = -b2.sd_plusorminus
     AND b1.ct_transaction <> b2.ct_transaction
    WHERE b1.sd_id > b2.sd_id
)
SELECT b.*
FROM base b
LEFT JOIN anuladas a
       ON a.supp_id = b.supp_id AND a.ct_docnumber = b.ct_docnumber
WHERE a.supp_id IS NULL
  AND b.ct_transaction NOT IN (SELECT ct_transaction FROM contrapartes);
"""


def upgrade() -> None:
    with op.get_context().autocommit_block():
        valid = op.get_bind().execute(_VALIDITY, {"name": INDEX}).scalar()
        if valid is False:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")
        if valid is not True:
            op.execute(f"CREATE INDEX CONCURRENTLY {INDEX} ON tb_commercial_transactions (supp_id, ct_docnumber)")
    op.execute(VIEW_DEFINITION)


def downgrade() -> None:
    op.execute(_COMPRAS_014_VIEW_DEFINITION)
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")
