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

import logging
import select
import sys
import threading
import time as time_module
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

from sqlalchemy import text

from app.core.config import settings
from app.core.database import get_background_db
from app.workers.context import WorkerContext
from app.workers.heartbeat import HeartbeatThread
from app.workers.registry import REGISTRY, JobHandler
from app.workers.scheduling import is_due

logger = logging.getLogger(__name__)

DEFAULT_SAFETY_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_DEBOUNCE_SECONDS = 0.05
DEFAULT_RECONNECT_BACKOFF_SECONDS = 1.0
MAX_RECONNECT_BACKOFF_SECONDS = 30.0
DEFAULT_HANDLER_DEADLINE_SECONDS = 30.0

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
                    text("SELECT last_success_at FROM worker_job_state WHERE name = :name"), {"name": handler.name}
                ).fetchone()
                last_success_at = row[0] if row else None
                if is_due(handler, now=now, last_success_at=last_success_at):
                    due.append(handler)
        return due

    def _run_handler(self, handler: JobHandler, now: datetime) -> None:
        deadline = now + timedelta(seconds=DEFAULT_HANDLER_DEADLINE_SECONDS)
        ctx = WorkerContext(deadline=deadline, worker_name=self.worker_name)
        try:
            result = handler.run(ctx)
            success = result.success
        except Exception:  # noqa: BLE001 -- one handler's bug must not kill the loop
            logger.exception("job handler %s raised", handler.name)
            success = False
        self._record_job_run(handler.name, success)

    def _record_job_run(self, handler_name: str, success: bool) -> None:
        now = datetime.now(timezone.utc)
        with get_background_db() as db:
            if db.get_bind().dialect.name == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as pg_insert

                from app.models.worker_job_state import WorkerJobState

                values = {"name": handler_name, "last_run_at": now}
                if success:
                    values["last_success_at"] = now
                stmt = pg_insert(WorkerJobState.__table__).values(**values)
                set_ = {"last_run_at": stmt.excluded.last_run_at}
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
        """Runs every due scheduled handler. PR2's registry is empty, so
        this is a no-op idle pass -- PR3 adds `order_metrics.drain` as a
        channel-notified (not schedule-only) handler; its notify dispatch
        is wired in `run_forever` below via the listener's channel wake,
        which currently has no registered channel handler to call either."""
        now = now or datetime.now(timezone.utc)
        for handler in self._due_handlers(now):
            self._run_handler(handler, now)

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
            detail_provider=lambda: {"draining": self._draining},
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
