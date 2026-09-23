"""`HeartbeatThread` (design D4 step 5, rev 4) -- a dedicated daemon thread
that proves worker liveness independently of whatever the main loop is
doing inside a handler. REPLACES the rejected rev-3 in-handler heartbeat:
`compute_order_metrics` runs several statements per batch with no
heartbeat inside them, so a live worker computing a big batch could read as
dead and overrun its lease.

Every `interval` seconds (default 5s), in its OWN short `get_background_db()`
block (never the main thread's session):
  (a) upserts `worker_job_state` row `name=worker_name` with `heartbeat_at`
      and `detail` (from `detail_provider()`, e.g. `{"draining": bool}`);
  (b) renews the lease of every claim token this process currently holds
      (`token_provider()` -- empty in PR2, since the registry ships no
      handler that claims anything yet; PR3's drain handler feeds it the
      live claim-token set).

`worker_alive` (health endpoint, PR6) = `now() - heartbeat_at < 30s`, so it
depends ONLY on this thread being alive and ticking, never on batch or
statement duration.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, Optional, Set

from sqlalchemy import text

from app.core.database import get_background_db

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 5.0
# Main loop treats the thread as dead if no tick completed for this many
# intervals (design D4 step 5 "Thread death detection").
DEAD_AFTER_MISSED_INTERVALS = 3


def _default_token_provider() -> Set[str]:
    return set()


def _default_detail_provider() -> Dict[str, object]:
    return {}


class HeartbeatThread(threading.Thread):
    def __init__(
        self,
        worker_name: str = "worker",
        interval: float = DEFAULT_INTERVAL_SECONDS,
        token_provider: Optional[Callable[[], Iterable[str]]] = None,
        detail_provider: Optional[Callable[[], Dict[str, object]]] = None,
    ) -> None:
        super().__init__(name="worker-heartbeat", daemon=True)
        self.worker_name = worker_name
        self.interval = interval
        self._token_provider = token_provider or _default_token_provider
        self._detail_provider = detail_provider or _default_detail_provider
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._last_tick_completed_at: Optional[datetime] = None
        self._last_tick_error: Optional[BaseException] = None
        self._started_at: Optional[datetime] = None

    # -- lifecycle -----------------------------------------------------
    def run(self) -> None:  # pragma: no cover -- exercised via integration tests
        with self._lock:
            self._started_at = datetime.now(timezone.utc)
        while not self._stop_event.is_set():
            try:
                self._tick()
                with self._lock:
                    self._last_tick_completed_at = datetime.now(timezone.utc)
                    self._last_tick_error = None
            except Exception as exc:  # noqa: BLE001 -- must never kill the thread silently
                with self._lock:
                    self._last_tick_error = exc
                logger.exception("heartbeat tick failed for worker=%s", self.worker_name)
            self._stop_event.wait(self.interval)

    def stop(self) -> None:
        self._stop_event.set()

    # -- one tick --------------------------------------------------------
    def _tick(self) -> None:
        tokens = list(self._token_provider())
        detail = self._detail_provider()
        with get_background_db() as db:
            db.execute(text("SET LOCAL statement_timeout = '5s'"))
            db.execute(text("SET LOCAL lock_timeout = '2s'"))
            self._upsert_job_state(db, detail)
            if tokens:
                self._renew_leases(db, tokens)

    def _upsert_job_state(self, db, detail: Dict[str, object]) -> None:
        dialect = db.get_bind().dialect.name
        now = datetime.now(timezone.utc)
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            from app.models.worker_job_state import WorkerJobState

            stmt = pg_insert(WorkerJobState.__table__).values(name=self.worker_name, heartbeat_at=now, detail=detail)
            stmt = stmt.on_conflict_do_update(
                index_elements=["name"],
                set_={"heartbeat_at": stmt.excluded.heartbeat_at, "detail": stmt.excluded.detail},
            )
            db.execute(stmt)
        else:
            # SQLite (unit tests only -- production and @pytest.mark.postgres
            # tests always use the postgresql branch above).
            db.execute(
                text(
                    "INSERT INTO worker_job_state (name, heartbeat_at) VALUES (:name, :heartbeat_at) "
                    "ON CONFLICT(name) DO UPDATE SET heartbeat_at = excluded.heartbeat_at"
                ),
                {"name": self.worker_name, "heartbeat_at": now},
            )

    def _renew_leases(self, db, tokens: Iterable[str]) -> None:
        """Renews `claimed_at` for every dirty row this process still holds,
        fenced by `claim_token` so a renewal can never resurrect a claim
        another worker already took (design D4 step 5). PR2 never calls this
        with a non-empty token set -- PR3's drain handler is the first
        holder of live tokens."""
        db.execute(
            text(
                "UPDATE ml_order_metrics_dirty SET claimed_at = now() "
                "WHERE claimed_by = :worker_name AND claim_token = ANY(CAST(:tokens AS uuid[]))"
            ),
            {"worker_name": self.worker_name, "tokens": list(tokens)},
        )

    # -- liveness, read by the main loop ----------------------------------
    def is_healthy(self, *, now: Optional[datetime] = None) -> bool:
        """`False` when the thread is not running, or has not completed a
        tick for `DEAD_AFTER_MISSED_INTERVALS * interval` -- the main loop's
        cue to log CRITICAL, stop starting work, and exit non-zero (design
        D4 step 5 'Thread death detection')."""
        if not self.is_alive():
            return False
        now = now or datetime.now(timezone.utc)
        with self._lock:
            last_tick = self._last_tick_completed_at
            started_at = self._started_at
        reference = last_tick or started_at
        if reference is None:
            return True  # not started yet
        return (now - reference) < timedelta(seconds=DEAD_AFTER_MISSED_INTERVALS * self.interval)

    @property
    def last_tick_error(self) -> Optional[BaseException]:
        with self._lock:
            return self._last_tick_error
