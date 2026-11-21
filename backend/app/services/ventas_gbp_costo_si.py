"""The cost of a GBP sale line (Ventas por fuera and Tienda Nube metrics, their live listings) from costo SI
(sell-in-costo-si T3 PR 9, S13; owner L6.2 "costo d va a aplicar sobre costo si").

One SQL piece for the four raw queries that used to carry their own list-cost LATERAL
(`scripts/agregar_metricas_fuera_ml.py`, `scripts/agregar_metricas_tienda_nube.py`, `api/endpoints/ventas_fuera_ml.py`,
`api/endpoints/ventas_tienda_nube.py`):

- `join(alias, item, fecha)`: `LEFT JOIN LATERAL` of `costo_si.lote.sql_en_fecha`, the cost in force on the sale date
  in the product's currency (owner L18) at that date's rate, list cost when there is no costo SI (interface Q1), a
  combo that is not a PC = its components x quantity (S11);
- `costo_unitario_ars(alias, item, comp, ct, grupo)`: that cost in pesos, 0 when unknown (as a line without a list
  cost always was), and 0 for a combo whose breakdown the same sale brings (owner L19: "claro si el combo trae el
  desglose no tomarlo, si no lo trae sí"): one of its components is another line of the same transaction that is
  costed too (`_desglosado`). A PC (cat 47) is its own product, as today.

Costo D (x 1.065) stays on top in each query, as before: only the base changed.
"""

from __future__ import annotations

from app.services.combos.pcs import CAT_PC
from app.services.costo_si import lote

GBP_ITEM = "COALESCE({t}.item_id, {t}.it_item_id_origin, {t}.item_idfrompreinvoice)"


def join(alias: str, item: str, fecha: str) -> str:
    """`LEFT JOIN LATERAL (<costo SI of item on fecha>) alias ON true`: columns `alias.costo_si_*`."""
    return f"LEFT JOIN LATERAL ({lote.sql_en_fecha(item, fecha)}) {alias} ON true"


def _desglosado(item: str, comp: str, ct: str, grupo: str, *, en_grupo: bool) -> str:
    """Owner L19: the combo `item` comes broken down: EVERY one of its components is another line of the same
    transaction that is costed too (one loose unit of a component is not a breakdown; quantities are not compared).
    `en_grupo` (the sum of an association group): any line of the transaction on the same side of
    `it_isassociationgroup` (a Boolean, so the same side, not one specific group: the grouping the queries already
    use). Otherwise (a listing row): a line of the same transaction that is a row itself, i.e. not a component hidden
    under its group's principal line (the queries' "Excluir componentes de combos" rule)."""
    otra = GBP_ITEM.format(t="d")
    if en_grupo:
        alcance = f"d.it_isassociationgroup IS NOT DISTINCT FROM {grupo}"
    else:
        alcance = (
            "NOT (COALESCE(d.it_isassociation, false) = true AND COALESCE(d.it_order, 1) <> 1"
            " AND d.it_isassociationgroup IS NOT NULL)"
        )
    return f"""(
        EXISTS (SELECT 1 FROM combo_componentes cc WHERE cc.combo_item_id = {item})
        AND NOT EXISTS (
            SELECT 1 FROM combo_componentes cc
            WHERE cc.combo_item_id = {item}
              AND NOT EXISTS (
                  SELECT 1 FROM tb_item_transactions d
                  WHERE d.comp_id = {comp} AND d.ct_transaction = {ct} AND {alcance}
                    AND {otra} = cc.componente_item_id
              )
        )
        AND NOT EXISTS (
            SELECT 1 FROM (SELECT DISTINCT ON (t.item_id) t.cat_id FROM tb_item t
                           WHERE t.item_id = {item} ORDER BY t.item_id, t.comp_id) pc
            WHERE pc.cat_id = {CAT_PC}
        )
    )"""


def costo_unitario_ars(alias: str, item: str, comp: str, ct: str, grupo: str, *, en_grupo: bool = False) -> str:
    """The line's unit cost in pesos WITHOUT Costo D (module docstring); `en_grupo` for the sum of an association
    group, else for a listing row (see `_desglosado`)."""
    desglosado = _desglosado(item, comp, ct, grupo, en_grupo=en_grupo)
    return f"(CASE WHEN {desglosado} THEN 0 ELSE COALESCE({alias}.costo_si_ars, 0) END)"
