"""`sell_in.bono` (sell-in-sell-out T3c-3): drains `sell_in_bono_dirty` and
reconciles the purchases the brand bonuses generate (`bonos.reconciliar`). No
cron: the queue's triggers `pg_notify('sell_in_bono_dirty')`.

Each batch is ONE short `get_background_db()` transaction:

1. claim up to `bono_queue.BATCH_SIZE` keys (`FOR UPDATE SKIP LOCKED`, so
   concurrent drains split the queue);
2. reconcile the claimed bonuses and operations together (the reconcile takes
   its own per-bonus and per-product locks and recomputes the consumptions);
3. ack the keys; a key involved in a pair that failed (no rate to convert a USD
   bonus) is charged (`attempts`/`last_error`) instead, is not claimed again in
   this run and parks after `bono_queue.MAX_ATTEMPTS` until a new change
   re-queues it.

An error that aborts the whole batch would otherwise make every wake claim the
same batch again, so the batch is retried one key per transaction and only the
key that still fails is charged, in its own transaction, while it is still the
version claimed. A transient infrastructure error (`sell_drain.is_transient`),
even while charging, charges nothing: the run stops, keeping its counters, and
the next wake retries. Errors are kept to `ERROR_MAX` chars, stored and logged.

Wired like `sell.drain`: `channels=("sell_in_bono_dirty",)` with no
`interval`/`run_at_local`, so `WorkerRuntime.drain_once` runs it on every LISTEN
wake and every safety poll; an empty queue costs one query.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy.orm import Session

from app.core.database import get_background_db
from app.services.sell_in import bono_queue, bonos, bonos_costo
from app.workers.context import JobResult, WorkerContext
from app.workers.handlers.sell_drain import is_transient

logger = logging.getLogger(__name__)

Key = bono_queue.Key
ERROR_MAX = 500  # chars of an error kept in `last_error` and in the log lines


def _cap(error: str) -> str:
    return error[:ERROR_MAX]


def _reconciliar(db: Session, keys: Sequence[Key]) -> Tuple[bonos.ReconcileResult, Dict[Key, str], List[Key]]:
    """Reconciles the claimed keys, acks them and charges the ones in a failed pair. Does not commit."""
    result = bonos.reconciliar(
        db,
        bono_ids=[ref for tipo, ref in keys if tipo == "bono"],
        pedido_ids=[ref for tipo, ref in keys if tipo == "pedido"],
    )
    # T25b: a % of cost bonus never generates a purchase (the reconcile skips it); its sales are recomputed here,
    # a voided or edited one included. A bonus whose recompute fails charges its key.
    costo = bonos_costo.recalcular(db, bono_ids=[ref for tipo, ref in keys if tipo == "bono"])
    failed: Dict[Key, str] = {("bono", bono_id): error for bono_id, error in costo.bonos_fallidos.items()}
    failed = {key: error for key, error in failed.items() if key in keys}
    for (bono_id, pedido_id), error in result.fallidas.items():
        for key in (("bono", bono_id), ("pedido", pedido_id)):
            if key in keys:
                failed[key] = f"{failed[key]}; {error}" if key in failed else error
    failed = {key: _cap(error) for key, error in failed.items()}
    parked = bono_queue.settle(db, [k for k in keys if k not in failed], failed)
    return result, failed, parked


def _log_parked(parked: Sequence[Key], errors: Dict[Key, str]) -> None:
    for key in parked:
        logger.error(
            "sell_in.bono: %s/%s parked after %s attempts; retried only when it changes again: %s",
            key[0],
            key[1],
            bono_queue.MAX_ATTEMPTS,
            errors[key],
        )


class SellInBonoHandler:
    """`JobHandler` for `sell_in.bono`."""

    name = "sell_in.bono"
    channels: Tuple[str, ...] = (bono_queue.CHANNEL,)
    interval: Optional[timedelta] = None
    run_at_local: Optional[time] = None

    def run(self, ctx: WorkerContext) -> JobResult:
        detail = {"keys": 0, "batches": 0, "creadas": 0, "actualizadas": 0, "anuladas": 0, "failed": 0}
        failed_keys: Set[Key] = set()
        while datetime.now(timezone.utc) < ctx.deadline:
            claimed: List[Key] = []
            try:
                with get_background_db() as db:
                    if db.get_bind().dialect.name != "postgresql":
                        break  # the queue, its triggers and SKIP LOCKED are Postgres-only
                    claimed = bono_queue.claim_batch(db, bono_queue.BATCH_SIZE, excluded=failed_keys)
                    if not claimed:
                        break
                    result, failed, parked = _reconciliar(db, claimed)
                _log_parked(parked, failed)  # only once the charges are committed
                results = [result]
                stopped = False
            except Exception as exc:
                if is_transient(exc):
                    logger.warning("sell_in.bono: transient error, nothing charged; the next wake retries: %s", exc)
                    break
                if not claimed:
                    raise  # nothing was claimed: not a key's fault
                logger.exception("sell_in.bono: batch of %s key(s) failed; retrying it key by key", len(claimed))
                results, failed, stopped = _one_by_one(claimed, ctx.deadline)
            failed_keys.update(failed)
            detail["keys"] += len(claimed)
            detail["batches"] += 1
            detail["failed"] += len(failed)
            for result in results:
                detail["creadas"] += result.creadas
                detail["actualizadas"] += result.actualizadas
                detail["anuladas"] += result.anuladas
            if failed:
                # Keys only: each key's (capped) error was already logged where it failed.
                logger.warning("sell_in.bono: %s key(s) failed: %s", len(failed), sorted(failed))
            if stopped or len(claimed) < bono_queue.BATCH_SIZE:
                break
        return JobResult(success=True, detail=detail)


def _one_by_one(claimed: Sequence[Key], deadline: datetime) -> Tuple[List[bonos.ReconcileResult], Dict[Key, str], bool]:
    """Retries a batch that failed as a whole, one key per transaction; the third value is True when a
    transient error stopped it (the remaining keys stay queued, untouched)."""
    results: List[bonos.ReconcileResult] = []
    failed: Dict[Key, str] = {}
    for key in claimed:
        if datetime.now(timezone.utc) >= deadline:
            break
        version: Optional[datetime] = None
        try:
            with get_background_db() as db:
                version = bono_queue.claim_one(db, key)
                if version is None:
                    continue  # acked, parked or taken by another drain meanwhile
                result, key_failed, parked = _reconciliar(db, [key])
            _log_parked(parked, key_failed)
            results.append(result)
            failed.update(key_failed)
        except Exception as exc:
            if is_transient(exc):
                logger.warning("sell_in.bono: transient error on %s, nothing charged; stopping: %s", key, exc)
                return results, failed, True
            if version is None:
                raise  # failed before the key was claimed: not its fault
            logger.exception("sell_in.bono: %s failed", key)
            error = _cap(f"{type(exc).__name__}: {exc}")
            try:
                with get_background_db() as db:
                    attempts = bono_queue.charge(db, key, error, version)
            except Exception as charge_exc:
                if is_transient(charge_exc):
                    logger.warning(
                        "sell_in.bono: transient error charging %s, nothing charged; stopping: %s", key, charge_exc
                    )
                    return results, failed, True
                raise
            if attempts is not None:
                failed[key] = error
                if attempts >= bono_queue.MAX_ATTEMPTS:
                    _log_parked([key], failed)
    return results, failed, False


bono = SellInBonoHandler()
