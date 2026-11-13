"""`ml_promotions.hay_mejores_boundaries`: re-run the "hay mejores ofertas" flag when time alone changes it.

Only candidates applicable right now count (`candidata_aplicable_ahora`). A candidate whose start date arrives, or
the only better one expiring, gets no sync event, so this schedule-only handler (every `interval`, no cron, in the ML
publications worker) re-runs `actualizar_hay_mejores_ofertas` for the items with a candidate whose start or finish
date fell between its last checked instant and now: never a full rescan of the flags. The read is the stored mirror
(no ML call).

Catch-up: when `RULES_VERSION` is newer than the one stored, the handler first recomputes every item whose flag the
new rules can change (flagged, or with a discarded fingerprint), once, in id order. That replaces the one-off
`recompute_hay_mejores_ofertas` script after a rules change.

Runs in its own thread of the ML worker (`own_thread`): a catch-up of up to `deadline_seconds` never delays the
other handlers of the drain pass. Single-flight: a run takes the session advisory lock `RUN_LOCK_KEY` on a connection
of its own for its whole length and skips the tick when another process (or a manual run) holds it.

State (merged into `worker_job_state.detail`, every other key kept):
    {rules_version, checked_until, window_until, cursor, catchup_started_at}
A run stopped by its deadline keeps `cursor` (the last item id done) and its window, and the next run resumes there;
the recompute is idempotent, so a window done twice changes nothing.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.core import database
from app.models.ml_publications import MlItemSellerPromotions
from app.models.worker_job_state import WorkerJobState
from app.services import ml_promotions_hay_mejores as hay_mejores
from app.services.ml_promotions_pricing import resolver_sell_in_out_para_mlas
from app.workers.context import JobResult, WorkerContext

logger = logging.getLogger(__name__)

HANDLER_NAME = "ml_promotions.hay_mejores_boundaries"
# Bump when the rules of the flag change: the next run recomputes the flags that can change, once.
# 1 = applicable-now rule (writable type, started, not finished, SELLER_CAMPAIGN Premium of the month).
RULES_VERSION = 1
BATCH = 100
# Session advisory lock: one run at a time across processes (next free key of the 84_217_xxx family).
RUN_LOCK_KEY = 84_217_006


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_state(db: Session) -> Dict[str, Any]:
    row = db.get(WorkerJobState, HANDLER_NAME)
    detail = row.detail if row is not None else None
    return dict(detail) if isinstance(detail, dict) else {}


def _write_state(db: Session, state: Dict[str, Any]) -> None:
    """Merge `state` into `worker_job_state.detail`, keeping every other key (the runtime's `last_result`)."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text(
                "INSERT INTO worker_job_state (name, detail) VALUES (:name, CAST(:detail AS jsonb)) "
                "ON CONFLICT (name) DO UPDATE SET "
                "detail = COALESCE(worker_job_state.detail, '{}'::jsonb) || EXCLUDED.detail"
            ),
            {"name": HANDLER_NAME, "detail": json.dumps(state)},
        )
        return
    row = db.get(WorkerJobState, HANDLER_NAME)
    if row is None:
        db.add(WorkerJobState(name=HANDLER_NAME, detail=dict(state)))
    else:
        row.detail = {**(row.detail or {}), **state}


def _parse(value: Any) -> Optional[datetime]:
    return datetime.fromisoformat(value) if isinstance(value, str) and value else None


def _catchup_ids(db: Session, after: Optional[str]) -> List[str]:
    """Items whose flag the new rules can change: flagged, or holding a discarded fingerprint."""
    query = db.query(MlItemSellerPromotions.item_id).filter(
        or_(
            MlItemSellerPromotions.hay_mejores_ofertas.is_(True),
            MlItemSellerPromotions.hay_mejores_descartado_fingerprint.isnot(None),
        )
    )
    if after:
        query = query.filter(MlItemSellerPromotions.item_id > after)
    return [row[0] for row in query.order_by(MlItemSellerPromotions.item_id).all()]


def _recompute(db: Session, item_ids: List[str], now: datetime) -> int:
    """One batch: one sell in / sell out read, the flag of each id at `now`. Returns the flags that changed."""
    batch = resolver_sell_in_out_para_mlas(db, item_ids)
    rows = db.query(MlItemSellerPromotions).filter(MlItemSellerPromotions.item_id.in_(item_ids)).all()
    before = {row.item_id: bool(row.hay_mejores_ofertas) for row in rows}
    changed = 0
    for item_id in item_ids:
        decision = hay_mejores.actualizar_hay_mejores_ofertas(db, item_id, sell_in_out_batch=batch, now=now)
        if decision is not None and decision.hay_mejores != before.get(item_id, False):
            changed += 1
    return changed


def _try_lock(db: Session) -> bool:
    """Take the run's session advisory lock; the session keeps its connection (open transaction) until `_unlock`.
    Not Postgres (SQLite unit tests): no other process to exclude."""
    if db.get_bind().dialect.name != "postgresql":
        return True
    return bool(db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": RUN_LOCK_KEY}).scalar())


def _unlock(db: Session) -> None:
    """Release it on the SAME connection before the session hands that connection back to the pool."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": RUN_LOCK_KEY})


class HayMejoresBoundariesHandler:
    """`JobHandler`: the flags whose candidates crossed a start or finish date since the last run."""

    name = HANDLER_NAME
    channels: tuple[str, ...] = ()
    interval: Optional[timedelta] = timedelta(minutes=5)
    run_at_local: Optional[time] = None
    deadline_seconds = 120
    # Its own thread (like `ml_publications.core_first` / `ml_orders.discounts`): never in the drain pass.
    own_thread = True

    def __init__(
        self,
        *,
        session_factory: Optional[Callable[[], Any]] = None,
        now: Callable[[], datetime] = _now,
    ) -> None:
        self._session_factory = session_factory
        self._now = now

    def _session(self) -> Any:
        return (self._session_factory or database.get_background_db)()

    def run(self, ctx: WorkerContext) -> JobResult:
        try:
            with self._session() as lock_db:
                if not _try_lock(lock_db):
                    logger.info("%s: another run holds the lock, tick skipped", HANDLER_NAME)
                    return JobResult(success=True, detail={"skipped": "locked"})
                try:
                    return self._run(ctx)
                finally:
                    _unlock(lock_db)
        except Exception as exc:  # noqa: BLE001 - a failed run is reported, the next tick retries it
            logger.warning("%s: run failed: %s", HANDLER_NAME, exc)
            return JobResult(success=False, error=f"{type(exc).__name__}: {exc}")

    def _run(self, ctx: WorkerContext) -> JobResult:
        now = self._now()
        with self._session() as db:
            state = _read_state(db)
            catchup = state.get("rules_version") != RULES_VERSION or _parse(state.get("checked_until")) is None
            if catchup:
                started = _parse(state.get("catchup_started_at"))
                # A cursor belongs to the catch-up only when one is under way (never to an unfinished window).
                ids = _catchup_ids(db, state.get("cursor") if started is not None else None)
                started = started or now
                window: Dict[str, Any] = {"catchup_started_at": started.isoformat()}
            else:
                since = _parse(state["checked_until"])
                until = _parse(state.get("window_until")) or now
                cursor = state.get("cursor")
                ids = [
                    i for i in hay_mejores.items_con_candidatas_que_cruzan(db, since, until) if not cursor or i > cursor
                ]
                window = {"window_until": until.isoformat()}
            db.rollback()  # the selection holds no lock while the batches run

        done = changed = 0
        for start in range(0, len(ids), BATCH):
            if ctx.stop_requested() or self._now() >= ctx.deadline:
                return self._stopped(window, ids[start - 1] if start else state.get("cursor"), done, changed, catchup)
            chunk = ids[start : start + BATCH]
            with self._session() as db:
                changed += _recompute(db, chunk, self._now())
                _write_state(db, {**window, "cursor": chunk[-1]})
                db.commit()
            done += len(chunk)

        with self._session() as db:
            if catchup:
                final = {
                    "rules_version": RULES_VERSION,
                    "checked_until": window["catchup_started_at"],
                    "catchup_started_at": None,
                }
            else:
                final = {"checked_until": window["window_until"]}
            _write_state(db, {**final, "window_until": None, "cursor": None})
            db.commit()
        if changed:
            logger.info("%s: recomputed=%s changed=%s catchup=%s", HANDLER_NAME, done, changed, catchup)
        return JobResult(success=True, detail={"recomputed": done, "changed": changed, "catchup": catchup})

    @staticmethod
    def _stopped(window: Dict[str, Any], cursor: Optional[str], done: int, changed: int, catchup: bool) -> JobResult:
        """Deadline or stop: the window and cursor are already stored, the next run resumes after `cursor`."""
        return JobResult(
            success=True,
            detail={"recomputed": done, "changed": changed, "catchup": catchup, "complete": False, "cursor": cursor},
        )


boundaries = HayMejoresBoundariesHandler()
