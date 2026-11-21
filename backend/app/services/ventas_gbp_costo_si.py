"""The cost of a GBP sale line (Ventas por fuera and Tienda Nube metrics, their live listings) from costo SI
(sell-in-costo-si T3 PR 9, S13; owner L6.2 "costo d va a aplicar sobre costo si").

One SQL piece for the four raw queries that used to carry their own list-cost LATERAL
(`scripts/agregar_metricas_fuera_ml.py`, `scripts/agregar_metricas_tienda_nube.py`, `api/endpoints/ventas_fuera_ml.py`,
`api/endpoints/ventas_tienda_nube.py`):

- `join(alias, item, fecha)`: `LEFT JOIN LATERAL` of `costo_si.lote.sql_en_fecha`, the cost in force on the sale date
  in the product's currency (owner L18) at that date's rate, list cost when there is no costo SI (interface Q1), a
  combo that is not a PC = its components x quantity (S11);
- `costo_unitario_ars(alias, item, comp, ct, grupo)`: that cost in pesos, NULL when unknown (no costo SI or list
  cost, or no USD rate: interface §7, never 0), 0 for a line without a product (as before), and 0 for a combo whose breakdown the same sale brings (owner L19: "claro si el combo trae el
  desglose no tomarlo, si no lo trae sí"): every one of its components is another line of the same transaction that
  is costed too (`_desglosado`). A PC (cat 47) is its own product, as today;
- `suma_grupo(costo)` / `costo_grupo(alias)`: an association group's cost, NULL when any of its lines is unknown;
- `tipo_cambio_en(fecha)`: the reader's USD rate on that date, the one the crons store as `cotizacion_dolar`;
- `avisar_costos_desconocidos(filas, origen)`: logs a row whose cost is unknown (stored NULL);
- `avisar_combos_parciales(db, filas, origen)`: logs a combo sold with only part of its breakdown (group id =
  `ct_transaction`), never silently costed twice.

Costo D (x 1.065) stays on top in each query, as before: only the base changed.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.combos.pcs import CAT_PC
from app.services.costo_si import lote
from app.services.ventas_fuera_pdf.costo_erp import combos_desglosados

logger = logging.getLogger(__name__)

GBP_ITEM = "COALESCE({t}.item_id, {t}.it_item_id_origin, {t}.item_idfrompreinvoice)"


def join(alias: str, item: str, fecha: str) -> str:
    """`LEFT JOIN LATERAL (<costo SI of item on fecha>) alias ON true`: columns `alias.costo_si_*`."""
    return f"LEFT JOIN LATERAL ({lote.sql_en_fecha(item, fecha)}) {alias} ON true"


def tipo_cambio_en(fecha: str) -> str:
    """The USD rate the reader converts with on `fecha` (`lote.sql_tipo_cambio`, NULL without one), as a scalar SQL
    subquery: what a row stores as its `cotizacion_dolar`, so the row's cost and its rate are the same rate."""
    return f"(SELECT t.costo_si_tipo_cambio FROM ({lote.sql_tipo_cambio(fecha)}) t)"


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
    return f"(CASE WHEN {item} IS NULL THEN 0 WHEN {desglosado} THEN 0 ELSE {alias}.costo_si_ars END)"


def suma_grupo(costo: str) -> str:
    """The cost of an association group (an aggregate over its lines): their sum, or NULL (unknown) when any line's
    cost is unknown; never a partial sum that passes an unknown line as 0 (interface §7)."""
    return f"(CASE WHEN bool_and(({costo}) IS NOT NULL) THEN SUM({costo}) END)"


def costo_grupo(alias: str) -> str:
    """The group cost a principal line (price 0) takes: 0 when its transaction has no group row (as before), the
    group's cost otherwise, NULL when that cost is unknown."""
    return f"(CASE WHEN {alias}.ct_transaction IS NULL THEN 0 ELSE {alias}.costo_combo END)"


def avisar_combos_parciales(db: Session, filas: Iterable[Any], *, origen: str) -> None:
    """Log every combo sold with only part of its breakdown (owner L19 doubt): the SQL above costs it whole and its
    loose components too. The group id is the GBP transaction `(comp_id, ct_transaction)`, and EVERY line of it
    counts, also the components hidden under an association group's principal line that are not listing rows. Same
    rule as the PDF (`costo_erp.combos_desglosados`)."""
    transacciones = sorted({fila.ct_transaction for fila in filas})
    if not transacciones:
        return
    lineas = db.execute(
        text(
            f"SELECT tit.comp_id, tit.ct_transaction, {GBP_ITEM.format(t='tit')} FROM tb_item_transactions tit"
            " WHERE tit.ct_transaction = ANY(:cts)"
        ),
        {"cts": transacciones},
    )
    grupos: dict[tuple[int, int], list[Optional[int]]] = {}
    for comp_id, ct, item_id in lineas:
        grupos.setdefault((comp_id, ct), []).append(item_id)
    combos_desglosados(db, grupos, origen=origen)


def avisar_costos_desconocidos(filas: Iterable[Any], *, origen: str) -> None:
    """Log every row whose cost is unknown (NULL, interface §7: no costo SI or list cost, or no USD rate on the sale
    date): it is stored without cost, ganancia or markup, never as a 0 cost."""
    for fila in filas:
        if fila.costo_total is None:
            logger.warning(
                "%s: unknown cost for item %s in transaction %s (line %s): stored without cost",
                origen,
                fila.item_id,
                fila.ct_transaction,
                fila.it_transaction,
            )
