"""RED/GREEN -- every handler in a drain pass gets its OWN deadline, and a
handler's `JobResult` is visible in `worker_job_state.detail`.

Prod, 2026-10-19 (`pricing-worker-ml`): `drain_once` took `now` once and
`_run_handler` derived every deadline from it, so the whole pass shared ONE
30 s deadline. `ml_publications.refresh` (first, with a backlog) used all of
it; every later handler started past its deadline, did zero work and still
reported `success=True` -- invisible, because `_record_job_run` never
persisted `JobResult.detail`.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.workers import runtime as runtime_module
from app.workers.context import JobResult, WorkerContext
from app.workers.runtime import DEFAULT_HANDLER_DEADLINE_SECONDS, WorkerRuntime


class _FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


class _RecordingHandler:
    """Channel-driven (no schedule), so `drain_once` runs it on every pass in registry order."""

    def __init__(self, name: str, on_run=None, result: Optional[JobResult] = None) -> None:
        self.name = name
        self.channels: tuple = ("test_channel",)
        self.interval = None
        self.run_at_local = None
        self.contexts: List[WorkerContext] = []
        self.started_at: List[datetime] = []
        self._on_run = on_run
        self._result = result or JobResult(success=True)

    def run(self, ctx: WorkerContext) -> JobResult:
        self.contexts.append(ctx)
        self.started_at.append(datetime.now(timezone.utc))
        if self._on_run is not None:
            self._on_run(ctx)
        return self._result


@pytest.fixture()
def pg_runtime_db(monkeypatch, pg_worker_engine):
    session_factory = sessionmaker(bind=pg_worker_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.core.database.SessionLocal", session_factory)
    with pg_worker_engine.begin() as conn:
        conn.execute(text("DELETE FROM worker_job_state"))
    yield pg_worker_engine
    with pg_worker_engine.begin() as conn:
        conn.execute(text("DELETE FROM worker_job_state"))


def _detail(engine, name: str) -> dict:
    with engine.connect() as conn:
        found = conn.execute(text("SELECT detail FROM worker_job_state WHERE name = :n"), {"n": name}).scalar()
    return found or {}


@pytest.mark.postgres
class TestEachHandlerGetsItsOwnDeadline:
    def test_a_handler_after_a_slow_one_gets_a_full_deadline_from_the_injected_clock(self, pg_runtime_db) -> None:
        clock = _FakeClock(datetime(2026, 10, 19, 14, 36, tzinfo=timezone.utc))
        budget = timedelta(seconds=DEFAULT_HANDLER_DEADLINE_SECONDS)

        def consume_the_whole_budget(ctx: WorkerContext) -> None:
            clock.now = ctx.deadline + timedelta(seconds=1)

        slow = _RecordingHandler("ml_publications.refresh", on_run=consume_the_whole_budget)
        second = _RecordingHandler("ml_publications.promo_refresh")
        runtime = WorkerRuntime(registry=[slow, second], direct_url=None, clock=clock)

        pass_start = clock.now
        runtime.drain_once()

        assert slow.contexts[0].deadline == pass_start + budget
        second_start = pass_start + budget + timedelta(seconds=1)
        assert second.contexts[0].deadline == second_start + budget

    def test_regression_a_shared_pass_deadline_leaves_the_second_handler_none(self, monkeypatch, pg_runtime_db) -> None:
        """Real wall clock, tiny budget: under the old shared deadline the second
        handler started AFTER its deadline, so its `while now < ctx.deadline` loop
        never ran."""
        monkeypatch.setattr(runtime_module, "DEFAULT_HANDLER_DEADLINE_SECONDS", 0.2)

        def sleep_past_the_budget(ctx: WorkerContext) -> None:
            while datetime.now(timezone.utc) < ctx.deadline:
                time.sleep(0.02)

        slow = _RecordingHandler("ml_publications.refresh", on_run=sleep_past_the_budget)
        second = _RecordingHandler("ml_publications.missed_feeds")
        WorkerRuntime(registry=[slow, second], direct_url=None).drain_once()

        assert second.contexts[0].deadline > second.started_at[0]
        assert second.contexts[0].deadline > slow.contexts[0].deadline

    def test_scheduling_still_uses_the_pass_now(self, monkeypatch, pg_runtime_db) -> None:
        clock = _FakeClock(datetime(2026, 10, 19, 14, 36, tzinfo=timezone.utc))
        seen: List[datetime] = []
        runtime = WorkerRuntime(registry=[], direct_url=None, clock=clock)
        monkeypatch.setattr(runtime, "_due_handlers", lambda now: seen.append(now) or [])

        runtime.drain_once()
        explicit = datetime(2026, 10, 19, 3, 0, tzinfo=timezone.utc)
        runtime.drain_once(now=explicit)

        assert seen == [clock.now, explicit]


@pytest.mark.postgres
class TestJobResultDetailIsPersisted:
    def test_a_zero_work_run_is_visible_in_detail(self, pg_runtime_db) -> None:
        result = JobResult(success=True, detail={"stopped": "deadline", "pages": 0})
        handler = _RecordingHandler("ml_publications.missed_feeds", result=result)
        WorkerRuntime(registry=[handler], direct_url=None).drain_once()

        last = _detail(pg_runtime_db, handler.name)["last_result"]
        assert last["success"] is True
        assert last["detail"] == {"stopped": "deadline", "pages": 0}
        assert last["error"] is None
        assert datetime.fromisoformat(last["at"])

    def test_a_handler_managed_detail_is_kept_and_last_result_is_merged_in(self, pg_runtime_db) -> None:
        name = "ml_publications.refresh"

        def write_own_detail(ctx: WorkerContext) -> None:
            with pg_runtime_db.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO worker_job_state (name, detail) VALUES (:n, CAST(:d AS jsonb)) "
                        "ON CONFLICT (name) DO UPDATE SET detail = EXCLUDED.detail"
                    ),
                    {"n": name, "d": json.dumps({"counters": {"fetched": 7}, "complete": False})},
                )

        result = JobResult(success=False, detail={"fetched": 7}, error="boom")
        handler = _RecordingHandler(name, on_run=write_own_detail, result=result)
        WorkerRuntime(registry=[handler], direct_url=None).drain_once()

        detail = _detail(pg_runtime_db, name)
        assert detail["counters"] == {"fetched": 7}
        assert detail["complete"] is False
        assert detail["last_result"]["success"] is False
        assert detail["last_result"]["error"] == "boom"
        assert detail["last_result"]["detail"] == {"fetched": 7}

    def test_an_oversized_detail_is_stored_compactly(self, pg_runtime_db) -> None:
        big = {f"key_{i}": "x" * 200 for i in range(100)}
        handler = _RecordingHandler("ml_publications.scan", result=JobResult(success=True, detail=big))
        WorkerRuntime(registry=[handler], direct_url=None).drain_once()

        stored = _detail(pg_runtime_db, handler.name)["last_result"]["detail"]
        assert stored["truncated"] is True
        assert stored["keys"] == sorted(big)

    def test_a_raising_handler_records_the_error(self, pg_runtime_db) -> None:
        def explode(ctx: WorkerContext) -> None:
            raise RuntimeError("kaput")

        handler = _RecordingHandler("ml_publications.relink", on_run=explode)
        WorkerRuntime(registry=[handler], direct_url=None).drain_once()

        last = _detail(pg_runtime_db, handler.name)["last_result"]
        assert last["success"] is False
        assert "kaput" in last["error"]


class TestLastResultNeverBreaksBookkeeping:
    """`_last_result` runs outside the handler's try/except, so ANY detail a
    handler returns must still yield a storable summary -- otherwise the run
    loses its `last_run_at` write and the rest of the pass is aborted."""

    AT = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)

    @pytest.mark.parametrize(
        "detail",
        [
            {"ratio": float("nan")},
            {"ratio": float("inf")},
            {("a", 1): "tuple key"},
            [("not", "a"), ("mapping",)],
        ],
        ids=["nan", "infinity", "tuple-key", "not-a-mapping"],
    )
    def test_an_unstorable_detail_degrades_to_a_marker(self, detail) -> None:
        summary = WorkerRuntime._last_result(JobResult(success=True, detail=detail), self.AT)

        assert summary["success"] is True
        assert summary["detail"]["unserializable"] is True
        json.dumps(summary, allow_nan=False)

    def test_a_circular_detail_degrades_to_a_marker(self) -> None:
        detail: dict = {}
        detail["self"] = detail

        summary = WorkerRuntime._last_result(JobResult(success=True, detail=detail), self.AT)

        assert summary["detail"]["unserializable"] is True

    def test_the_summary_is_bounded_however_many_keys_and_however_long_the_error(self) -> None:
        detail = {f"key_{i:05d}": 1 for i in range(5000)}
        result = JobResult(success=False, detail=detail, error="e" * 50_000)

        summary = WorkerRuntime._last_result(result, self.AT)

        assert summary["detail"]["truncated"] is True
        assert summary["detail"]["key_count"] == 5000
        assert len(json.dumps(summary)) <= 2 * runtime_module.MAX_LAST_RESULT_DETAIL_CHARS
        assert summary["error"].startswith("e")


@pytest.mark.postgres
class TestUnstorableDetailStillRecordsTheRun:
    def test_a_nan_detail_records_the_run_and_the_pass_goes_on(self, pg_runtime_db) -> None:
        first = _RecordingHandler("ml_publications.refresh", result=JobResult(success=True, detail={"r": float("nan")}))
        second = _RecordingHandler("ml_publications.scan", result=JobResult(success=True, detail={"pages": 1}))
        WorkerRuntime(registry=[first, second], direct_url=None).drain_once()

        assert _detail(pg_runtime_db, first.name)["last_result"]["detail"]["unserializable"] is True
        assert _detail(pg_runtime_db, second.name)["last_result"]["detail"] == {"pages": 1}
