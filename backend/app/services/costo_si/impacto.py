"""What the deploy's costo SI history recalc will change, measured read-only (sell-in-costo-si T4 dry-run, plan
handoffs/sell-in-costo-si-t4-plan.md §2; owner L17: "cuando deployamos se debería disparar").

The deploy queues every product of `queue.productos_vigentes` for a whole recompute; the drain recomputes each one
from scratch and calls the area callbacks with the first changed date. On a database without costo SI that date is
the product's first step, so `calcular` does the same, inside a `simulacion.Simulacion` (read-only, costo SI read
from memory):

1. the scope (`queue.productos_vigentes`) and every product's steps (`fuentes.entrada` + `engine.calcular`, the
   recompute's own code); a product the engine cannot compute is reported with its reason, never skipped silently;
2. per area callback, the stored rows it will rewrite, before and after, with the same rule it applies (the
   `lote` reader's SQL, the same filters) -- `test_impacto_postgres.py` runs the real callbacks on the same world
   and requires every stored value to equal the prediction.

Areas: `CANAL_ML_LEGACY` = `despues.metricas_ml_legacy` (`ml_ventas_metricas`), `CANAL_ML_CONGELADO` = the ML
sale costs frozen at the sale date (`despues.ml_ventas` -> `recongelar_costo_si`, `ml_order_item_costos`) and the
stored markups = `despues.pricing` (`productos_pricing`), `CANAL_FUERA` = the ventas por fuera PDF lines
(`despues.ventas_fuera` -> `costo_erp.recostear`, called here in its report-only mode), `CANAL_TN` and
`CANAL_FUERA_GBP` = the stored GBP metrics (`despues.ventas_tienda_nube_metricas` / `ventas_fuera_ml_metricas` ->
`costo_si_metricas_gbp`: its own line selection and the cron's own query, compared as its UPDATE compares).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence

from sqlalchemy import BigInteger, Date, Float, Integer, Numeric, String, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.producto import ProductoPricing
from app.services.costo_si import fuentes, lote, queue
from app.services.costo_si.engine import calcular as calcular_engine
from app.services.costo_si.recompute import _fila
from app.services.costo_si.simulacion import Simulacion

logger = logging.getLogger(__name__)

CANAL_ML_LEGACY = "ml_legacy"
CANAL_ML_CONGELADO = "ml_congelado"
CANAL_FUERA = "fuera"
CANAL_TN = "tienda_nube"
CANAL_FUERA_GBP = "fuera_gbp"
LOTE = 50  # products per channel statement: the in-memory steps are scanned per sale row, keep them few


@dataclass(frozen=True)
class Cambio:
    """One stored sale row a callback rewrites: its cost in pesos before and after (`despues` None = the cost
    becomes unknown on its date, the row's cost is then stored empty)."""

    canal: str
    item_id: int
    fila_id: int
    fecha: date
    mes: date
    antes: Optional[Decimal]
    despues: Optional[Decimal]


@dataclass(frozen=True)
class CambioMarkup:
    item_id: int
    campo: str
    antes: object
    despues: object


@dataclass
class Pasos:
    filas: List[dict] = field(default_factory=list)  # every product's steps, as `costo_si_pasos` rows
    desdes: Dict[int, date] = field(default_factory=dict)  # product -> its first step: what the callbacks get
    fallidos: Dict[int, str] = field(default_factory=dict)  # product -> why the engine could not compute it
    alcance: int = 0  # products queued by the deploy


@dataclass
class Informe:
    pasos: Pasos
    cambios: List[Cambio]
    markups: List[CambioMarkup]
    omitidos_markup: List[tuple]  # (item_id, markup, reason) the pricing callback cannot recompute
    sombras: list


def calcular_pasos(db: Session, items: Sequence[int]) -> Pasos:
    """Every product's whole history, computed as the recompute does (`recompute.recalcular`), not stored."""
    out = Pasos(alcance=len(items))
    for item_id in items:
        try:
            with db.begin_nested():  # a database error in one product must not abort the read-only transaction
                entrada = fuentes.entrada(db, item_id)
                if entrada is None:
                    continue
                pasos = calcular_engine(entrada.inicio, entrada.compras)
                moneda = entrada.moneda
        except (ValueError, SQLAlchemyError) as exc:
            out.fallidos[item_id] = f"{type(exc).__name__}: {exc}"
            logger.warning("costo SI dry-run: product %s not computed: %s", item_id, out.fallidos[item_id])
            continue
        for orden, paso in enumerate(pasos):
            out.filas.append({**_fila(paso, moneda), "item_id": item_id, "orden": orden})
        if pasos:
            out.desdes[item_id] = min(p.fecha for p in pasos)
    return out


_COMPONENTES_SQL = text(
    "SELECT combo_item_id, componente_item_id FROM combo_componentes WHERE combo_item_id = ANY(:ids)"
).bindparams(bindparam("ids", type_=ARRAY(Integer)))


def _con_combos(db: Session, desdes: Dict[int, date]) -> Dict[int, date]:
    """Product -> the date its rows are re-costed from: each product from its own first step, and each combo that
    contains it (a PC included, `lote.combos_con`) from the earliest one among its changed components."""
    out = dict(desdes)
    for componente, combos in lote.combos_con(db, desdes).items():
        for combo in combos:
            out[combo] = min(out.get(combo, desdes[componente]), desdes[componente])
    return out


def _lotes(db: Session, sim: Simulacion, filas: List[dict], desdes: Dict[int, date]):
    """(items, desdes) in batches, each with only the steps its products (and their combos' components) read."""
    items = sorted(desdes)
    for i in range(0, len(items), LOTE):
        lote_items = items[i : i + LOTE]
        leidos = set(lote_items)
        for combo, componente in db.execute(_COMPONENTES_SQL, {"ids": lote_items}):
            leidos.add(componente)
        sim.sombra.fijar_pasos([f for f in filas if f["item_id"] in leidos])
        yield lote_items, [desdes[x] for x in lote_items]


# `despues.metricas_ml_legacy`'s rule (its `v` CTE): the rows from the date on whose stored unit cost differs from
# the cost in force on their sale date, total = unit x quantity.
_ML_LEGACY_SQL = text(
    f"""
    SELECT m.id_operacion, m.item_id, m.fecha_venta::date AS fecha,
           date_trunc('month', m.fecha_venta::date)::date AS mes,
           m.costo_total_sin_iva AS antes, round(cs.costo_si_ars * m.cantidad, 2) AS despues
    FROM unnest(:items, :desdes) AS q(item_id, desde)
    JOIN ml_ventas_metricas m ON m.item_id = q.item_id AND m.fecha_venta::date >= q.desde
    LEFT JOIN LATERAL ({lote.sql_en_fecha("m.item_id", "m.fecha_venta::date")}) cs ON true
    WHERE m.costo_unitario_sin_iva IS DISTINCT FROM round(cs.costo_si_ars, 6)
    ORDER BY m.id
    """
).bindparams(bindparam("items", type_=ARRAY(Integer)), bindparam("desdes", type_=ARRAY(Date)))


def ml_legacy(db: Session, sim: Simulacion, filas: List[dict], desdes: Dict[int, date]) -> List[Cambio]:
    out: List[Cambio] = []
    for items, fechas in _lotes(db, sim, filas, desdes):
        for r in db.execute(_ML_LEGACY_SQL, {"items": items, "desdes": fechas}):
            out.append(Cambio(CANAL_ML_LEGACY, r.item_id, r.id_operacion, r.fecha, r.mes, r.antes, r.despues))
    return out


def _ml_congelado_sql():
    """`recongelar_costo_si`'s rule (its `nuevos` + `cambiados` CTEs, built from its own SQL pieces): the rows of
    the product sold (ART day) on or after the date whose cost, or was, costo SI, with a known cost on that date,
    where any frozen value differs. Money = unit cost x the sale line's quantity (`ml_order_items_ops`; 1 when the
    line is missing). A row the reader cannot cost on its date is kept as frozen by the re-freeze: not a change."""
    from app.services.ml_orders_ingestion import recongelar_costo_si as rc

    fecha = rc.FECHA_VENTA_SQL
    return text(
        f"""
        SELECT c.id, c.producto_item_id AS item_id, {fecha} AS fecha, date_trunc('month', {fecha})::date AS mes,
               c.costo_unitario_ars * COALESCE(q.cantidad, 1) AS antes,
               round(cs.costo_si_ars, 4) * COALESCE(q.cantidad, 1) AS despues
        FROM unnest(:items, :desdes) AS d(item_id, desde)
        JOIN ml_order_item_costos c ON c.producto_item_id = d.item_id
        JOIN ml_orders_ops o ON o.order_id = c.order_id AND o.date_created IS NOT NULL
        LEFT JOIN LATERAL ({lote.sql_en_fecha("c.producto_item_id", fecha)}) cs ON true
        LEFT JOIN LATERAL (
            SELECT sum(oi.quantity) AS cantidad FROM ml_order_items_ops oi
            WHERE oi.order_id = c.order_id AND oi.item_id = c.item_id
              AND oi.variation_id IS NOT DISTINCT FROM c.variation_id
        ) q ON true
        WHERE {fecha} >= d.desde
          AND cs.costo_si_ars > 0
          AND (cs.costo_si_fuente = '{lote.FUENTE_COSTO_SI}' OR c.fuente IN :costo_si
               OR c.fuente IN ('combo', 'hist_combo'))
          AND (c.costo_origen, c.moneda, c.tipo_cambio, c.tipo_cambio_fecha, c.costo_unitario_ars, c.fuente,
               c.costo_fecha)
              IS DISTINCT FROM
              (round(cs.costo_si_costo, 4), cs.costo_si_moneda, round(cs.costo_si_tipo_cambio, 4),
               cs.costo_si_tipo_cambio_fecha,
               round(cs.costo_si_ars, 4), {rc._FUENTE_SQL}, {fecha})
        ORDER BY c.id
        """
    ).bindparams(
        bindparam("items", type_=ARRAY(Integer)),
        bindparam("desdes", type_=ARRAY(Date)),
        bindparam("costo_si", value=rc.FUENTES_COSTO_SI, expanding=True),
    )


def ml_congelado(db: Session, sim: Simulacion, filas: List[dict], desdes: Dict[int, date]) -> List[Cambio]:
    sql = _ml_congelado_sql()
    out: List[Cambio] = []
    for items, fechas in _lotes(db, sim, filas, desdes):
        for r in db.execute(sql, {"items": items, "desdes": fechas}):
            out.append(Cambio(CANAL_ML_CONGELADO, r.item_id, r.id, r.fecha, r.mes, r.antes, r.despues))
    return out


def ventas_fuera(db: Session, sim: Simulacion, filas: List[dict], desdes: Dict[int, date]) -> List[Cambio]:
    """What `despues.ventas_fuera` rewrites, product by product as the drain calls it (the product and the combos
    containing it, from its first step), through `costo_erp.recostear(aplicar=False)`: its own selection, manual
    costs and broken-down combos (L19) included. A combo line reached from several components counts once."""
    from app.services.ventas_fuera_pdf.costo_erp import recostear

    combos = lote.combos_con(db, desdes)
    out: Dict[int, Cambio] = {}
    for item_id, desde in sorted(desdes.items()):
        ids = {item_id, *combos.get(item_id, [])}
        leidos = set(ids)
        for _combo, componente in db.execute(_COMPONENTES_SQL, {"ids": sorted(ids)}):
            leidos.add(componente)
        sim.sombra.fijar_pasos([f for f in filas if f["item_id"] in leidos])
        for c in recostear(db, desde=desde, items=ids, aplicar=False):
            out[c.linea_id] = Cambio(
                CANAL_FUERA, c.item_id, c.linea_id, c.fecha, c.fecha.replace(day=1), c.antes, c.despues
            )
    return [out[k] for k in sorted(out)]


# `costo_si_metricas_gbp._RECOSTEO`'s `v`: the stored rows whose cost, currency or rate differ from the cron's.
_GBP_SQL = """
WITH n AS (
    SELECT * FROM unnest(:its, :unitarios, :totales, :monedas, :tcs) AS n(it, unitario, total, moneda, tc)
)
SELECT m.id, m.item_id, m.fecha_venta, m.costo_total, round(n.total, 2)
FROM {tabla} m
JOIN n ON n.it = m.it_transaction
WHERE m.costo_unitario IS DISTINCT FROM round(n.unitario, 6)
   OR m.costo_total IS DISTINCT FROM round(n.total, 2)
   OR m.moneda_costo IS DISTINCT FROM n.moneda
   OR m.cotizacion_dolar IS DISTINCT FROM round(NULLIF(n.tc, 0), 4)"""

_ITEMS_DE_SQL = text(
    "SELECT DISTINCT item_id FROM tb_item_transactions WHERE ct_transaction = ANY(:cts) AND item_id IS NOT NULL"
).bindparams(bindparam("cts", type_=ARRAY(BigInteger)))


def _gbp_sql(tabla: str):
    return text(_GBP_SQL.format(tabla=tabla)).bindparams(
        bindparam("its", type_=ARRAY(BigInteger)),
        bindparam("unitarios", type_=ARRAY(Numeric)),
        bindparam("totales", type_=ARRAY(Numeric)),
        bindparam("monedas", type_=ARRAY(String)),
        bindparam("tcs", type_=ARRAY(Numeric)),
    )


def ventas_gbp(db: Session, sim: Simulacion, filas: List[dict], desdes: Dict[int, date]) -> List[Cambio]:
    """What `costo_si_metricas_gbp.recostear_tn` / `recostear_fuera` rewrite, product by product as the drain calls
    them (the product and its combos, from its first step): their own line selection (`_SQL_LINEAS`), the cron's own
    query over those invoices, and their UPDATE's comparison. The steps read are those of every product on the
    invoices (and their components), so a GBP group costs as it will once the whole scope is recomputed. A row
    reached from several products counts once. Costs are pesos (the crons store ARS, `costo_si_moneda` is a label)."""
    from app.scripts import agregar_metricas_fuera_ml as cron_fuera
    from app.scripts import agregar_metricas_tienda_nube as cron_tn
    from app.services import costo_si_metricas_gbp as gbp

    combos = lote.combos_con(db, desdes)
    canales = (
        (CANAL_TN, gbp.TN, cron_tn.obtener_ventas_tienda_nube),
        (CANAL_FUERA_GBP, gbp.FUERA, cron_fuera.obtener_ventas_fuera_ml),
    )
    out: List[Cambio] = []
    for canal, tabla, obtener in canales:
        sql = _gbp_sql(tabla)
        vistos: Dict[int, Cambio] = {}
        for item_id, desde in sorted(desdes.items()):
            items = [item_id, *combos.get(item_id, [])]
            lineas = db.execute(gbp._SQL_LINEAS[tabla], {"desde": desde, "items": items}).all()
            if not lineas:
                continue
            cts = sorted({ln.ct_transaction for ln in lineas})
            its = {ln.it_transaction for ln in lineas}
            leidos = set(items) | {r[0] for r in db.execute(_ITEMS_DE_SQL, {"cts": cts})}
            for _combo, componente in db.execute(_COMPONENTES_SQL, {"ids": sorted(leidos)}):
                leidos.add(componente)
            sim.sombra.fijar_pasos([f for f in filas if f["item_id"] in leidos])
            nuevas = [
                f
                for f in obtener(db, datetime.combine(desde, time.min), gbp._HASTA_SIEMPRE, cts)
                if f.it_transaction in its
            ]
            if not nuevas:
                continue
            params = {
                "its": [f.it_transaction for f in nuevas],
                "unitarios": [f.costo_unitario for f in nuevas],
                "totales": [f.costo_total for f in nuevas],
                "monedas": [f.moneda_costo for f in nuevas],
                "tcs": [f.cotizacion_dolar for f in nuevas],
            }
            for fila_id, item, fecha, antes, nuevo in db.execute(sql, params):
                dia = fecha.date() if isinstance(fecha, datetime) else fecha
                vistos[fila_id] = Cambio(canal, item, fila_id, dia, dia.replace(day=1), antes, nuevo)
        out += [vistos[k] for k in sorted(vistos)]
    return out


def _como_guardado(campo: str, valor):
    """A markup as its column stores it (Float as is; Numeric(10, 2) to the cent), so before and after compare."""
    if valor is None:
        return None
    columna = ProductoPricing.__table__.columns[campo]
    if isinstance(columna.type, Float):
        return float(valor)
    return Decimal(str(valor)).quantize(Decimal(1).scaleb(-columna.type.scale))


def markups(db: Session, sim: Simulacion, filas: List[dict], items: Iterable[int]) -> tuple:
    """The stored markups `despues.pricing` rewrites (`recalcular_markups_guardados` over the current costo SI, for
    the products and the combos that contain them), computed in the session and never flushed."""
    from app.services.recalcular_markups_service import MARKUPS_GUARDADOS, recalcular_markups_guardados

    ids = set(items)
    for combos in lote.combos_con(db, ids).values():
        ids.update(combos)
    sim.sombra.fijar_pasos(filas)
    campos = [markup for _, markup in MARKUPS_GUARDADOS]
    objetos = db.query(ProductoPricing).filter(ProductoPricing.item_id.in_(sorted(ids))).all() if ids else []
    antes = {(o.item_id, c): _como_guardado(c, getattr(o, c)) for o in objetos for c in campos}
    flush = db.flush
    db.flush = lambda *args, **kwargs: None  # the read-only transaction would refuse it anyway
    try:
        omitidos = recalcular_markups_guardados(db, sorted(ids))
    finally:
        db.flush = flush
    out = []
    for o in objetos:
        for c in campos:
            nuevo = _como_guardado(c, getattr(o, c))
            if nuevo != antes[(o.item_id, c)]:
                out.append(CambioMarkup(o.item_id, c, antes[(o.item_id, c)], nuevo))
    db.expunge_all()
    return out, omitidos


def calcular(sim: Simulacion) -> Informe:
    db = sim.db
    sim.sombra.fijar_pasos([])
    alcance = queue.productos_vigentes(db)
    pasos = calcular_pasos(db, alcance)
    desdes = _con_combos(db, pasos.desdes)
    cambios = (
        ml_legacy(db, sim, pasos.filas, desdes)
        + ml_congelado(db, sim, pasos.filas, desdes)
        + ventas_fuera(db, sim, pasos.filas, pasos.desdes)
        + ventas_gbp(db, sim, pasos.filas, pasos.desdes)
    )
    cambios_markup, omitidos = markups(db, sim, pasos.filas, pasos.desdes)
    return Informe(pasos, cambios, cambios_markup, omitidos, sim.sombra.sombras)
