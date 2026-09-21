"""One-off repair for payments ML finished refunding AFTER we asked
(ml-ventas-repreguntar-pagos-diferido).

Production incident this closes: order 2000018524489386's Flex shipping
charge was reversed by ML a few seconds after the order's own
`ml_last_updated` stopped moving, so our stored `ml_payment_charges` row
still carries `refunded=0` while ML's live payment now reports the
reversal. `sweep_service`'s new `payments_recheck_at` gate (RECHECK_AFTER
= 60 minutes) prevents this going forward for orders synced after this
script ships; this script is the one-time catch-up for the 59 payments
already affected in production.

Candidate selection (bulk, ONE query -- never one query per order, see
`costeo_service._productos_por_item`'s docstring for the rule this
repeats): a payment whose `MlPaymentOps.status == 'refunded'` and that
has at least one `MlPaymentCharge` row with `refunded == 0` and
`amount > 0` -- exactly the shape the production incident exhibited (five
charges refunded correctly, one charge left at `refunded=0`).

For each candidate this script re-fetches the LIVE payment from ML and
calls the SAME `upsert_payment` the sweep uses, which replaces the whole
charge set for that payment in one transaction
(`ml_payments_ingestion/ingestion_service.py`'s replace-set discipline) --
so a charge ML now reports as refunded is corrected, and one still
unrefunded is left exactly as it was (never zeroed, never guessed).

The report counts CHARGES ACTUALLY CHANGED (refunded value before !=
after), not payments sent -- that measured number is what tells us
whether 60 minutes is the right `RECHECK_AFTER` window.

No cap on candidates: a backfill has to cover the whole affected set. A
cap would truncate silently, and re-running would not advance, because a
payment ML still reports unrefunded stays a candidate and keeps taking the
first slots of the payment_id ordering.

Run:
    python -m app.scripts.repair_deferred_refunds --dry-run
    python -m app.scripts.repair_deferred_refunds
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Agregar path del backend
backend_path = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(backend_path))

from dotenv import load_dotenv  # noqa: E402

env_path = backend_path / ".env"
load_dotenv(dotenv_path=env_path)

from app.core.database import get_background_db  # noqa: E402
from app.models.ml_payments import MlPaymentCharge, MlPaymentOps  # noqa: E402
from app.services.ml_payments_ingestion.ingestion_service import upsert_payment  # noqa: E402
from app.services.ml_payments_ingestion.mapper import MappingError, map_payment  # noqa: E402
from app.services.ml_webhook_client import ml_webhook_client  # noqa: E402
from app.utils.async_bridge import resolve_maybe_async  # noqa: E402

logger = logging.getLogger(__name__)


@dataclass
class RepairResult:
    dry_run: bool
    candidates_found: int = 0
    payments_processed: int = 0
    payments_fetch_failed: int = 0
    payments_mapping_error: int = 0
    payments_write_failed: int = 0
    charges_changed: int = 0
    charges_unchanged: int = 0
    # PAYMENTS, not charges. One payment whose six charges all reversed is
    # ONE late reversal, and this is the number `RECHECK_AFTER` has to be
    # judged against -- counting charges would make a handful of
    # multi-charge payments look like a wave.
    payments_changed: int = 0
    changed_payment_ids: List[int] = field(default_factory=list)


def _find_candidate_payment_ids() -> List[int]:
    """ONE query: every distinct `payment_id` whose payment is `refunded`
    and carries at least one charge with `refunded == 0` against a
    positive `amount` -- the exact shape of the production incident."""
    with get_background_db() as db:
        rows = (
            db.query(MlPaymentOps.payment_id)
            .join(MlPaymentCharge, MlPaymentCharge.payment_id == MlPaymentOps.payment_id)
            .filter(
                MlPaymentOps.status == "refunded",
                MlPaymentCharge.refunded == 0,
                MlPaymentCharge.amount > 0,
            )
            .distinct()
            .order_by(MlPaymentOps.payment_id)
            .all()
        )
    return [payment_id for (payment_id,) in rows]


def _charge_snapshot(payment_ids: List[int]) -> Dict[Tuple[int, str, str], object]:
    """Bulk snapshot of every existing charge for these payments, keyed on
    `(payment_id, name, type)` -- the same key `_dedup_charges` uses, and
    stable across the replace-set upsert even though the underlying row
    `id` is not (old rows are deleted and reinserted with fresh ids)."""
    if not payment_ids:
        return {}
    with get_background_db() as db:
        rows = (
            db.query(
                MlPaymentCharge.payment_id,
                MlPaymentCharge.name,
                MlPaymentCharge.type,
                MlPaymentCharge.refunded,
            )
            .filter(MlPaymentCharge.payment_id.in_(payment_ids))
            .all()
        )
    return {(payment_id, name, charge_type): refunded for payment_id, name, charge_type, refunded in rows}


def run_repair(dry_run: bool = False) -> RepairResult:
    result = RepairResult(dry_run=dry_run)

    candidate_ids = _find_candidate_payment_ids()
    result.candidates_found = len(candidate_ids)
    if not candidate_ids:
        return result

    if dry_run:
        logger.info(
            "repair_deferred_refunds: dry-run, %s candidate payment(s), no HTTP calls, no writes", len(candidate_ids)
        )
        return result

    before = _charge_snapshot(candidate_ids)

    for payment_id in candidate_ids:
        try:
            payload = resolve_maybe_async(ml_webhook_client.get_payment(payment_id))
        except Exception:
            logger.warning("repair_deferred_refunds: payment fetch failed for payment_id=%s", payment_id, exc_info=True)
            result.payments_fetch_failed += 1
            continue
        if not isinstance(payload, dict):
            result.payments_fetch_failed += 1
            continue

        mapped = map_payment(payload)
        if isinstance(mapped, MappingError):
            logger.warning("repair_deferred_refunds: mapping error for payment_id=%s: %s", payment_id, mapped.reason)
            result.payments_mapping_error += 1
            continue

        # Guarded like the fetch above. Without this, one payment that
        # fails to persist ends the whole run and every candidate after it
        # is never repaired -- and the summary still reads like a clean
        # finish, just with a smaller number. Each payment already writes
        # in its own session, so a failure here costs only that payment.
        try:
            with get_background_db() as db:
                upsert_payment(db, mapped)
        except Exception:
            logger.exception("repair_deferred_refunds: write failed for payment_id=%s", payment_id)
            result.payments_write_failed += 1
            continue
        result.payments_processed += 1

    after = _charge_snapshot(candidate_ids)

    # What changed is measured from the DB, not from ML's response --
    # this is the number that tells us whether 60 minutes is the right
    # `RECHECK_AFTER` window, and it must reflect what was actually
    # persisted, never what was merely sent.
    all_keys = set(before) | set(after)
    changed_payments: Set[int] = set()
    for key in all_keys:
        if before.get(key) != after.get(key):
            result.charges_changed += 1
            changed_payments.add(key[0])
        else:
            result.charges_unchanged += 1
    result.payments_changed = len(changed_payments)
    result.changed_payment_ids = sorted(changed_payments)

    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="One-off repair: re-fetch payments ML finished refunding after our last "
        "look, and correct the stored charges that now report a refund."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count candidates and log them; make zero HTTP calls and zero writes.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    args = _build_parser().parse_args(argv)

    result = run_repair(dry_run=args.dry_run)

    logger.info(
        "repair_deferred_refunds: complete (dry_run=%s) -- "
        "candidates_found=%s payments_processed=%s payments_fetch_failed=%s "
        "payments_mapping_error=%s payments_write_failed=%s "
        "payments_changed=%s charges_changed=%s charges_unchanged=%s",
        result.dry_run,
        result.candidates_found,
        result.payments_processed,
        result.payments_fetch_failed,
        result.payments_mapping_error,
        result.payments_write_failed,
        result.payments_changed,
        result.charges_changed,
        result.charges_unchanged,
    )
    if result.changed_payment_ids:
        logger.info("repair_deferred_refunds: payment_ids with a changed charge: %s", result.changed_payment_ids)

    # A run that could not process every candidate must NOT look clean
    # from the outside. The per-payment guards are there so one bad
    # payment does not end the run -- not so the run can report success
    # while leaving candidates unrepaired. `$?` is the only signal a
    # cron, a chained command or a person reading the shell ever sees.
    # Both kinds exit non-zero -- unfinished work is unfinished either way
    # -- but they need DIFFERENT things from whoever reads this, so the
    # message must not tell one to do the other's remedy. A fetch or write
    # failure is transient and a re-run picks it up; a mapping error is
    # deterministic, so re-running produces the identical failure and what
    # it actually needs is somebody looking at the payload.
    retryable = result.payments_fetch_failed + result.payments_write_failed
    if retryable:
        logger.error(
            "repair_deferred_refunds: %s candidate(s) failed transiently (fetch=%s write=%s); re-run to pick them up",
            retryable,
            result.payments_fetch_failed,
            result.payments_write_failed,
        )
    if result.payments_mapping_error:
        logger.error(
            "repair_deferred_refunds: %s candidate(s) could not be mapped; re-running will fail the same way, "
            "these payloads need a look",
            result.payments_mapping_error,
        )
    if retryable or result.payments_mapping_error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
