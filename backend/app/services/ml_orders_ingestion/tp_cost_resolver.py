"""TP-Link (cost list 8) cost resolver shared by the historical backfill
(`app/scripts/backfill_tp_cost.py`) and the late-load worker
(`services/ml_orders_ingestion/tp_cost_fill.py`, metricas-ml-tplink-mode P2).

`procesar_lote` resolves the TP cost of `ml_order_item_costos` rows from the
list-8 price HISTORY (`tb_item_cost_list_history`, `coslis_id = 8`) and writes
it only where it is still NULL; see `app/scripts/backfill_tp_cost.py` for the
full rules (price at the sale date, first-price fallback flagged approximate,
combo precedence, rejected prices stay NULL).

The five history/FX pickers (`as_date`, `tiene_precio`, `pick_history_row`,
`usd_rates_by_date`, `pick_fx_rate`) come from
`app/services/ml_orders_ingestion/list_history.py`, shared with the
normal-cost backfill; no `app.scripts` module is imported here, so the worker
never loads `backend/.env` through this module.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.models.item_cost_list_history import ItemCostListHistory
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.tipo_cambio import TipoCambio
from app.services.combos.componentes import exigir_combos_disponibles
from app.services.ml_orders_ingestion.costeo_service import (
    _MONEDA_POR_CURR_ID,
    TPLINK_COSLIS_ID,
    componentes_por_combo,
)
from app.services.ml_orders_ingestion.list_history import (
    as_date,
    pick_fx_rate,
    pick_history_row,
    tiene_precio,
    usd_rates_by_date,
)

logger = logging.getLogger(__name__)

# Written by the backfill script and the late-load worker, never by
# `congelar()` (whose own values are `costeo_service.FUENTE_TP_INGESTA`/
# `FUENTE_TP_COMBO`): the list-8 price in effect at the sale date, own or
# summed from components.
FUENTE_TP_HISTORIA = "lista8_historia"
FUENTE_TP_HISTORIA_COMBO = "lista8_historia_combo"
# APPROXIMATE: list 8 only started being used on 2026-06-26, so a sale before
# an item's first list-8 row has no price in effect at its date. It is costed
# with the item's FIRST real list-8 price instead, and stamped with its own
# `fuente` so the screen can show it as approximate. A combo where at least
# one component took that fallback gets the `_combo` variant.
FUENTE_TP_PRIMER_PRECIO = "lista8_primer_precio"
FUENTE_TP_PRIMER_PRECIO_COMBO = "lista8_primer_precio_combo"

SKIP_NO_ORDER_DATE = "no_order_date"
# `producto_item_id` is NOT NULL in the schema; guarded anyway so one bad
# row can never abort its batch -- and every re-run with it.
SKIP_SIN_ITEM_ERP = "sin_item_erp"
# Any unexpected error resolving ONE row: logged, counted, the batch goes on.
SKIP_ERROR = "error_resolucion"
# Never had a real list-8 price: not in TP's catalog (only products with a
# list-8 price are). Expected, kept apart from the real problems below.
SKIP_FUERA_CATALOGO = "fuera_catalogo_tp"
# Has real list-8 prices, but none of them carries a date to pick from.
SKIP_NO_HISTORY = "no_dated_list8_price"
SKIP_AMBIGUOUS = "companies_disagree"
SKIP_BAD_CURRENCY = "unknown_currency"
SKIP_NO_FX = "no_fx_rate"
SKIP_COMBO_COMPONENT = "combo_component_no_price"

# (costo_tp_origen, costo_tp_moneda, costo_tp_tipo_cambio, costo_tp_unitario_ars, costo_tp_fuente)
_TpValues = Tuple[Decimal, str, Optional[Decimal], Decimal, str]


@dataclass
class BackfillTpResult:
    examined: int = 0
    # `resolved` is what could be costed; `written` is what the UPDATE
    # actually changed (a concurrent writer may have set it first).
    resolved: int = 0
    written: int = 0
    batches: int = 0
    last_id: int = 0
    skipped: Counter = field(default_factory=Counter)
    resolved_by_fuente: Counter = field(default_factory=Counter)
    written_by_fuente: Counter = field(default_factory=Counter)


def _historia_lista8(db: Session, item_ids: Sequence[int]) -> Dict[int, List[ItemCostListHistory]]:
    """Every list-8 history row for these ERP items, in ONE query per batch."""
    if not item_ids:
        return {}
    rows = (
        db.query(ItemCostListHistory)
        .filter(
            ItemCostListHistory.coslis_id == TPLINK_COSLIS_ID,
            ItemCostListHistory.item_id.in_(sorted(set(item_ids))),
        )
        .all()
    )
    by_item: Dict[int, List[ItemCostListHistory]] = {}
    for row in rows:
        by_item.setdefault(row.item_id, []).append(row)
    return by_item


# Internal, never counted: the item has real list-8 prices, but none in
# effect at the sale date -- the first-price fallback may still apply.
_SIN_PRECIO_A_FECHA = "sin_precio_a_fecha"


def _primer_precio(rows: Sequence[ItemCostListHistory]) -> Optional[ItemCostListHistory]:
    """The EARLIEST dated row that carries a real price (`> 0`)."""
    fechadas = [row for row in rows if as_date(row.iclh_cd) is not None and tiene_precio(row)]
    if not fechadas:
        return None
    return min(fechadas, key=lambda row: (as_date(row.iclh_cd), row.iclh_id))


def _validar(picks: Sequence[ItemCostListHistory]) -> Tuple[Optional[Tuple[Decimal, str]], Optional[str]]:
    """One pick per company: they must agree, in a known currency."""
    if len({(Decimal(str(p.iclh_price)), p.curr_id) for p in picks}) > 1:
        return None, SKIP_AMBIGUOUS
    moneda = _MONEDA_POR_CURR_ID.get(picks[0].curr_id)
    if moneda is None:
        return None, SKIP_BAD_CURRENCY
    return (Decimal(str(picks[0].iclh_price)), moneda), None


def _precio_exacto(
    rows: Sequence[ItemCostListHistory], as_of: date
) -> Tuple[Optional[Tuple[Decimal, str]], Optional[str]]:
    """The price in effect at `as_of`: `((price, moneda), None)` or
    `(None, reason)`. Never had a real price -> `SKIP_FUERA_CATALOGO`; real
    prices but none in effect yet -> `_SIN_PRECIO_A_FECHA`; anything else is
    a REJECTED price (companies disagree, unknown currency)."""
    if not any(tiene_precio(row) for row in rows):
        return None, SKIP_FUERA_CATALOGO
    companias = {row.comp_id for row in rows}
    picks = [pick_history_row([r for r in rows if r.comp_id == comp], as_of) for comp in companias]
    picks = [pick for pick in picks if pick is not None]
    if not picks:
        return None, _SIN_PRECIO_A_FECHA
    return _validar(picks)


def _precio_primero(rows: Sequence[ItemCostListHistory]) -> Tuple[Optional[Tuple[Decimal, str]], Optional[str]]:
    """The item's FIRST real list-8 price (approximate), per company and
    validated the same way. Only undated real rows -> `SKIP_NO_HISTORY`."""
    companias = {row.comp_id for row in rows}
    primeros = [_primer_precio([r for r in rows if r.comp_id == comp]) for comp in companias]
    primeros = [pick for pick in primeros if pick is not None]
    if not primeros:
        return None, SKIP_NO_HISTORY
    return _validar(primeros)


def _a_ars(
    precio: Tuple[Decimal, str], rates: Sequence[TipoCambio], as_of: date
) -> Optional[Tuple[Decimal, Optional[Decimal]]]:
    valor, moneda = precio
    if moneda == "ARS":
        return valor, None
    rate = pick_fx_rate(rates, as_of)
    if rate is None:
        return None
    tipo_cambio = Decimal(str(rate.venta))
    return valor * tipo_cambio, tipo_cambio


def _sumar_componentes(
    componentes: Sequence[Tuple[int, Decimal]],
    as_of: date,
    historia: Dict[int, List[ItemCostListHistory]],
    rates: Sequence[TipoCambio],
    con_primer_precio: bool,
) -> Tuple[Optional[Tuple[Decimal, bool]], Optional[str]]:
    """`((total_ars, algun_aproximado), None)` or `(None, reason)`, ALL OR
    NOTHING. Every component is examined before deciding, so a REJECTED
    component always wins: `SKIP_COMBO_COMPONENT`/`SKIP_NO_FX` (terminal),
    then `SKIP_FUERA_CATALOGO` (a component never on list 8, terminal), then
    `_SIN_PRECIO_A_FECHA` (only without `con_primer_precio`: try later)."""
    total = Decimal("0")
    algun_aproximado = False
    motivos = set()
    for componente_id, qty in componentes:
        rows = historia.get(componente_id, [])
        precio, motivo = _precio_exacto(rows, as_of)
        aproximado = False
        if precio is None and motivo == _SIN_PRECIO_A_FECHA and con_primer_precio:
            precio, motivo = _precio_primero(rows)
            aproximado = precio is not None
        if precio is None:
            motivos.add(motivo if motivo in (SKIP_FUERA_CATALOGO, _SIN_PRECIO_A_FECHA) else SKIP_COMBO_COMPONENT)
            continue
        convertido = _a_ars(precio, rates, as_of)
        if convertido is None:
            motivos.add(SKIP_NO_FX)
            continue
        total += convertido[0] * qty
        algun_aproximado = algun_aproximado or aproximado
    for motivo in (SKIP_COMBO_COMPONENT, SKIP_NO_FX, SKIP_FUERA_CATALOGO, _SIN_PRECIO_A_FECHA):
        if motivo in motivos:
            return None, motivo
    if total <= 0:
        return None, SKIP_COMBO_COMPONENT
    return (total, algun_aproximado), None


def _valores_propios(
    precio: Tuple[Decimal, str], fuente: str, rates: Sequence[TipoCambio], as_of: date
) -> Tuple[Optional[_TpValues], Optional[str]]:
    # A first-price fallback still converts at the SALE-DATE rate.
    convertido = _a_ars(precio, rates, as_of)
    if convertido is None:
        return None, SKIP_NO_FX
    return (precio[0], precio[1], convertido[1], convertido[0], fuente), None


def _resolver(
    erp_id: int,
    as_of: date,
    historia: Dict[int, List[ItemCostListHistory]],
    combos: Dict[int, List[Tuple[int, Decimal]]],
    rates: Sequence[TipoCambio],
) -> Tuple[Optional[_TpValues], Optional[str]]:
    """Exact beats approximate. In order, stopping at the first that applies:
    1. own price in effect at the sale (`lista8_historia`);
    2. a combo's exact component sum at the sale (`lista8_historia_combo`);
    3. own first price (`lista8_primer_precio`);
    4. a combo's component sum with each component's first-price fallback
       (`lista8_primer_precio_combo`).
    A REJECTED price at any step (companies disagree, unknown currency, no
    rate, a rejected component) ends it: NULL, no later step."""
    rows = historia.get(erp_id, [])
    componentes = combos.get(erp_id)

    precio, motivo = _precio_exacto(rows, as_of)
    if precio is not None:
        return _valores_propios(precio, FUENTE_TP_HISTORIA, rates, as_of)
    if motivo not in (SKIP_FUERA_CATALOGO, _SIN_PRECIO_A_FECHA):
        return None, motivo

    if componentes:
        suma, motivo_componentes = _sumar_componentes(componentes, as_of, historia, rates, con_primer_precio=False)
        if suma is not None:
            return (suma[0], "ARS", None, suma[0], FUENTE_TP_HISTORIA_COMBO), None
        # Rejected component: terminal. Missing ones (not dated yet, or
        # never on list 8) leave room for the combo's own first price.
        if motivo_componentes not in (_SIN_PRECIO_A_FECHA, SKIP_FUERA_CATALOGO):
            return None, motivo_componentes

    if motivo == _SIN_PRECIO_A_FECHA:
        precio, motivo = _precio_primero(rows)
        if precio is not None:
            return _valores_propios(precio, FUENTE_TP_PRIMER_PRECIO, rates, as_of)
        if motivo != SKIP_NO_HISTORY:
            return None, motivo

    if componentes:
        suma, motivo_componentes = _sumar_componentes(componentes, as_of, historia, rates, con_primer_precio=True)
        if suma is None:
            return None, motivo_componentes
        fuente = FUENTE_TP_PRIMER_PRECIO_COMBO if suma[1] else FUENTE_TP_HISTORIA_COMBO
        return (suma[0], "ARS", None, suma[0], fuente), None
    return None, motivo


@dataclass(frozen=True)
class DatosLote:
    """Everything the resolver reads for a set of rows, prefetched once."""

    combos: Dict[int, List[Tuple[int, Decimal]]]
    historia: Dict[int, List[ItemCostListHistory]]
    rates: List[TipoCambio]


def leer_datos(db: Session, rows: Sequence[Any]) -> DatosLote:
    """READ phase: combo compositions, list-8 history (items and components)
    and USD rates for every row, in a fixed number of queries whatever the
    row count.

    Raises `CombosNoSincronizados` while `combo_componentes` is empty: with no
    components a combo would fall through to its own approximate first price,
    and a TP cost once written is never rewritten. Nothing is read or written
    past this point, so the caller can retry later."""
    exigir_combos_disponibles(db)
    erp_ids = {row.producto_item_id for row in rows if row.producto_item_id is not None}
    combos = componentes_por_combo(db, erp_ids)
    componentes = {componente_id for comps in combos.values() for componente_id, _ in comps}
    historia = _historia_lista8(db, erp_ids | componentes)
    fechas = [
        as_date(row.date_created) for row in rows if row.producto_item_id is not None and row.date_created is not None
    ]
    return DatosLote(combos=combos, historia=historia, rates=usd_rates_by_date(db, fechas))


def procesar_lote(db: Session, rows: Sequence[Any], dry_run: bool, result: BackfillTpResult) -> None:
    """Resolves the TP cost of `rows` (each with `.id`, `.producto_item_id`,
    `.date_created`) and, unless `dry_run`, writes it where it is still NULL.
    Counts into `result`; never commits. One bad row never aborts the batch.
    READ (`leer_datos`) then RESOLVE+WRITE (`resolver_y_escribir`)."""
    resolver_y_escribir(db, rows, leer_datos(db, rows), dry_run, result)


def resolver_y_escribir(
    db: Session, rows: Sequence[Any], datos: DatosLote, dry_run: bool, result: BackfillTpResult
) -> None:
    """RESOLVE+WRITE phase over prefetched `datos` (which must cover `rows`):
    no reads, one UPDATE per group of rows resolving to the same values."""
    validas = []
    for row in rows:
        if row.producto_item_id is None:
            result.skipped[SKIP_SIN_ITEM_ERP] += 1
        else:
            validas.append(row)
    rows = validas
    combos, historia, rates = datos.combos, datos.historia, datos.rates

    # Rows that resolve to the same values share ONE UPDATE: far fewer
    # statements than rows, and each one's own RETURNING counts what it changed.
    grupos: Dict[_TpValues, List[int]] = {}
    for row in rows:
        if row.date_created is None:
            result.skipped[SKIP_NO_ORDER_DATE] += 1
            continue
        try:
            valores, motivo = _resolver(row.producto_item_id, as_date(row.date_created), historia, combos, rates)
        except Exception:  # noqa: BLE001 -- one row must never abort its batch
            logger.exception("backfill_tp_cost: resolving ml_order_item_costos.id=%s failed", row.id)
            valores, motivo = None, SKIP_ERROR
        if valores is None:
            result.skipped[motivo] += 1
            continue
        result.resolved += 1
        result.resolved_by_fuente[valores[4]] += 1
        grupos.setdefault(valores, []).append(row.id)

    if dry_run:
        return
    tabla = MlOrderItemCosto.__table__
    for (origen, moneda, tipo_cambio, ars, fuente), ids in grupos.items():
        stmt = (
            update(tabla)
            .where(tabla.c.id.in_(ids), tabla.c.costo_tp_unitario_ars.is_(None))
            .values(
                costo_tp_origen=origen,
                costo_tp_moneda=moneda,
                costo_tp_tipo_cambio=tipo_cambio,
                costo_tp_unitario_ars=ars,
                costo_tp_fuente=fuente,
                costo_tp_at=func.now(),
            )
            .returning(tabla.c.id)
        )
        escritas = len(db.execute(stmt).fetchall())
        result.written += escritas
        result.written_by_fuente[fuente] += escritas
