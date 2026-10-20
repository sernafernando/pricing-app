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
(`list_history.pick_history_row`) and the list-8 metrics job:
the most recent row dated at or before the sale that carries a REAL price
(`> 0`) -- a zero row is an ERP hole, not a free product.

List 8 only started being used on 2026-06-26, so most historical sales
predate every list-8 row (owner decision, measured on prod). Such a sale --
no real price at or before its date, but real prices later -- is costed with
the item's FIRST real list-8 price, still converted at the SALE-DATE rate,
and stamped `lista8_primer_precio` (`lista8_primer_precio_combo` when any
component of a combo took it) so it can be shown as approximate. An item
that never had a real list-8 price is not in TP's catalog: it stays NULL
and is counted as `fuera_catalogo_tp`, apart from the real problems.
Exact always beats approximate: a combo's exact component sum at the sale
wins over its own first price (order in `tp_cost_resolver._resolver`).

The resolver itself lives in `services/ml_orders_ingestion/tp_cost_resolver.py`,
shared with the late-load worker. Same rules as `congelar()` otherwise, and anything that cannot be resolved
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
from pathlib import Path
from typing import List, Optional

backend_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(backend_path))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(dotenv_path=backend_path / ".env")

from app.core.database import SessionLocal  # noqa: E402
from app.models.ml_order_item_costo import MlOrderItemCosto  # noqa: E402
from app.models.ml_orders_ops import MlOrdersOps  # noqa: E402
from app.services.ml_orders_ingestion.tp_cost_resolver import BackfillTpResult, procesar_lote  # noqa: E402
from app.services.combos.componentes import CombosNoSincronizados  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 500


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
            procesar_lote(db, rows, dry_run, result)
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
    try:
        result = run_backfill(
            limit=args.limit, dry_run=args.dry_run, batch_size=args.batch_size, after_id=args.after_id
        )
    except CombosNoSincronizados as exc:
        sys.exit(f"ERROR: {exc}")
    logger.info(
        "backfill_tp_cost: complete (dry_run=%s, limit=%s) -- examined=%s resolved=%s written=%s "
        "batches=%s last_id=%s resolved_by_fuente=%s written_by_fuente=%s skipped_total=%s skipped_breakdown=%s",
        args.dry_run,
        args.limit,
        result.examined,
        result.resolved,
        result.written,
        result.batches,
        result.last_id,
        dict(result.resolved_by_fuente),
        dict(result.written_by_fuente),
        sum(result.skipped.values()),
        dict(result.skipped),
    )


if __name__ == "__main__":
    main()
