"""Queue every sale of every combo once (combos in sell in / sell out, owner 2026-11-05).

From this version a combo's sale counts for its components: it takes their sell-in lots, their cost bonuses and
their sell-out campaigns. Sales stored before it were counted as the combo's own item. This script puts every sale
line of every combo in `combo_componentes` into the `sell_dirty` queue (`sell.queue.enqueue_combos`, the same step a
bill-of-materials change runs), and the `sell.drain` worker re-counts them: the components' FIFO, their cost bonuses
and the sell-out campaigns of both the components and anything still filed under the combo.

Idempotent: a re-run queues the same lines again and the drain writes nothing new. One transaction. Refuses (exit 1,
nothing queued) while the bill of materials is empty: `combos.sync` has not run yet.

Run from `backend/` with `-m` (the settings read `backend/.env` from there):
    cd /var/www/html/pricing-app/backend && ./venv/bin/python -m app.scripts.requeue_combo_sales
"""

from __future__ import annotations

import json
import sys
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.combo_componente import ComboComponente
from app.services.combos.componentes import CombosNoSincronizados, exigir_combos_disponibles
from app.services.sell import queue as sell_queue


def run(session_factory: Callable[[], Session]) -> dict:
    """Queues the sales of every combo; `{"combos": how many combos}`."""
    with session_factory() as db:
        exigir_combos_disponibles(db)
        combos = list(db.scalars(select(ComboComponente.combo_item_id).distinct()))
        sell_queue.enqueue_combos(db, combos)
        db.commit()
    return {"combos": len(combos)}


def main(argv: list[str] | None = None) -> int:
    from app.core import database  # resolved at call time, so tests can point it elsewhere

    try:
        summary = run(database.SessionLocal)
    except CombosNoSincronizados:
        print(json.dumps({"error": "the combo bill of materials is empty: run combos.sync first"}))
        return 1
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
