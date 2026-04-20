"""compras 014 — vista v_facturas_compra_vigentes

Revision ID: compras_014_vfactvig
Revises: compras_013_cc_recon
Create Date: 2026-04-17

Vista SQL `v_facturas_compra_vigentes` (design §4.1, D4). Filtra las
filas de `tb_commercial_transactions` que representan facturas de
compra "vigentes" (no anuladas, no contrapartes contables, no remitos,
no presupuestos), para el matching ERP ↔ pedidos_compra y el listado
de facturas pagables.

Plan B documentado (RD2): si p95 > 500 ms bajo carga real, migrar a
MATERIALIZED VIEW con REFRESH CONCURRENTLY post-sync en v1.5.

Convenio heurístico: cuando dos filas del mismo (supp_id, ct_docnumber,
comp_id, bra_id) comparten `hacc_group` con `sd_plusorminus` invertido,
la de `sd_id` MAYOR se considera contraparte contable y se excluye; la
menor queda como base. Derivado de obs #106.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "compras_014_vfactvig"
down_revision: Union[str, None] = "compras_013_cc_recon"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


VIEW_DEFINITION: str = """
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
    op.execute(VIEW_DEFINITION)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_facturas_compra_vigentes")
