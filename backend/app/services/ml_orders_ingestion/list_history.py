"""Dated ERP cost-list history and USD rate pickers, shared by the normal-cost
backfill (`app/scripts/backfill_costo_congelado.py`) and the TP-Link cost
resolver (`tp_cost_resolver.py`, used by the TP backfill script and the
late-load worker).

A service module on purpose: these used to live in the normal-cost backfill
script, and importing a script runs its `load_dotenv` in whatever process
imports it.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.item_cost_list_history import ItemCostListHistory
from app.models.tipo_cambio import TipoCambio


def as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def tiene_precio(row: ItemCostListHistory) -> bool:
    """A history row that carries a real cost. A NULL or <= 0 `iclh_price`
    is a HOLE in the ERP, not a product that became free."""
    if row.iclh_price is None:
        return False
    try:
        return Decimal(str(row.iclh_price)) > 0
    except InvalidOperation:
        return False


def pick_history_row(rows: Sequence[ItemCostListHistory], as_of: date) -> Optional[ItemCostListHistory]:
    """The most recent history row dated AT OR BEFORE `as_of` THAT CARRIES
    A REAL PRICE.

    Still no fallback to a later row and no fallback to `ProductoERP.costo`
    -- the sale is never costed with a figure from after it happened. What
    this DOES skip over is a priced-at-zero row, and that is not a loosening
    of the rule, it is the rule applied correctly: measured in production,
    4.360 zero rows spread over 4.353 products blocked 3.462 sales, because
    one junk row poisons every sale between itself and the next real cost.
    A zero is a MISSING cost, not a cost change, so the last real cost known
    before the sale is still the honest answer.

    Compared by DATE, not datetime: `iclh_cd` carries a time-of-day that "at
    the sale" was never meant to discriminate against."""
    fechadas = [row for row in rows if as_date(row.iclh_cd) is not None and as_date(row.iclh_cd) <= as_of]
    con_precio = [row for row in fechadas if tiene_precio(row)]
    if not con_precio:
        return None
    return max(con_precio, key=lambda row: (as_date(row.iclh_cd), row.iclh_id))


def usd_rates_by_date(db: Session, dates: Sequence[date]) -> List[TipoCambio]:
    """Every USD `TipoCambio` row that could possibly be "the rate in
    effect" for any date in this batch, fetched ONCE. Covers from the
    earliest requested date back to the widest available row so the
    per-item pick in `pick_fx_rate` (most recent row with
    `fecha <= sale date`) always has candidates without a second query."""
    if not dates:
        return []
    return (
        db.query(TipoCambio)
        .filter(TipoCambio.moneda == "USD", TipoCambio.fecha <= max(dates))
        .order_by(TipoCambio.fecha.asc(), TipoCambio.id.asc())
        .all()
    )


def pick_fx_rate(rates: Sequence[TipoCambio], as_of: date) -> Optional[TipoCambio]:
    """The most recent USD `TipoCambio` row with `fecha <= as_of` -- the
    rate in effect AT THE SALE DATE, never today's `latest_usd_rate_with_date`
    (that would reintroduce the wrong-date bug this whole script exists to
    close)."""
    eligible = [rate for rate in rates if rate.fecha is not None and rate.venta and rate.fecha <= as_of]
    if not eligible:
        return None
    return max(eligible, key=lambda rate: (rate.fecha, rate.id))
