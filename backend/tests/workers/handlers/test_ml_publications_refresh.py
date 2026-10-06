"""`ml_publications.refresh` (design D1, D10, D12, D17, D19): the disabled outcome, the
claim -> `/items/bulk` -> `apply_fetch` -> `complete` path, counters and the worker wiring.

Postgres only (queue claims, row locks). Every ML body is a real capture served by an
`httpx.MockTransport`; a test that must prove "no ML call" uses a transport that fails the
test on any request.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_publications import settings_store
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import Pacer
from app.services.ml_publications.queue import LANE_MANUAL, EnqueueEntry, enqueue
from app.workers.context import JobResult, WorkerContext
from app.workers.handlers import ml_publications as handlers
from app.workers.runtime import WorkerRuntime

pytestmark = pytest.mark.postgres

HANDLER_NAME = "ml_publications.refresh"


class NoCallTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        pytest.fail(f"unexpected ML call: {request.url}")


class FakeClock:
    """Pacing never really sleeps in these tests."""

    def __init__(self) -> None:
        self.t = 1000.0

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


def make_handler(transport: httpx.BaseTransport) -> handlers.RefreshHandler:
    def factory(pacer: Pacer) -> MlHttpClient:
        return MlHttpClient(
            pacer=pacer,
            transport=transport,
            token_loader=lambda: {"access_token": "tok", "expires_epoch": 9e12},
        )

    return handlers.RefreshHandler(client_factory=factory, pacer=Pacer(clock=FakeClock()))


def context(seconds: float = 30.0) -> WorkerContext:
    return WorkerContext(deadline=datetime.now(timezone.utc) + timedelta(seconds=seconds), worker_name="worker-ml")


@pytest.fixture()
def env(mlpub_pg, monkeypatch):
    """The real core schema plus `worker_job_state`, with ML credentials configured."""
    with mlpub_pg.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE worker_job_state (name varchar(64) PRIMARY KEY, last_run_at timestamptz, "
                "last_success_at timestamptz, state varchar(32), detail jsonb, heartbeat_at timestamptz)"
            )
        )
    monkeypatch.setattr(settings, "ML_USER_ID", "1")
    monkeypatch.setattr(settings, "ML_CLIENT_ID", "1")
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)
    return mlpub_pg


def sql_one(engine, statement: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(statement), params).mappings().first()


def sql_scalar(engine, statement: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(statement), params).scalar()


def queue_row(engine, item: str):
    return sql_one(engine, "SELECT * FROM ml_pub_refresh_queue WHERE entity_id = :i", i=item)


def enqueue_items(*ids: str, lane: int = LANE_MANUAL, resources=("bundle",)) -> None:
    enqueue([EnqueueEntry(kind="item", entity_id=i, lane=lane, resources=tuple(resources)) for i in ids])


class TestDisabledOutcome:
    def test_all_flags_off_makes_no_call_no_write_and_reports_disabled(self, env) -> None:
        enqueue_items("MLA935110613")
        transport = NoCallTransport()
        result = make_handler(transport).run(context())

        assert result == JobResult(success=False, detail={"disabled": True})
        assert transport.requests == []
        row = queue_row(env, "MLA935110613")
        assert (row["claimed_at"], row["attempts"], row["parked_at"]) == (None, 0, None)
        assert sql_scalar(env, "SELECT count(*) FROM ml_items") == 0
        assert sql_scalar(env, "SELECT count(*) FROM ml_change_log") == 0
        assert sql_scalar(env, "SELECT count(*) FROM worker_job_state") == 0

    def test_kill_switch_overrides_a_db_enabled_row(self, env, monkeypatch) -> None:
        settings_store.set_setting("refresh.enabled", True, "test")
        enqueue_items("MLA935110613")
        monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)
        transport = NoCallTransport()

        result = make_handler(transport).run(context())

        assert result == JobResult(success=False, detail={"disabled": True})
        assert queue_row(env, "MLA935110613")["claimed_at"] is None

    def test_a_settings_table_that_cannot_be_read_fails_closed(self, env) -> None:
        settings_store.set_setting("refresh.enabled", True, "test")
        with env.begin() as conn:
            conn.execute(text("ALTER TABLE ml_pub_settings RENAME TO ml_pub_settings_gone"))
        transport = NoCallTransport()

        result = make_handler(transport).run(context())

        assert result == JobResult(success=False, detail={"disabled": True})

    def test_the_runtime_does_not_consume_the_slot_of_a_disabled_handler(self, env) -> None:
        handler = make_handler(NoCallTransport())
        runtime = WorkerRuntime(registry=[handler], direct_url=None)
        now = datetime.now(timezone.utc)

        assert runtime._run_handler(handler, now) is False

        row = sql_one(env, "SELECT * FROM worker_job_state WHERE name = :n", n=HANDLER_NAME)
        assert row["last_run_at"] is not None
        assert row["last_success_at"] is None
        assert runtime._due_handlers(now) == [handler]

    def test_a_daily_handler_enabled_after_its_slot_is_due_on_the_next_pass(self, env) -> None:
        class DailyStub:
            name = "ml_publications.stub_daily"
            channels: tuple = ()
            interval = None
            run_at_local = time(3, 30)

            def run(self, ctx: WorkerContext) -> JobResult:
                return handlers.disabled_outcome()

        stub = DailyStub()
        runtime = WorkerRuntime(registry=[stub], direct_url=None)
        after_the_slot = datetime(2026, 10, 6, 17, 0, tzinfo=timezone.utc)  # 14:00 Argentina

        assert runtime._run_handler(stub, after_the_slot) is False

        assert runtime._due_handlers(after_the_slot + timedelta(seconds=10)) == [stub]

    def test_a_pending_request_flag_stays_set_while_disabled(self, env) -> None:
        with env.begin() as conn:
            conn.execute(
                text("INSERT INTO worker_job_state (name, state) VALUES (:n, 'requested')"), {"n": HANDLER_NAME}
            )
        handler = make_handler(NoCallTransport())
        runtime = WorkerRuntime(registry=[handler], direct_url=None)

        runtime.drain_once()

        assert sql_scalar(env, "SELECT state FROM worker_job_state WHERE name = :n", n=HANDLER_NAME) == "requested"
