"""Backfill the per-group metrics record for sales that already exist.

WHY THIS IS NOT OPTIONAL: `ml_group_metrics` rows are written as a SIDE
EFFECT of storing a member order's metrics. Every sale that existed before
this slice already has its per-order metrics, so nothing will ever re-store
them and their group record would never come into being. `GET
/ml-ventas-ops/packs/{pack_id}` reads that record with no live fallback, so
every historical pedido's detail reads as unknown until this runs.

(`GET /sales/kpis` does NOT read it yet -- it still aggregates per-order via
`aggregate_order_metrics`. T28/T29 are what move it over, and until they land
the detail and the KPI can disagree. Stated here rather than left implicit:
the first draft of this docstring already described the destination as if it
had arrived.)

The existing `order_metrics.reconcile` does NOT cover it: it re-enqueues
orders whose `formula_version` is stale or that have no metrics row at all,
and these orders have a current row. Nothing about them is dirty; what is
missing is one level up.

Run this BEFORE the readers are deployed, or accept a window where every
pack's money reads as unknown.

    python -m app.scripts.backfill_ml_group_metrics --dry-run   # cuántos faltan
    python -m app.scripts.backfill_ml_group_metrics             # hacerlo, entero

`--limit` existe para una primera pasada cautelosa, NO para el uso normal:
el trabajo ya se hace de a `--batch-size` grupos por transaccion, asi que
limitar no achica ninguna transaccion, solo hace que la corrida termine a
medias. Toda corrida informa `remaining`, y una que deja algo pendiente lo
dice con un WARNING, para que una pasada parcial no se parezca nunca a una
completa.

Only INSERTs (through the same `recompute_group_metrics`/`store_group_metrics`
the live path uses -- never a second formula that could drift). It removes
nothing, so unlike the repair pass its worst case is extra rows, and
`--dry-run` stays an opt-in flag rather than the default.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.services.ml_group_metrics.compute import recompute_group_metrics  # noqa: E402
from app.services.ml_group_metrics.store import store_group_metrics  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 500

# The group key as `_group_key_expr()` builds it, in SQL: a pack is
# `p:<pack_id>`, a standalone order is `o:<order_id>`. Kept as one statement
# rather than pulling every order into Python -- the point is to find the
# groups that have NO record, not to walk the ones that do.
_MISSING_GROUPS_SQL = """
SELECT DISTINCT
    CASE WHEN o.pack_id IS NOT NULL
         THEN 'p:' || o.pack_id
         ELSE 'o:' || o.order_id
    END AS group_key
FROM ml_orders_ops o
JOIN ml_order_metrics m ON m.order_id = o.order_id
LEFT JOIN ml_group_metrics g
       ON g.group_key = CASE WHEN o.pack_id IS NOT NULL
                             THEN 'p:' || o.pack_id
                             ELSE 'o:' || o.order_id
                        END
WHERE g.group_key IS NULL
ORDER BY 1
"""


def count_missing_groups(db) -> int:
    """How many groups still have NO record, ignoring any `--limit`.

    This is what makes a partial run visible. `--limit` truncates the set of
    groups a pass touches, so without this number a run that covered half
    the work reports exactly the same shape as one that covered all of it --
    and this script is what stands between a deploy and every historical
    pedido reading as unknown.
    """
    return db.execute(text(f"SELECT COUNT(*) FROM ({_MISSING_GROUPS_SQL}) AS faltantes")).scalar() or 0


def missing_group_keys(db, limit: Optional[int]) -> List[str]:
    """Groups with at least one member carrying stored metrics and no record
    of their own. A group whose members have no metrics yet is NOT here: it
    will get its record the ordinary way, when the worker stores them."""
    sql = _MISSING_GROUPS_SQL
    if limit is not None:
        sql = f"{sql} LIMIT {int(limit)}"
    return [row[0] for row in db.execute(text(sql)).all()]


def run_backfill(limit: Optional[int], dry_run: bool, batch_size: int = DEFAULT_BATCH_SIZE) -> dict:
    db = SessionLocal()
    resultado = {"examined": 0, "written": 0, "no_members": 0, "remaining": 0}
    try:
        group_keys = missing_group_keys(db, limit)
        resultado["examined"] = len(group_keys)
        if dry_run:
            # The WHOLE pending set, not what this limited pass would touch:
            # answering "how much is there" is the entire point of a dry run.
            resultado["remaining"] = count_missing_groups(db)
            logger.info(
                "backfill_ml_group_metrics: %s groups WOULD be computed, %s pending in total",
                len(group_keys),
                resultado["remaining"],
            )
            return resultado

        for inicio in range(0, len(group_keys), batch_size):
            lote = group_keys[inicio : inicio + batch_size]
            computados = recompute_group_metrics(db, lote)
            if computados:
                store_group_metrics(db, computados)
            db.commit()
            resultado["written"] += len(computados)
            # NOT a count of `unresolved` records. A group whose members are
            # not all resolvable still GETS a record, an `unresolved` one, and
            # is counted in `written`. What is counted here is the groups
            # `recompute_group_metrics` declined to return at all, because
            # they have no current members. The key was named `unresolved`
            # while the log printed it as `no_members`, which is two names for
            # one number and the wrong one in front.
            resultado["no_members"] += len(lote) - len(computados)

        # Counted AFTER the writes, so it reflects what this run actually
        # left behind. Non-zero means the job is NOT done: run it again.
        resultado["remaining"] = count_missing_groups(db)
        return resultado
    finally:
        db.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after this many groups. For a cautious first pass; the run then reports remaining > 0.",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many groups WOULD be computed; write nothing.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO)
    args = _build_parser().parse_args(argv)
    resultado = run_backfill(limit=args.limit, dry_run=args.dry_run, batch_size=args.batch_size)
    logger.info(
        "backfill_ml_group_metrics: complete (dry_run=%s) -- examined=%s written=%s no_members=%s remaining=%s",
        args.dry_run,
        resultado["examined"],
        resultado["written"],
        resultado["no_members"],
        resultado["remaining"],
    )
    if resultado["remaining"] and not args.dry_run:
        # Loud on purpose: a backfill that stopped early must never look the
        # same as one that finished.
        logger.warning(
            "backfill_ml_group_metrics: NOT DONE -- %s groups still have no record. Run again (without --limit).",
            resultado["remaining"],
        )


if __name__ == "__main__":
    main()
