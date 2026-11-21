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

Areas: `CANAL_ML_LEGACY` = `despues.metricas_ml_legacy` (`ml_ventas_metricas`) and the stored markups =
`despues.pricing` (`productos_pricing`). The ML frozen cost (PR 7), ventas por fuera (PR 9) and the Tienda Nube /
fuera GBP metrics join as their callbacks land.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence

from sqlalchemy import Date, Float, Integer, bindparam, text
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
    contains it (not a PC, `lote.combos_con`) from the earliest one among its changed components."""
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
    cambios = ml_legacy(db, sim, pasos.filas, desdes)
    cambios_markup, omitidos = markups(db, sim, pasos.filas, pasos.desdes)
    return Informe(pasos, cambios, cambios_markup, omitidos, sim.sombra.sombras)
