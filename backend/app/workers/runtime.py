"""`WorkerRuntime` (design D4): the LISTEN/select loop that drives
`registry.REGISTRY` job handlers. PR2 ships this fully generic and wired to
an EMPTY registry -- an idle worker that LISTENs (or safety-polls), drains
nothing, runs no scheduled job, and never crashes.

Loop (design D4 steps 1-5):
1. Open a dedicated listener connection via `DATABASE_URL_DIRECT`
   (bypasses PgBouncer, which does not support LISTEN in transaction mode).
   Unset -> `poll_only` mode, logged once as a WARNING (degraded latency,
   never silent loss).
2. `select()` on the listener socket, timeout = `safety_poll_interval`
   (default 5s). On wake: drain notifies, debounce, run a drain pass. On
   timeout: run a drain pass anyway (safety poll for missed notifies).
3. Startup: one full drain pass before the first LISTEN wait.
4. Listener connection loss -> reconnect with exponential backoff; drain
   immediately after reconnect.
5. A supervised `HeartbeatThread` runs the whole time; if it dies or stalls
   the main loop logs CRITICAL, stops starting new work, and exits(70) so
   systemd (`Restart=always`) restarts the process.
"""

from __future__ import annotations

import json
import logging
import select
import sys
import threading
import time as time_module
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

from sqlalchemy import text

from app.core.config import settings
from app.core.database import get_background_db
from app.workers.context import JobResult, WorkerContext
from app.workers.heartbeat import HeartbeatThread
from app.workers.registry import REGISTRY, JobHandler
from app.workers.scheduling import is_due

logger = logging.getLogger(__name__)

DEFAULT_SAFETY_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_DEBOUNCE_SECONDS = 0.05
DEFAULT_RECONNECT_BACKOFF_SECONDS = 1.0
MAX_RECONNECT_BACKOFF_SECONDS = 30.0
DEFAULT_HANDLER_DEADLINE_SECONDS = 30.0
# `JobResult.detail` larger than this (serialized) is stored as its key count and first keys only:
# `detail.last_result` is a diagnostic breadcrumb, not a second copy of a handler's summary.
MAX_LAST_RESULT_DETAIL_CHARS = 4096
MAX_LAST_RESULT_KEYS = 100

# systemd `Restart=always` treats this as a normal supervised restart, not a
# crash loop (design D4 step 5 "Thread death detection").
HEARTBEAT_DEATH_EXIT_CODE = 70


class WorkerRuntime:
    def __init__(
        self,
        registry: Optional[Iterable[JobHandler]] = None,
        worker_name: str = "worker",
        safety_poll_interval: float = DEFAULT_SAFETY_POLL_INTERVAL_SECONDS,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        direct_url: Optional[str] = None,
        heartbeat_interval: Optional[float] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.registry: List[JobHandler] = list(registry if registry is not None else REGISTRY)
        self.worker_name = worker_name
        self.safety_poll_interval = safety_poll_interval
        self.debounce_seconds = debounce_seconds
        self._direct_url = direct_url if direct_url is not None else settings.DATABASE_URL_DIRECT
        self._heartbeat_interval = heartbeat_interval or settings.WORKER_HEARTBEAT_INTERVAL_SECONDS
        self._stop_event = threading.Event()
        self.heartbeat: Optional[HeartbeatThread] = None
        self._held_tokens: set = set()
        self._draining = False
        # Injectable for tests; every handler's deadline is read from it when that handler STARTS.
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(timezone.utc))

    @property
    def listener_mode(self) -> str:
        """`'notify'` when `DATABASE_URL_DIRECT` is configured (LISTEN
        bypasses PgBouncer, sub-second wake latency); `'poll_only'`
        otherwise (degraded latency, worker still correct via the safety
        poll -- never silent loss, design D4 step 1)."""
        return "notify" if self._direct_url else "poll_only"

    # -- listener connection -------------------------------------------
    def _open_listener_connection(self):
        import psycopg2
        import psycopg2.extensions

        # `DATABASE_URL_DIRECT` is a SQLAlchemy URL (may carry the
        # `+psycopg2` dialect suffix); psycopg2's raw `connect()` only
        # understands a plain `postgresql://` DSN.
        dsn = self._direct_url.replace("postgresql+psycopg2://", "postgresql://", 1)
        conn = psycopg2.connect(dsn)
        conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        channels = sorted({channel for handler in self.registry for channel in handler.channels})
        for channel in channels:
            cur.execute(f"LISTEN {channel}")
        # PR6 (design D10): `worker_jobs` is listened unconditionally, not
        # derived from any handler's own `channels` -- `POST
        # /order-metrics/divergence/run` notifies it regardless of which
        # handlers happen to be registered, so an on-demand trigger wakes
        # the worker even for a schedule-only handler like
        # `order_metrics.divergence` (`channels=()`).
        cur.execute("LISTEN worker_jobs")
        cur.close()
        return conn

    # -- scheduled jobs ---------------------------------------------------
    def _due_handlers(self, now: datetime) -> List[JobHandler]:
        scheduled = [h for h in self.registry if h.interval is not None or h.run_at_local is not None]
        if not scheduled:
            return []
        due: List[JobHandler] = []
        with get_background_db() as db:
            for handler in scheduled:
                row = db.execute(
                    text("SELECT last_success_at, detail FROM worker_job_state WHERE name = :name"),
                    {"name": handler.name},
                ).fetchone()
                last_success_at = row[0] if row else None
                # PR6 review fix J4: a persisted `detail.complete is False`
                # (only ever written by `order_metrics.divergence`'s own
                # run summary) unlocks that handler's `catch_up_interval`
                # in `is_due` -- no previous summary at all is NOT
                # "incomplete" (nothing to catch up on yet, same as a
                # freshly-registered handler).
                detail = row[1] if row and len(row) > 1 else None
                incomplete = bool(detail) and detail.get("complete") is False
                if is_due(handler, now=now, last_success_at=last_success_at, incomplete=incomplete):
                    due.append(handler)
        return due

    def _requested_handlers(self) -> List[JobHandler]:
        """On-demand triggers (design D10): `POST
        /order-metrics/divergence/run` sets `worker_job_state.state
        ='requested'` for one handler's row; this READS (never clears)
        every such flag this worker's registry recognizes and returns the
        matching handlers to run right now, regardless of schedule.
        Postgres-only; on any other dialect (bare unit tests) this is a
        no-op -- no test exercises the requested-flag path outside
        `@pytest.mark.postgres`.

        PR6 review fix J3: this used to clear the flag with an `UPDATE ...
        RETURNING` right here, BEFORE the handler ever ran -- a handler
        that raises, or a process that dies mid-run, silently lost the
        request even though `POST /divergence/run` already answered `202`.
        The flag now only clears in `_clear_requested`, called from
        `drain_once` AFTER the handler's `JobResult.success` is known, so a
        failed or crashed run leaves it `'requested'` for the next drain
        pass to retry -- and a successful run is the only thing that ever
        clears it, so it can never stay stuck forever either."""
        names = {h.name: h for h in self.registry}
        if not names:
            return []
        with get_background_db() as db:
            if db.get_bind().dialect.name != "postgresql":
                return []
            rows = db.execute(
                text("SELECT name FROM worker_job_state WHERE state = 'requested' AND name = ANY(:names)"),
                {"names": list(names.keys())},
            ).fetchall()
        return [names[row[0]] for row in rows if row[0] in names]

    def _clear_requested(self, handler_name: str) -> None:
        """Clears one handler's `'requested'` flag -- called ONLY after
        `_run_handler` reports `success=True` for a handler that was
        picked up via `_requested_handlers` (PR6 review fix J3)."""
        with get_background_db() as db:
            if db.get_bind().dialect.name != "postgresql":
                return
            db.execute(
                text("UPDATE worker_job_state SET state = NULL WHERE state = 'requested' AND name = :name"),
                {"name": handler_name},
            )

    def _run_handler(self, handler: JobHandler) -> bool:
        """Runs one handler with its OWN deadline, measured from the clock at
        the moment it starts -- never from the drain pass's scheduling
        instant: a pass used to share one deadline, so after a handler that
        spent its whole budget every later handler started already expired
        and "succeeded" with zero work (prod, 2026-10-19)."""
        deadline = self._clock() + timedelta(seconds=DEFAULT_HANDLER_DEADLINE_SECONDS)
        ctx = WorkerContext(deadline=deadline, worker_name=self.worker_name, held_tokens=self._held_tokens)
        # PR3.T6a: `worker_job_state.detail.draining` and the heartbeat's
        # lease renewal both key off this flag while a claiming handler runs.
        self._draining = True
        try:
            result = handler.run(ctx)
            success = result.success
        except Exception as exc:  # noqa: BLE001 -- one handler's bug must not kill the loop
            logger.exception("job handler %s raised", handler.name)
            result = JobResult(success=False, error=f"{type(exc).__name__}: {exc}")
            success = False
        finally:
            self._draining = False
        self._record_job_run(handler.name, success, result)
        return success

    @staticmethod
    def _last_result(result: Optional[JobResult], at: datetime) -> Dict[str, Any]:
        """Compact, JSON-safe summary of one run for `detail.last_result`."""
        raw: Any = result.detail if result is not None else None
        try:
            # Total by design: this runs OUTSIDE the handler's try/except, so a detail
            # Postgres JSONB cannot store (NaN, non-string keys, cycles, non-mapping)
            # must degrade to a marker instead of losing the run's bookkeeping.
            detail: Any = dict(raw) if raw else {}
            serialized = json.dumps(detail, default=str, allow_nan=False)
            if len(serialized) > MAX_LAST_RESULT_DETAIL_CHARS:
                keys = sorted(str(key) for key in detail)
                detail = {"truncated": True, "key_count": len(keys), "keys": keys[:MAX_LAST_RESULT_KEYS]}
            else:
                detail = json.loads(serialized)
        except (TypeError, ValueError) as exc:
            detail = {"unserializable": True, "type": type(raw).__name__, "reason": str(exc)[:200]}
        error = result.error if result is not None else None
        return {
            "at": at.isoformat(),
            "success": bool(result.success) if result is not None else False,
            "error": str(error)[:MAX_LAST_RESULT_DETAIL_CHARS] if error is not None else None,
            "detail": detail,
        }

    def _record_job_run(self, handler_name: str, success: bool, result: Optional[JobResult] = None) -> None:
        """Upserts `last_run_at`/`last_success_at` and, on Postgres, merges the
        run's `JobResult` into `detail.last_result`. A merge (`detail ||
        {last_result}`), never a replace: several handlers own their `detail`
        (resume cursors, counters, `complete`), and this runs AFTER they wrote it."""
        now = datetime.now(timezone.utc)
        with get_background_db() as db:
            if db.get_bind().dialect.name == "postgresql":
                from sqlalchemy import cast, func
                from sqlalchemy.dialects.postgresql import JSONB
                from sqlalchemy.dialects.postgresql import insert as pg_insert

                from app.models.worker_job_state import WorkerJobState

                last_result = {"last_result": self._last_result(result, now)}
                values = {"name": handler_name, "last_run_at": now, "detail": last_result}
                if success:
                    values["last_success_at"] = now
                table = WorkerJobState.__table__
                stmt = pg_insert(table).values(**values)
                set_ = {
                    "last_run_at": stmt.excluded.last_run_at,
                    "detail": func.coalesce(table.c.detail, cast({}, JSONB)).op("||")(stmt.excluded.detail),
                }
                if success:
                    set_["last_success_at"] = stmt.excluded.last_success_at
                db.execute(stmt.on_conflict_do_update(index_elements=["name"], set_=set_))
            else:
                db.execute(
                    text(
                        "INSERT INTO worker_job_state (name, last_run_at, last_success_at) "
                        "VALUES (:name, :last_run_at, :last_success_at) "
                        "ON CONFLICT(name) DO UPDATE SET last_run_at = excluded.last_run_at, "
                        "last_success_at = COALESCE(excluded.last_success_at, worker_job_state.last_success_at)"
                    ),
                    {"name": handler_name, "last_run_at": now, "last_success_at": now if success else None},
                )

    # -- one drain pass ----------------------------------------------------
    def drain_once(self, now: Optional[datetime] = None) -> None:
        """Runs every due scheduled handler, PLUS every channel-driven
        handler (design D4 step 2: on wake OR on the safety-poll timeout,
        the notify-driven `order_metrics.drain` runs unconditionally, not
        on a schedule). `now` only decides what is due; each handler's
        deadline comes from the clock when it starts (`_run_handler`). PR2's registry is empty, so this stayed a no-op
        idle pass until PR3 registers `order_metrics.drain`
        (`channels=("order_metrics_dirty",)`, no `interval`/`run_at_local`)."""
        now = now or self._clock()
        due = self._due_handlers(now)
        channel_driven = [h for h in self.registry if h.channels and h.interval is None and h.run_at_local is None]
        requested = self._requested_handlers()
        requested_names = {h.name for h in requested}
        to_run: List[JobHandler] = []
        seen = set()
        for handler in due + channel_driven + requested:
            if handler.name not in seen:
                seen.add(handler.name)
                to_run.append(handler)
        for handler in to_run:
            success = self._run_handler(handler)
            # Only a successful run clears the on-demand request flag
            # (PR6 review fix J3) -- a raise or `success=False` leaves it
            # `'requested'` so the next drain pass retries it.
            if success and handler.name in requested_names:
                self._clear_requested(handler.name)

    # -- heartbeat health check ---------------------------------------------
    def _check_heartbeat_or_die(self) -> None:
        if self.heartbeat is not None and not self.heartbeat.is_healthy():
            logger.critical(
                "heartbeat thread for worker=%s died or stalled -- stopping work and exiting(%d) for systemd to restart",
                self.worker_name,
                HEARTBEAT_DEATH_EXIT_CODE,
            )
            sys.exit(HEARTBEAT_DEATH_EXIT_CODE)

    # -- main loop -----------------------------------------------------
    def run_forever(self) -> None:
        if self.listener_mode == "poll_only":
            logger.warning(
                "DATABASE_URL_DIRECT is not set -- worker '%s' running in poll_only mode "
                "(degraded latency via %ss safety poll; correctness unaffected)",
                self.worker_name,
                self.safety_poll_interval,
            )

        self.heartbeat = HeartbeatThread(
            worker_name=self.worker_name,
            interval=self._heartbeat_interval,
            token_provider=lambda: set(self._held_tokens),
            # PR6 (design D9): the health endpoint reads `listener_mode`
            # straight off this same `detail` JSON -- `notify`/`poll_only`
            # is a property of this running process, never guessed from
            # config alone (a stale `DATABASE_URL_DIRECT` that fails to
            # connect still degrades to poll_only in practice).
            detail_provider=lambda: {"draining": self._draining, "listener_mode": self.listener_mode},
        )
        self.heartbeat.start()

        # Startup: full drain before the first LISTEN wait (design D4 step 3).
        self.drain_once()

        conn = None
        backoff = DEFAULT_RECONNECT_BACKOFF_SECONDS
        try:
            while not self._stop_event.is_set():
                self._check_heartbeat_or_die()

                if self.listener_mode == "notify" and conn is None:
                    try:
                        conn = self._open_listener_connection()
                        backoff = DEFAULT_RECONNECT_BACKOFF_SECONDS
                        # Reconnect after a loss -> drain immediately (design D4 step 4).
                        self.drain_once()
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "worker '%s' listener connection failed -- retrying in %.1fs", self.worker_name, backoff
                        )
                        self._stop_event.wait(backoff)
                        backoff = min(backoff * 2, MAX_RECONNECT_BACKOFF_SECONDS)
                        continue

                if conn is not None:
                    try:
                        ready, _, _ = select.select([conn], [], [], self.safety_poll_interval)
                        if ready:
                            conn.poll()
                            while conn.notifies:
                                conn.notifies.pop()
                            time_module.sleep(self.debounce_seconds)
                    except Exception:  # noqa: BLE001 -- connection dropped mid-select
                        logger.exception("worker '%s' listener connection lost", self.worker_name)
                        try:
                            conn.close()
                        except Exception:  # noqa: BLE001
                            pass
                        conn = None
                        continue
                else:
                    self._stop_event.wait(self.safety_poll_interval)

                self.drain_once()
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
            if self.heartbeat is not None:
                self.heartbeat.stop()
                self.heartbeat.join(timeout=5)

    def stop(self) -> None:
        self._stop_event.set()
