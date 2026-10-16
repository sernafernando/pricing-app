"""Backfill the TP-Link (cost list 8) cost of historical sales
(metricas-ml-tplink-mode / P2).

`costeo_service.congelar()` freezes the TP cost from the CURRENT list 8 only
for sales ingested after P1. Every older `ml_order_item_costos` row has its
`costo_tp_*` columns NULL. This script fills those -- and ONLY those: the
candidate query reads NULL rows only, and the UPDATE repeats
`costo_tp_unitario_ars IS NULL`, so a TP cost already set is never
rewritten, even one written concurrently by the late-load worker.

The price is the list-8 price IN EFFECT AT THE SALE DATE
(`tb_item_cost_list_history`, `coslis_id = 8`), never a later one and never
the current list. Same picker as the normal-cost backfill
(`backfill_costo_congelado._pick_history_row`) and the list-8 metrics job:
the most recent row dated at or before the sale that carries a REAL price
(`> 0`) -- a zero row is an ERP hole, not a free product.

Same rules as `congelar()` otherwise, and anything that cannot be resolved
stays NULL (the "Total TP incomplete" flag), never 0, never the normal cost:
- rows from more than one company whose prices at the sale date disagree,
  or a picked row in an unknown currency: rejected, and a rejected combo
  price never falls back to its components;
- USD converts at the `TipoCambio` in effect at the sale date (and keeps it
  in `costo_tp_tipo_cambio`); no rate at that date -> NULL;
- a combo with no dated price of its own sums its components' dated prices
  times quantity, ALL OR NOTHING, already in ARS (no rate kept).

Bounded and resumable: keyset pagination on `ml_order_item_costos.id`, one
short session and one commit per batch, never a long transaction. Rows that
resolve leave the NULL set, so a re-run only re-examines what is still
unresolvable; `--after-id` (the `last_id` of the previous summary) skips
that tail.

Run:
    python -m app.scripts.backfill_tp_cost --dry-run
    python -m app.scripts.backfill_tp_cost --limit 50000 --after-id 0
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

backend_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(backend_path))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(dotenv_path=backend_path / ".env")

from sqlalchemy import func, update  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.item_cost_list_history import ItemCostListHistory  # noqa: E402
from app.models.ml_order_item_costo import MlOrderItemCosto  # noqa: E402
from app.models.ml_orders_ops import MlOrdersOps  # noqa: E402
from app.models.tipo_cambio import TipoCambio  # noqa: E402
from app.scripts.backfill_costo_congelado import (  # noqa: E402
    _as_date,
    _pick_fx_rate,
    _pick_history_row,
    _usd_rates_by_date,
)
from app.services.ml_orders_ingestion.costeo_service import (  # noqa: E402
    _MONEDA_POR_CURR_ID,
    TPLINK_COSLIS_ID,
    componentes_por_combo,
)

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 500

# Written ONLY by this script, never by `congelar()` (whose own values are
# `costeo_service.FUENTE_TP_INGESTA`/`FUENTE_TP_COMBO`): the list-8 price in
# effect at the sale date, own or summed from components.
FUENTE_TP_HISTORIA = "lista8_historia"
FUENTE_TP_HISTORIA_COMBO = "lista8_historia_combo"

SKIP_NO_ORDER_DATE = "no_order_date"
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


def _precio_a_fecha(
    rows: Sequence[ItemCostListHistory], as_of: date
) -> Tuple[Optional[Tuple[Decimal, str]], Optional[str]]:
    """`((price, moneda), None)`, or `(None, reason)`. The reason tells a
    MISSING price (`SKIP_NO_HISTORY`, a combo may still sum its components)
    from a REJECTED one (any other reason, never falls back)."""
    picks = []
    for comp_id in {row.comp_id for row in rows}:
        pick = _pick_history_row([row for row in rows if row.comp_id == comp_id], as_of)
        if pick is not None:
            picks.append(pick)
    if not picks:
        return None, SKIP_NO_HISTORY
    if len({(Decimal(str(p.iclh_price)), p.curr_id) for p in picks}) > 1:
        return None, SKIP_AMBIGUOUS
    moneda = _MONEDA_POR_CURR_ID.get(picks[0].curr_id)
    if moneda is None:
        return None, SKIP_BAD_CURRENCY
    return (Decimal(str(picks[0].iclh_price)), moneda), None


def _a_ars(
    precio: Tuple[Decimal, str], rates: Sequence[TipoCambio], as_of: date
) -> Optional[Tuple[Decimal, Optional[Decimal]]]:
    valor, moneda = precio
    if moneda == "ARS":
        return valor, None
    rate = _pick_fx_rate(rates, as_of)
    if rate is None:
        return None
    tipo_cambio = Decimal(str(rate.venta))
    return valor * tipo_cambio, tipo_cambio


def _resolver(
    erp_id: int,
    as_of: date,
    historia: Dict[int, List[ItemCostListHistory]],
    combos: Dict[int, List[Tuple[int, Decimal]]],
    rates: Sequence[TipoCambio],
) -> Tuple[Optional[_TpValues], Optional[str]]:
    precio, motivo = _precio_a_fecha(historia.get(erp_id, []), as_of)
    if precio is not None:
        convertido = _a_ars(precio, rates, as_of)
        if convertido is None:
            return None, SKIP_NO_FX
        return (precio[0], precio[1], convertido[1], convertido[0], FUENTE_TP_HISTORIA), None
    componentes = combos.get(erp_id)
    if motivo != SKIP_NO_HISTORY or not componentes:
        return None, motivo

    total = Decimal("0")
    for componente_id, qty in componentes:
        precio_componente, _ = _precio_a_fecha(historia.get(componente_id, []), as_of)
        if precio_componente is None:
            return None, SKIP_COMBO_COMPONENT
        convertido = _a_ars(precio_componente, rates, as_of)
        if convertido is None:
            return None, SKIP_NO_FX
        total += convertido[0] * qty
    if total <= 0:
        return None, SKIP_COMBO_COMPONENT
    return (total, "ARS", None, total, FUENTE_TP_HISTORIA_COMBO), None


def _procesar_lote(db: Session, rows: Sequence[Any], dry_run: bool, result: BackfillTpResult) -> None:
    erp_ids = {row.producto_item_id for row in rows}
    combos = componentes_por_combo(db, erp_ids)
    componentes = {componente_id for comps in combos.values() for componente_id, _ in comps}
    historia = _historia_lista8(db, erp_ids | componentes)
    fechas = [_as_date(row.date_created) for row in rows if row.date_created is not None]
    rates = _usd_rates_by_date(db, fechas)

    # Rows that resolve to the same values share ONE UPDATE: far fewer
    # statements than rows, and each one's own RETURNING counts what it changed.
    grupos: Dict[_TpValues, List[int]] = {}
    for row in rows:
        if row.date_created is None:
            result.skipped[SKIP_NO_ORDER_DATE] += 1
            continue
        valores, motivo = _resolver(row.producto_item_id, _as_date(row.date_created), historia, combos, rates)
        if valores is None:
            result.skipped[motivo] += 1
            continue
        result.resolved += 1
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
        result.written += len(db.execute(stmt).fetchall())


def run_backfill(
    limit: Optional[int],
    dry_run: bool,
    batch_size: int = DEFAULT_BATCH_SIZE,
    after_id: int = 0,
) -> BackfillTpResult:
    result = BackfillTpResult(last_id=after_id)
    while limit is None or result.examined < limit:
        take = batch_size if limit is None else min(batch_size, limit - result.examined)
        db = SessionLocal()
        try:
            rows = (
                db.query(MlOrderItemCosto.id, MlOrderItemCosto.producto_item_id, MlOrdersOps.date_created)
                .outerjoin(MlOrdersOps, MlOrdersOps.order_id == MlOrderItemCosto.order_id)
                .filter(MlOrderItemCosto.costo_tp_unitario_ars.is_(None), MlOrderItemCosto.id > result.last_id)
                .order_by(MlOrderItemCosto.id)
                .limit(take)
                .all()
            )
            if not rows:
                break
            _procesar_lote(db, rows, dry_run, result)
            db.commit()
        finally:
            db.close()
        result.examined += len(rows)
        result.batches += 1
        result.last_id = rows[-1].id
        if len(rows) < take:
            break
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fill the NULL TP-Link (list 8) cost of historical sales from the list-8 price "
        "in effect at the sale date. Never rewrites a TP cost already set."
    )
    parser.add_argument("--limit", type=int, default=None, help="Stop after examining this many rows.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Rows per batch and commit.")
    parser.add_argument(
        "--after-id",
        type=int,
        default=0,
        help="Resume after this ml_order_item_costos.id (the last_id of a previous summary).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Resolve and report; write nothing.")
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO)
    args = _build_parser().parse_args(argv)
    result = run_backfill(limit=args.limit, dry_run=args.dry_run, batch_size=args.batch_size, after_id=args.after_id)
    logger.info(
        "backfill_tp_cost: complete (dry_run=%s, limit=%s) -- examined=%s resolved=%s written=%s "
        "batches=%s last_id=%s skipped_total=%s skipped_breakdown=%s",
        args.dry_run,
        args.limit,
        result.examined,
        result.resolved,
        result.written,
        result.batches,
        result.last_id,
        sum(result.skipped.values()),
        dict(result.skipped),
    )


if __name__ == "__main__":
    main()
