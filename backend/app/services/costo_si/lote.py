"""The resolved cost of many products at once (sell-in-costo-si T3 PR 1): what every listing, export, SQL sort and cron
reads instead of `productos_erp.costo`. Interface: handoffs/sell-in-costo-si-interfaz.md.

One rule, written once as SQL (`sql_en_fecha`, `actual`) and run by the Python readers too, so they never disagree:

- costo SI (S1, S10) on a date = the product's last `costo_si_pasos` row dated on or before it; current = its last row.
  It is in the row's `moneda`, the product's cost currency (owner L18).
- No costo SI (Q1, L4.7: one cost everywhere): the list cost, `fuente` 'lista' (0 or less = no list cost: the ERP
  writes 0 for a missing one). Current = `productos_erp.costo` in
  `moneda_costo`; on a date = the last list 1 history row created before the end of that day (`curr_id` 1/NULL ARS,
  else USD), else the current one.
- A combo that is not a PC (S11, L4.9, L7.1) = its components x quantity, each resolved the same way on the same date;
  costo SI only when every component is; unknown when any component is. A PC (cat 47) is its own product.
- Pesos: ARS as is; USD x the USD rate (`tipo_cambio`, venta > 0, the last one on or before the date, else the ERP's
  USD -> ARS `tb_cur_exch_history`, like the metrics crons; current: the latest, or the caller's). Without a rate the
  peso value is unknown (NULL, logged by the Python readers): never 0, never the USD number.

Every column is named `costo_si_*` so the MCP strips it without `productos.ver_costos` (`mcp.tools._COST_KEY`, C12).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import Date, Integer, Numeric, String, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import Subquery

from app.services.combos.pcs import CAT_PC, pcs_entre

logger = logging.getLogger(__name__)

FUENTE_COSTO_SI = "costo_si"
FUENTE_LISTA = "lista"

COLUMNAS = (
    "costo_si_costo",
    "costo_si_moneda",
    "costo_si_fuente",
    "costo_si_desde",
    "costo_si_tipo_cambio",
    "costo_si_ars",
)


def _tc_en(fecha: str) -> str:
    """The USD rate on the SQL date `fecha`, like the metrics crons: the last `tipo_cambio` venta > 0 dated on or
    before it, else the ERP's last USD -> ARS `tb_cur_exch_history` rate > 0 created before the end of that day; NULL
    without either (the peso value is then unknown, never 0)."""
    return (
        "COALESCE((SELECT csi_tc.venta::numeric FROM tipo_cambio csi_tc WHERE csi_tc.moneda = 'USD'"
        f" AND csi_tc.venta > 0 AND csi_tc.fecha <= ({fecha}) ORDER BY csi_tc.fecha DESC LIMIT 1),"
        " (SELECT csi_ceh.ceh_exchange::numeric FROM tb_cur_exch_history csi_ceh WHERE csi_ceh.curr_id_1 = 2"
        f" AND csi_ceh.curr_id_2 = 1 AND csi_ceh.ceh_exchange > 0 AND csi_ceh.ceh_cd < ({fecha})::date + 1"
        " ORDER BY csi_ceh.ceh_cd DESC, csi_ceh.ceh_id DESC LIMIT 1))"
    )


_TC_ULTIMO = _tc_en("CURRENT_DATE")


def _es_combo(item: str) -> str:
    """A combo that takes its components' sum: not of the PC category by its first company row (`pcs_entre`)."""
    return (
        f"(EXISTS (SELECT 1 FROM combo_componentes csi_x WHERE csi_x.combo_item_id = {item})"
        " AND NOT EXISTS (SELECT 1 FROM (SELECT DISTINCT ON (csi_t.item_id) csi_t.cat_id FROM tb_item csi_t"
        f" WHERE csi_t.item_id = {item} ORDER BY csi_t.item_id, csi_t.comp_id) csi_pt WHERE csi_pt.cat_id = {CAT_PC}))"
    )


def _propio(item: str, fecha: Optional[str]) -> str:
    """One product's own cost: (costo, moneda, fuente, desde), at most one row. `fecha` None = current."""
    hasta = "" if fecha is None else f" AND csi_p.fecha <= ({fecha})"
    historia = (
        ""
        if fecha is None
        else f"""
        UNION ALL
        (SELECT csi_h.iclh_price::numeric, CASE WHEN COALESCE(csi_h.curr_id, 1) = 1 THEN 'ARS' ELSE 'USD' END,
                '{FUENTE_LISTA}', NULL::date, 2
         FROM tb_item_cost_list_history csi_h
         WHERE csi_h.item_id = {item} AND csi_h.coslis_id = 1 AND csi_h.iclh_cd < ({fecha})::date + 1
         ORDER BY csi_h.iclh_cd DESC, csi_h.iclh_id DESC LIMIT 1)"""
    )
    return f"""
        SELECT csi_o.costo, csi_o.moneda, csi_o.fuente, csi_o.desde FROM (
            (SELECT csi_p.promedio_usd, csi_p.moneda, '{FUENTE_COSTO_SI}', csi_p.fecha, 1
             FROM costo_si_pasos csi_p WHERE csi_p.item_id = {item}{hasta}
             ORDER BY csi_p.fecha DESC, csi_p.orden DESC LIMIT 1){historia}
            UNION ALL
            (SELECT csi_pe.costo::numeric,
                    CASE WHEN upper(btrim(COALESCE(csi_pe.moneda_costo, ''))) IN ('', 'ARS') THEN 'ARS'
                         ELSE upper(btrim(csi_pe.moneda_costo)) END,
                    '{FUENTE_LISTA}', NULL::date, 3
             FROM productos_erp csi_pe WHERE csi_pe.item_id = {item})
        ) csi_o(costo, moneda, fuente, desde, prioridad)
        WHERE csi_o.costo IS NOT NULL AND (csi_o.prioridad = 1 OR csi_o.costo > 0)
        ORDER BY csi_o.prioridad LIMIT 1"""


def _fragmento(item: str, fecha: Optional[str], tc: str) -> str:
    ars = "CASE WHEN csi_b.moneda = 'ARS' THEN csi_b.costo ELSE csi_b.costo * csi_fx.tc END"
    return f"""
    SELECT csi_r.costo AS costo_si_costo, csi_r.moneda AS costo_si_moneda, csi_r.fuente AS costo_si_fuente,
           csi_r.desde AS costo_si_desde,
           CASE WHEN csi_r.moneda = 'USD' THEN csi_fx.tc END AS costo_si_tipo_cambio,
           CASE WHEN csi_r.moneda = 'ARS' THEN csi_r.costo WHEN csi_fx.tc IS NOT NULL THEN csi_r.costo * csi_fx.tc END AS costo_si_ars
    FROM (SELECT {tc} AS tc) csi_fx
    LEFT JOIN LATERAL (
        SELECT csi_d.costo, csi_d.moneda, csi_d.fuente, csi_d.desde FROM ({_propio(item, fecha)}) csi_d
        WHERE NOT {_es_combo(item)}
        UNION ALL
        SELECT CASE WHEN count(DISTINCT csi_b.moneda) = 1 THEN round(sum(csi_cc.cantidad * csi_b.costo), 5)
                    ELSE round(sum(csi_cc.cantidad * {ars}), 5) END,
               CASE WHEN count(DISTINCT csi_b.moneda) = 1 THEN min(csi_b.moneda) ELSE 'ARS' END,
               CASE WHEN bool_and(csi_b.fuente = '{FUENTE_COSTO_SI}') THEN '{FUENTE_COSTO_SI}' ELSE '{FUENTE_LISTA}' END,
               NULL::date
        FROM combo_componentes csi_cc
        LEFT JOIN LATERAL ({_propio("csi_cc.componente_item_id", fecha)}) csi_b ON true
        WHERE csi_cc.combo_item_id = {item} AND {_es_combo(item)}
        HAVING count(*) > 0 AND count(csi_b.costo) = count(*) AND (count(DISTINCT csi_b.moneda) = 1 OR csi_fx.tc IS NOT NULL)
    ) csi_r ON true"""


def sql_actual(item: str) -> str:
    """The current cost in pesos (`costo_si_ars` of `actual()`, latest rate) of the SQL expression `item`, as a scalar
    subquery body: what a listing sorts the `costo_si` key by (`columna.orden`)."""
    return f"SELECT csi_cs.costo_si_ars FROM ({_fragmento(item, None, _TC_ULTIMO)}) csi_cs"


def sql_en_fecha(item: str, fecha: str) -> str:
    """THE SQL fragment for raw SQL and crons: one row with `COLUMNAS` for the SQL expressions `item` (an item id) and
    `fecha` (a date), the cost in force that day at that day's rate. Use it as
    `LEFT JOIN LATERAL ({sql_en_fecha("v.item_id", "v.fecha::date")}) cs ON true`. Every name inside starts with `csi_`
    so it never shadows the caller's aliases: don't give your own tables a `csi_` alias."""
    return _fragmento(item, fecha, _tc_en(fecha))


_TIPOS = dict(
    costo_si_costo=Numeric(),
    costo_si_moneda=String(),
    costo_si_fuente=String(),
    costo_si_desde=Date(),
    costo_si_tipo_cambio=Numeric(),
    costo_si_ars=Numeric(),
)

_PRODUCTOS = (
    "SELECT item_id FROM productos_erp UNION SELECT item_id FROM costo_si_pasos"
    " UNION SELECT combo_item_id FROM combo_componentes"
)


def actual() -> Subquery:
    """The current cost as a joinable subquery: `item_id` plus `COLUMNAS`, one row per known product, for a LEFT JOIN
    that sorts or filters a listing in SQL (`costo_si_ars` orders products of both currencies together)."""
    sql = f"SELECT csi_ids.item_id, csi_cs.* FROM ({_PRODUCTOS}) csi_ids LEFT JOIN LATERAL ({_fragmento('csi_ids.item_id', None, _TC_ULTIMO)}) csi_cs ON true"
    return text(sql).columns(item_id=Integer(), **_TIPOS).subquery("costo_si_actual")


@dataclass(frozen=True)
class Costo:
    item_id: int
    costo: Optional[Decimal]  # unit cost in `moneda`; None = unknown
    moneda: Optional[str]  # 'USD' | 'ARS'; None when unknown
    fuente: Optional[str]  # FUENTE_COSTO_SI | FUENTE_LISTA | None
    costo_si_desde: Optional[date]  # the costo SI step in force; None for lista and combos
    tipo_cambio: Optional[Decimal]  # the USD rate of costo_ars; None for ARS or without a rate
    costo_ars: Optional[Decimal]  # in pesos; None when unknown


def _costo(item_id: int, fila) -> Costo:
    return Costo(item_id, *fila)


_ACTUALES_SQL = text(
    "SELECT q.item_id, cs.* FROM unnest(:ids) AS q(item_id) "
    f"LEFT JOIN LATERAL ({_fragmento('q.item_id', None, f'COALESCE(CAST(:tc AS numeric), {_TC_ULTIMO})')}) cs ON true"
).bindparams(bindparam("ids", type_=ARRAY(Integer)), bindparam("tc", type_=Numeric()))

_EN_FECHAS_SQL = text(
    "SELECT q.item_id, q.fecha, cs.* FROM unnest(:items, :fechas) AS q(item_id, fecha) "
    f"LEFT JOIN LATERAL ({sql_en_fecha('q.item_id', 'q.fecha')}) cs ON true"
).bindparams(bindparam("items", type_=ARRAY(Integer)), bindparam("fechas", type_=ARRAY(Date)))


def _avisar_sin_tc(costos) -> None:
    """Log every USD cost left without pesos (no USD rate on or before its date): its peso value is unknown, never 0."""
    for c, fecha in costos:
        if c.moneda == "USD" and c.costo is not None and c.costo_ars is None:
            logger.warning("costo SI: no USD rate for item %s on %s; its peso cost is unknown", c.item_id, fecha)


def actuales(db: Session, item_ids: Iterable[int], *, tipo_cambio=None) -> Dict[int, Costo]:
    """The current cost of every id (one query; none for no ids). `tipo_cambio`: the caller's USD rate for
    `costo_ars`; None = the latest one."""
    ids = sorted({int(i) for i in item_ids if i is not None})
    if not ids:
        return {}
    tc = Decimal(str(tipo_cambio)) if tipo_cambio else None
    out = {r[0]: _costo(r[0], r[1:]) for r in db.execute(_ACTUALES_SQL, {"ids": ids, "tc": tc})}
    _avisar_sin_tc((c, date.today()) for c in out.values())
    return out


def en_fechas(db: Session, pares: Iterable[Tuple[int, date]]) -> Dict[Tuple[int, date], Costo]:
    """The cost in force on every (product, date), at that date's rate (one query; none for no pairs). A datetime
    counts as its date, and the result is keyed by that date."""
    lista = sorted(
        {(int(i), f.date() if isinstance(f, datetime) else f) for i, f in pares if i is not None and f is not None}
    )
    if not lista:
        return {}
    filas = db.execute(_EN_FECHAS_SQL, {"items": [i for i, _ in lista], "fechas": [f for _, f in lista]})
    out = {(r[0], r[1]): _costo(r[0], r[2:]) for r in filas}
    _avisar_sin_tc((c, f) for (_, f), c in out.items())
    return out


def en_pesos(costo: Optional[Decimal], moneda: Optional[str], tipo_cambio) -> Optional[Decimal]:
    """A cost in pesos: ARS as is, USD x `tipo_cambio`. Unknown without a rate: never the USD number as pesos."""
    if costo is None or moneda is None:
        return None
    if moneda == "ARS":
        return Decimal(costo)
    if not tipo_cambio:
        return None
    return Decimal(costo) * Decimal(str(tipo_cambio))


_COMBOS_CON_SQL = text(
    "SELECT componente_item_id, combo_item_id FROM combo_componentes WHERE componente_item_id = ANY(:ids) ORDER BY 1, 2"
).bindparams(bindparam("ids", type_=ARRAY(Integer)))


def combos_con(db: Session, item_ids: Iterable[int]) -> Dict[int, List[int]]:
    """Component -> the combos (not PCs) that contain it: what a change to the component's cost also moves."""
    ids = sorted({int(i) for i in item_ids if i is not None})
    if not ids:
        return {}
    filas = list(db.execute(_COMBOS_CON_SQL, {"ids": ids}))
    pcs = pcs_entre(db, {combo for _, combo in filas})
    out: Dict[int, List[int]] = {}
    for componente, combo in filas:
        if combo not in pcs:
            out.setdefault(componente, []).append(combo)
    return out
