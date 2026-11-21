"""The resolved cost of many products at once (sell-in-costo-si T3 PR 1): what every listing, export, SQL sort and cron
reads instead of `productos_erp.costo`. Interface: handoffs/sell-in-costo-si-interfaz.md.

One rule, written once as SQL (`sql_en_fecha`, `actual`) and run by the Python readers too, so they never disagree:

- costo SI (S1, S10) on a date = the product's last `costo_si_pasos` row dated on or before it; current = its last row.
  It is in the row's `moneda`, the product's cost currency (owner L18).
- No costo SI (Q1, L4.7: one cost everywhere): the list cost, `fuente` 'lista' (0 or less = no list cost: the ERP
  writes 0 for a missing one). Current = `productos_erp.costo` in
  `moneda_costo`; on a date = the last list 1 history row created before the end of that day (`curr_id` 1/NULL ARS,
  else USD), else the current one.
- A combo (S11, L4.9, L7.1; a PC too, L22) = its components x quantity, each resolved the same way on the same date;
  costo SI only when every component is; unknown when any component is (logged). A PC (cat 47) is a combo here (L22:
  "las pcs son la suma de sus componentes el costo"); one without a bill of materials keeps its list cost. A component
  with no `productos_erp` row (the ERP sync skips categories such as 72 PRODUCCIÓN; the bill of materials does not)
  takes GBP's current list 1 cost (`tb_item_cost_list`, first company) where `productos_erp.costo` would be (#2373).
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
    "costo_si_tipo_cambio_fecha",
)


def _tc_en(fecha: str, *, propio: Optional[str] = None) -> str:
    """The USD rate on the SQL date `fecha` and that rate's own date, as one row (`tc`, `tc_fecha`), like the metrics
    crons: the last `tipo_cambio` venta > 0 dated on or before it, else the ERP's last USD -> ARS
    `tb_cur_exch_history` rate > 0 created before the end of that day; NULLs without either (the peso value is then
    unknown, never 0). `propio`: a rate the caller supplies (SQL), first when not NULL, dated by the latest
    `tipo_cambio` row with that very rate (the screens pass `obtener_tipo_cambio_actual`), NULL when none has it.

    Scalar subqueries under COALESCE / CASE, never a UNION of the sources: a later source is read only when the earlier
    ones have no rate, and with a constant `fecha` each lookup is evaluated once per query, not once per product (a
    full-catalogue sort read the ERP history per row, #2366)."""

    def tipo_cambio(columna: str) -> str:
        return (
            f"(SELECT csi_tc.{columna} FROM tipo_cambio csi_tc WHERE csi_tc.moneda = 'USD' AND csi_tc.venta > 0"
            f" AND csi_tc.fecha <= ({fecha}) ORDER BY csi_tc.fecha DESC LIMIT 1)"
        )

    def erp(columna: str) -> str:
        return (
            f"(SELECT csi_ceh.{columna} FROM tb_cur_exch_history csi_ceh WHERE csi_ceh.curr_id_1 = 2"
            f" AND csi_ceh.curr_id_2 = 1 AND csi_ceh.ceh_exchange > 0 AND csi_ceh.ceh_cd < ({fecha})::date + 1"
            " ORDER BY csi_ceh.ceh_cd DESC, csi_ceh.ceh_id DESC LIMIT 1)"
        )

    tc = f"COALESCE({tipo_cambio('venta')}::numeric, {erp('ceh_exchange')}::numeric)"
    tc_fecha = (
        f"CASE WHEN {tipo_cambio('venta')} IS NOT NULL THEN {tipo_cambio('fecha')} ELSE {erp('ceh_cd')}::date END"
    )
    if propio is not None:
        del_propio = (
            f"(SELECT csi_tcp.fecha FROM tipo_cambio csi_tcp WHERE csi_tcp.moneda = 'USD' AND csi_tcp.venta = {propio}"
            f" AND csi_tcp.fecha <= ({fecha}) ORDER BY csi_tcp.fecha DESC LIMIT 1)"
        )
        tc = f"COALESCE({propio}, {tc})"
        tc_fecha = f"CASE WHEN {propio} IS NOT NULL THEN {del_propio} ELSE {tc_fecha} END"
    return f"SELECT {tc} AS tc, {tc_fecha} AS tc_fecha"


_TC_ULTIMO = _tc_en("CURRENT_DATE")


def sql_tipo_cambio(fecha: str) -> str:
    """The reader's USD rate on the SQL date `fecha`, public for raw SQL that stores the rate next to a cost: a SELECT
    of one row, `costo_si_tipo_cambio` and `costo_si_tipo_cambio_fecha` (that rate's own date), NULLs without a rate
    (interfaz §7). LATERAL-join it, or read the rate as a scalar: `(SELECT t.costo_si_tipo_cambio FROM (...) t)`."""
    return (
        "SELECT csi_tx.tc AS costo_si_tipo_cambio, csi_tx.tc_fecha AS costo_si_tipo_cambio_fecha"
        f" FROM ({_tc_en(fecha)}) csi_tx"
    )


def _es_combo(item: str) -> str:
    """A combo that takes its components' sum, a PC included (L22)."""
    return f"(EXISTS (SELECT 1 FROM combo_componentes csi_x WHERE csi_x.combo_item_id = {item}))"


def _lista_gbp(item: str) -> str:
    """GBP's current list 1 cost of a COMBO COMPONENT that has no `productos_erp` row (the ERP sync skips some
    categories, e.g. 72 PRODUCCIÓN, but the combo bill of materials does not): the source `productos_erp.costo` itself
    is synced from, first company, `curr_id` 1/NULL ARS else USD. Orchestrator decision on #2373."""
    return f"""
            (SELECT csi_gl.coslis_price::numeric, CASE WHEN COALESCE(csi_gl.curr_id, 1) = 1 THEN 'ARS' ELSE 'USD' END,
                    '{FUENTE_LISTA}', NULL::date, 4
             FROM tb_item_cost_list csi_gl
             WHERE csi_gl.item_id = {item} AND csi_gl.coslis_id = 1
               AND NOT EXISTS (SELECT 1 FROM productos_erp csi_pg WHERE csi_pg.item_id = {item})
             ORDER BY csi_gl.comp_id LIMIT 1)"""


def _propio(item: str, fecha: Optional[str], *, componente: bool = False) -> str:
    """One product's own cost: (costo, moneda, fuente, desde), at most one row. `fecha` None = current. `componente`:
    a combo component, which falls back last to GBP's list cost when it has no `productos_erp` row (`_lista_gbp`)."""
    hasta = "" if fecha is None else f" AND csi_p.fecha <= ({fecha})"
    gbp = f"\n            UNION ALL{_lista_gbp(item)}" if componente else ""
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
             FROM productos_erp csi_pe WHERE csi_pe.item_id = {item}){gbp}
        ) csi_o(costo, moneda, fuente, desde, prioridad)
        WHERE csi_o.costo IS NOT NULL AND (csi_o.prioridad = 1 OR csi_o.costo > 0)
        ORDER BY csi_o.prioridad LIMIT 1"""


def _fragmento(item: str, fecha: Optional[str], tc: str) -> str:
    ars = "CASE WHEN csi_b.moneda = 'ARS' THEN csi_b.costo ELSE csi_b.costo * csi_fx.tc END"
    return f"""
    SELECT csi_r.costo AS costo_si_costo, csi_r.moneda AS costo_si_moneda, csi_r.fuente AS costo_si_fuente,
           csi_r.desde AS costo_si_desde,
           CASE WHEN csi_r.moneda = 'USD' THEN csi_fx.tc END AS costo_si_tipo_cambio,
           CASE WHEN csi_r.moneda = 'ARS' THEN csi_r.costo WHEN csi_fx.tc IS NOT NULL THEN csi_r.costo * csi_fx.tc END AS costo_si_ars,
           CASE WHEN csi_r.moneda = 'USD' THEN csi_fx.tc_fecha END AS costo_si_tipo_cambio_fecha
    FROM ({tc}) csi_fx
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
        LEFT JOIN LATERAL ({_propio("csi_cc.componente_item_id", fecha, componente=True)}) csi_b ON true
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
    costo_si_tipo_cambio_fecha=Date(),
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


def sql_actual_catalogo(item: str) -> str:
    """`sql_actual(item)` for a sort over many rows per product (Publicaciones ML has ~6 per product): the current
    costo SI in pesos of every known product computed ONCE per query (an uncorrelated subquery: one InitPlan), then
    looked up per row by the SQL expression `item`; NULL when unknown. Over a few rows `sql_actual` is cheaper."""
    return (
        "((SELECT jsonb_object_agg(csi_ids.item_id::text, csi_cs.costo_si_ars) FROM"
        f" ({_PRODUCTOS}) csi_ids JOIN LATERAL ({_fragmento('csi_ids.item_id', None, _TC_ULTIMO)}) csi_cs"
        f" ON csi_cs.costo_si_ars IS NOT NULL) ->> (({item})::text))::numeric"
    )


@dataclass(frozen=True)
class Costo:
    item_id: int
    costo: Optional[Decimal]  # unit cost in `moneda`; None = unknown
    moneda: Optional[str]  # 'USD' | 'ARS'; None when unknown
    fuente: Optional[str]  # FUENTE_COSTO_SI | FUENTE_LISTA | None
    costo_si_desde: Optional[date]  # the costo SI step in force; None for lista and combos
    tipo_cambio: Optional[Decimal]  # the USD rate of costo_ars; None for ARS or without a rate
    costo_ars: Optional[Decimal]  # in pesos; None when unknown
    # the date of `tipo_cambio` (its `tipo_cambio` row, or the ERP rate's day); None with no rate or a caller's rate
    tipo_cambio_fecha: Optional[date] = None


def _costo(item_id: int, fila) -> Costo:
    return Costo(item_id, *fila)


_ACTUALES_SQL = text(
    f"SELECT q.item_id, cs.*, {_es_combo('q.item_id')} FROM unnest(:ids) AS q(item_id) "
    f"LEFT JOIN LATERAL ({_fragmento('q.item_id', None, _tc_en('CURRENT_DATE', propio='CAST(:tc AS numeric)'))}) cs ON true"
).bindparams(bindparam("ids", type_=ARRAY(Integer)), bindparam("tc", type_=Numeric()))

_EN_FECHAS_SQL = text(
    f"SELECT q.item_id, q.fecha, cs.*, {_es_combo('q.item_id')} FROM unnest(:items, :fechas) AS q(item_id, fecha) "
    f"LEFT JOIN LATERAL ({sql_en_fecha('q.item_id', 'q.fecha')}) cs ON true"
).bindparams(bindparam("items", type_=ARRAY(Integer)), bindparam("fechas", type_=ARRAY(Date)))


def _avisar_sin_tc(costos) -> None:
    """Log the USD costs left without pesos (no USD rate on or before their date): their peso value is unknown, never
    0. One warning per date naming every item, so a page of USD products logs one line, not one per product."""
    por_fecha: Dict[date, List[int]] = {}
    for c, fecha in costos:
        if c.moneda == "USD" and c.costo is not None and c.costo_ars is None:
            por_fecha.setdefault(fecha, []).append(c.item_id)
    for fecha, items in sorted(por_fecha.items()):
        logger.warning(
            "costo SI: no USD rate on %s for %d items %s; their peso cost is unknown", fecha, len(items), sorted(items)
        )


def _avisar_combos_desconocidos(costos) -> None:
    """Log the combos and PCs left without a cost (interfaz §7, L22): a component without one (or, in mixed currencies,
    without a USD rate) makes the sum unknown, never a partial sum or 0. `costos`: (cost, date, is a combo), read by
    the same query; one warning per date naming every item."""
    por_fecha: Dict[date, List[int]] = {}
    for c, fecha, es_combo in costos:
        if es_combo and c.costo is None:
            por_fecha.setdefault(fecha, []).append(c.item_id)
    for fecha, items in sorted(por_fecha.items()):
        logger.warning(
            "costo SI: on %s %d combos/PCs have a component without a cost (or no USD rate); their cost is unknown %s",
            fecha,
            len(items),
            sorted(items),
        )


def actuales(db: Session, item_ids: Iterable[int], *, tipo_cambio=None) -> Dict[int, Costo]:
    """The current cost of every id (one query; none for no ids). `tipo_cambio`: the caller's USD rate for
    `costo_ars`; None = the latest one."""
    ids = sorted({int(i) for i in item_ids if i is not None})
    if not ids:
        return {}
    tc = Decimal(str(tipo_cambio)) if tipo_cambio else None
    filas = [(_costo(r[0], r[1:-1]), r[-1]) for r in db.execute(_ACTUALES_SQL, {"ids": ids, "tc": tc})]
    out = {c.item_id: c for c, _ in filas}
    _avisar_sin_tc((c, date.today()) for c in out.values())
    _avisar_combos_desconocidos((c, date.today(), es_combo) for c, es_combo in filas)
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
    leidas = [(r[1], _costo(r[0], r[2:-1]), r[-1]) for r in filas]
    out = {(c.item_id, f): c for f, c, _ in leidas}
    _avisar_sin_tc((c, f) for (_, f), c in out.items())
    _avisar_combos_desconocidos((c, f, es_combo) for f, c, es_combo in leidas)
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
    """Component -> the combos (PCs included, L22) that contain it: what a change to the component's cost also moves."""
    ids = sorted({int(i) for i in item_ids if i is not None})
    if not ids:
        return {}
    out: Dict[int, List[int]] = {}
    for componente, combo in db.execute(_COMBOS_CON_SQL, {"ids": ids}):
        out.setdefault(componente, []).append(combo)
    return out


def sql_actual_fila(item: str, tipo_cambio: str = "NULL::numeric") -> str:
    """The CURRENT cost of the SQL expression `item` as one row with `COLUMNAS`: exactly what `actuales` answers (the
    list cost from `productos_erp`, never the list history `sql_en_fecha` falls back to). `tipo_cambio`: an SQL
    expression for the caller's USD rate; NULL = the latest one. Use it as
    `LEFT JOIN LATERAL ({sql_actual_fila("p.item_id", ":tc")}) cs ON true` (sell-in-costo-si T3 PR 10)."""
    return _fragmento(item, None, _tc_en("CURRENT_DATE", propio=f"CAST({tipo_cambio} AS numeric)"))


def sql_actual_conjunto(ids: str, tipo_cambio: str = "NULL::numeric") -> str:
    """`sql_actual_fila` for a whole set at once, set-based (no per-row lateral): `item_id` plus `COLUMNAS` for every
    id of the SQL query `ids` (one `item_id` column), exactly what `actuales` answers. The latest step of every product
    is read in one `DISTINCT ON` pass, the list cost and the combos by joins, the rate once. For raw SQL over many rows
    (a catalogue's totals): `LEFT JOIN ({sql_actual_conjunto("SELECT item_id FROM ...", ":tc")}) cs ON cs.item_id =
    p.item_id`. Over a handful of rows `sql_actual_fila` is cheaper (sell-in-costo-si T3 PR 10)."""
    tc = _tc_en("CURRENT_DATE", propio=f"CAST({tipo_cambio} AS numeric)")
    lista_moneda = (
        "CASE WHEN upper(btrim(COALESCE(csi_pe.moneda_costo, ''))) IN ('', 'ARS') THEN 'ARS'"
        " ELSE upper(btrim(csi_pe.moneda_costo)) END"
    )
    # A product's own cost (`_propio`, current): its latest step when it has an average, else its list cost > 0.
    propio = f"""
        SELECT csi_n.item_id,
               CASE WHEN csi_s.promedio_usd IS NOT NULL THEN csi_s.promedio_usd
                    WHEN csi_pe.costo > 0 THEN csi_pe.costo::numeric END AS costo,
               CASE WHEN csi_s.promedio_usd IS NOT NULL THEN csi_s.moneda
                    WHEN csi_pe.costo > 0 THEN {lista_moneda} END AS moneda,
               CASE WHEN csi_s.promedio_usd IS NOT NULL THEN '{FUENTE_COSTO_SI}'
                    WHEN csi_pe.costo > 0 THEN '{FUENTE_LISTA}' END AS fuente,
               CASE WHEN csi_s.promedio_usd IS NOT NULL THEN csi_s.fecha END AS desde
        FROM csi_necesarios csi_n
        LEFT JOIN (
            SELECT DISTINCT ON (csi_p.item_id) csi_p.item_id, csi_p.promedio_usd, csi_p.moneda, csi_p.fecha
            FROM costo_si_pasos csi_p WHERE csi_p.item_id IN (SELECT item_id FROM csi_necesarios)
            ORDER BY csi_p.item_id, csi_p.fecha DESC, csi_p.orden DESC
        ) csi_s ON csi_s.item_id = csi_n.item_id
        LEFT JOIN productos_erp csi_pe ON csi_pe.item_id = csi_n.item_id"""
    ars = "CASE WHEN csi_b.moneda = 'ARS' THEN csi_b.costo ELSE csi_b.costo * csi_fx.tc END"
    return f"""
    WITH csi_q AS (SELECT DISTINCT csi_i.item_id FROM ({ids}) csi_i WHERE csi_i.item_id IS NOT NULL),
    -- the ids with parts (a hash join): combos and PCs alike (L22)
    csi_combo AS MATERIALIZED (
        SELECT csi_q.item_id FROM csi_q
        WHERE csi_q.item_id IN (SELECT csi_x.combo_item_id FROM combo_componentes csi_x)
    ),
    csi_necesarios AS (
        SELECT csi_q.item_id FROM csi_q WHERE csi_q.item_id NOT IN (SELECT item_id FROM csi_combo)
        UNION
        SELECT csi_cc.componente_item_id FROM combo_componentes csi_cc
        WHERE csi_cc.combo_item_id IN (SELECT item_id FROM csi_combo)
    ),
    csi_propio AS ({propio}),
    -- a combo component with no `productos_erp` row: GBP's list cost (`_lista_gbp`)
    csi_gbp AS (
        SELECT DISTINCT ON (csi_gl.item_id) csi_gl.item_id, csi_gl.coslis_price::numeric AS costo,
               CASE WHEN COALESCE(csi_gl.curr_id, 1) = 1 THEN 'ARS' ELSE 'USD' END AS moneda
        FROM tb_item_cost_list csi_gl
        WHERE csi_gl.coslis_id = 1
          AND csi_gl.item_id IN (SELECT csi_cc.componente_item_id FROM combo_componentes csi_cc
                                 WHERE csi_cc.combo_item_id IN (SELECT item_id FROM csi_combo))
          AND NOT EXISTS (SELECT 1 FROM productos_erp csi_pg WHERE csi_pg.item_id = csi_gl.item_id)
        ORDER BY csi_gl.item_id, csi_gl.comp_id
    ),
    csi_componente AS (
        SELECT csi_o.item_id,
               CASE WHEN csi_o.costo IS NOT NULL THEN csi_o.costo WHEN csi_g.costo > 0 THEN csi_g.costo END AS costo,
               CASE WHEN csi_o.costo IS NOT NULL THEN csi_o.moneda WHEN csi_g.costo > 0 THEN csi_g.moneda END AS moneda,
               CASE WHEN csi_o.costo IS NOT NULL THEN csi_o.fuente WHEN csi_g.costo > 0 THEN '{FUENTE_LISTA}' END
                   AS fuente
        FROM csi_propio csi_o LEFT JOIN csi_gbp csi_g ON csi_g.item_id = csi_o.item_id
    ),
    csi_fx AS ({tc}),
    csi_r AS (
        SELECT csi_q.item_id, csi_o.costo, csi_o.moneda, csi_o.fuente, csi_o.desde
        FROM csi_q JOIN csi_propio csi_o ON csi_o.item_id = csi_q.item_id
        WHERE csi_q.item_id NOT IN (SELECT item_id FROM csi_combo)
        UNION ALL
        SELECT csi_cc.combo_item_id,
               CASE WHEN count(DISTINCT csi_b.moneda) = 1 THEN round(sum(csi_cc.cantidad * csi_b.costo), 5)
                    ELSE round(sum(csi_cc.cantidad * {ars}), 5) END,
               CASE WHEN count(DISTINCT csi_b.moneda) = 1 THEN min(csi_b.moneda) ELSE 'ARS' END,
               CASE WHEN bool_and(csi_b.fuente = '{FUENTE_COSTO_SI}') THEN '{FUENTE_COSTO_SI}' ELSE '{FUENTE_LISTA}' END,
               NULL::date
        FROM combo_componentes csi_cc
        CROSS JOIN csi_fx
        LEFT JOIN csi_componente csi_b ON csi_b.item_id = csi_cc.componente_item_id
        WHERE csi_cc.combo_item_id IN (SELECT item_id FROM csi_combo)
        GROUP BY csi_cc.combo_item_id, csi_fx.tc
        HAVING count(*) > 0 AND count(csi_b.costo) = count(*) AND (count(DISTINCT csi_b.moneda) = 1 OR csi_fx.tc IS NOT NULL)
    )
    SELECT csi_q.item_id,
           csi_r.costo AS costo_si_costo, csi_r.moneda AS costo_si_moneda, csi_r.fuente AS costo_si_fuente,
           csi_r.desde AS costo_si_desde,
           CASE WHEN csi_r.moneda = 'USD' THEN csi_fx.tc END AS costo_si_tipo_cambio,
           CASE WHEN csi_r.moneda = 'ARS' THEN csi_r.costo WHEN csi_fx.tc IS NOT NULL THEN csi_r.costo * csi_fx.tc END AS costo_si_ars,
           CASE WHEN csi_r.moneda = 'USD' THEN csi_fx.tc_fecha END AS costo_si_tipo_cambio_fecha
    FROM csi_q CROSS JOIN csi_fx LEFT JOIN csi_r ON csi_r.item_id = csi_q.item_id"""
