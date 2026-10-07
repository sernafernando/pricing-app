"""`ml_publications.refresh` (design D1, D10, D12, D17, D19): the disabled outcome, the
claim -> `/items/bulk` -> `apply_fetch` -> `complete` path, counters and the worker wiring.

Postgres only (queue claims, row locks). Every ML body is a real capture served by an
`httpx.MockTransport`; a test that must prove "no ML call" uses a transport that fails the
test on any request.
"""

from __future__ import annotations

import copy
from datetime import datetime, time, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.services.ml_publications import settings_store, store
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import Pacer
from app.services.ml_publications.queue import LANE_MANUAL, EnqueueEntry, enqueue
from app.workers.context import JobResult, WorkerContext
from app.workers.handlers import ml_publications as handlers
from app.workers.runtime import WorkerRuntime
from tests.services.ml_publications.conftest import bulk_call

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


class ScriptedTransport(httpx.BaseTransport):
    """Answers each request with `responder(request, call_number)` and records it."""

    def __init__(self, responder) -> None:
        self.responder = responder
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responder(request, len(self.requests))

    def ids(self) -> list[list[str]]:
        return [r.url.params["ids"].split(",") for r in self.requests]


def json_response(body, status: int = 200, headers=None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers or {})


def bulk_answer(ids: list[str]) -> list[dict]:
    """The real `/items/bulk` elements captured for MLA935110613, MLA934406852 and MLA1; any other
    requested id gets the real MLA1 not-found element (real payload, one field changed: its id)."""
    captured = {e["id"]: e for e in bulk_call("bulk_full")}
    answer = []
    for item_id in ids:
        element = copy.deepcopy(captured.get(item_id) or captured["MLA1"])
        element["id"] = item_id
        answer.append(element)
    return answer


def bulk_responder(request: httpx.Request, call: int) -> httpx.Response:
    return json_response(bulk_answer(request.url.params["ids"].split(",")))


def make_handler(transport: httpx.BaseTransport, *, token_loader=None, pacer: Pacer | None = None):
    loader = token_loader or (lambda: {"access_token": "tok", "expires_epoch": 9e12})

    def factory(pacer_: Pacer) -> MlHttpClient:
        return MlHttpClient(pacer=pacer_, transport=transport, token_loader=loader)

    return handlers.RefreshHandler(client_factory=factory, pacer=pacer or Pacer(clock=FakeClock()))


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


def sql_all(engine, statement: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(statement), params).mappings().all()


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


def enable_refresh(**other_settings) -> None:
    settings_store.set_setting("refresh.enabled", True, "test")
    for key, value in other_settings.items():
        settings_store.set_setting(key.replace("__", "."), value, "test")


def counters_of(engine) -> dict:
    return sql_scalar(engine, "SELECT detail FROM worker_job_state WHERE name = :n", n=HANDLER_NAME)["counters"]


class TestRefreshCorePath:
    def test_one_bulk_request_applies_two_items_and_records_the_third_as_never_existed(self, env) -> None:
        enable_refresh()
        enqueue_items("MLA935110613", "MLA934406852", "MLA1")
        transport = ScriptedTransport(bulk_responder)

        result = make_handler(transport).run(context())

        assert result.success is True
        assert len(transport.requests) == 1
        request = transport.requests[0]
        assert request.url.path == "/items/bulk"  # never the legacy /items?ids=
        assert set(request.url.params) == {"ids"}  # never attributes=
        assert sorted(transport.ids()[0]) == ["MLA1", "MLA934406852", "MLA935110613"]
        rows = {r["item_id"]: r for r in sql_all(env, "SELECT item_id, raw, never_existed, gone_at FROM ml_items")}
        assert rows["MLA935110613"]["raw"]["id"] == "MLA935110613"
        assert rows["MLA934406852"]["raw"]["id"] == "MLA934406852"
        assert rows["MLA1"]["raw"] is None and rows["MLA1"]["never_existed"] is True
        assert sql_scalar(env, "SELECT count(*) FROM ml_pub_refresh_queue") == 0

    def test_45_items_are_requested_in_batches_of_20_20_and_5(self, env) -> None:
        enable_refresh()
        ids = [f"MLA{n}" for n in range(100, 145)]
        enqueue_items(*ids)
        transport = ScriptedTransport(bulk_responder)

        result = make_handler(transport).run(context())

        assert result.success is True
        assert [len(batch) for batch in transport.ids()] == [20, 20, 5]
        assert sorted(i for batch in transport.ids() for i in batch) == sorted(ids)
        assert sql_scalar(env, "SELECT count(*) FROM ml_pub_refresh_queue") == 0

    def test_a_malformed_response_applies_nothing_and_requeues_with_the_error(self, env) -> None:
        enable_refresh()
        enqueue_items("MLA935110613", "MLA934406852", "MLA1")
        transport = ScriptedTransport(lambda r, n: json_response(bulk_answer(["MLA935110613", "MLA934406852"])))

        result = make_handler(transport).run(context())

        assert result.success is True  # the batch failed, the handler did not
        assert sql_scalar(env, "SELECT count(*) FROM ml_items") == 0
        for item in ("MLA935110613", "MLA934406852", "MLA1"):
            row = queue_row(env, item)
            assert row["attempts"] == 1 and "malformed" in row["last_error"]
            assert row["claimed_at"] is None and row["not_before"] > datetime.now(timezone.utc)

    def test_one_failing_element_charges_only_that_item(self, env) -> None:
        """Synthetic transport fault (the capture has no 5xx element): element status 503."""
        enable_refresh()
        enqueue_items("MLA935110613", "MLA934406852")

        def responder(request, call):
            answer = bulk_answer(request.url.params["ids"].split(","))
            for element in answer:
                if element["id"] == "MLA934406852":
                    element.pop("body")
                    element["status_code"] = 503
            return json_response(answer)

        make_handler(ScriptedTransport(responder)).run(context())

        assert queue_row(env, "MLA935110613") is None  # applied and completed
        failed = queue_row(env, "MLA934406852")
        assert failed["attempts"] == 1 and failed["claimed_at"] is None
        assert sql_scalar(env, "SELECT http_status FROM ml_items WHERE item_id = 'MLA934406852'") == 503

    def test_entries_complete_only_after_the_store_write_committed(self, env, monkeypatch) -> None:
        enable_refresh()
        enqueue_items("MLA935110613", "MLA934406852")
        seen: dict[str, tuple] = {}
        original = store.apply_fetch

        def spy(spec, key, response, **kwargs):
            seen[key[0]] = (queue_row(env, key[0]) is not None, sql_scalar(env, "SELECT count(*) FROM ml_items"))
            return original(spec, key, response, **kwargs)

        monkeypatch.setattr(store, "apply_fetch", spy)

        make_handler(ScriptedTransport(bulk_responder)).run(context())

        assert all(queued for queued, _ in seen.values())  # still queued while applying
        assert queue_row(env, "MLA935110613") is None and queue_row(env, "MLA934406852") is None

    def test_the_events_flag_is_read_with_the_batch_settings_and_passed_to_the_store(self, env, monkeypatch) -> None:
        enable_refresh(events__enabled=True)
        enqueue_items("MLA935110613")
        passed = []
        original = store.apply_fetch

        def spy(spec, key, response, **kwargs):
            passed.append(kwargs.get("events_enabled"))
            return original(spec, key, response, **kwargs)

        monkeypatch.setattr(store, "apply_fetch", spy)

        make_handler(ScriptedTransport(bulk_responder)).run(context())

        assert passed == [True]

    def test_the_links_flag_is_read_with_the_batch_settings_and_links_the_fetched_item(self, env) -> None:
        from app.models.producto import ProductoERP

        ProductoERP.__table__.create(bind=env)
        with env.begin() as conn:
            conn.execute(text("INSERT INTO productos_erp (item_id, codigo) VALUES (41, '6932391923481')"))
        enable_refresh(links__enabled=True)
        enqueue_items("MLA935110613")

        make_handler(ScriptedTransport(bulk_responder)).run(context())

        assert (
            sql_scalar(env, "SELECT producto_item_id FROM ml_item_product_links WHERE item_id = 'MLA935110613'") == 41
        )

    def test_the_links_flag_is_passed_to_the_store_so_it_does_not_read_it_per_fetch(self, env, monkeypatch) -> None:
        enable_refresh(links__enabled=True)
        enqueue_items("MLA935110613")
        passed = []
        original = store.apply_fetch

        def spy(spec, key, response, **kwargs):
            passed.append(kwargs.get("links_enabled"))
            return original(spec, key, response, **kwargs)

        monkeypatch.setattr(store, "apply_fetch", spy)

        make_handler(ScriptedTransport(bulk_responder)).run(context())

        assert passed == [True]

    def test_with_links_off_the_fetch_leaves_the_link_table_empty(self, env) -> None:
        enable_refresh()
        enqueue_items("MLA935110613")

        make_handler(ScriptedTransport(bulk_responder)).run(context())

        assert sql_scalar(env, "SELECT count(*) FROM ml_item_product_links") == 0

    def test_the_store_runs_no_settings_query_when_the_handler_passes_the_flag(self, env, monkeypatch) -> None:
        enable_refresh(events__enabled=True)
        enqueue_items("MLA935110613")

        def boom(_handler):
            raise AssertionError("apply_fetch must not read the events flag itself")

        monkeypatch.setattr(store.settings_store, "is_enabled", boom)

        make_handler(ScriptedTransport(bulk_responder)).run(context())

        assert queue_row(env, "MLA935110613") is None  # applied, nothing charged

    def test_a_flag_change_takes_effect_at_the_next_batch_boundary(self, env, monkeypatch) -> None:
        enable_refresh(bulk_max_ids=1)
        enqueue_items("MLA935110613", "MLA934406852")
        passed = []
        original = store.apply_fetch

        def spy(spec, key, response, **kwargs):
            passed.append(kwargs.get("events_enabled"))
            outcome = original(spec, key, response, **kwargs)
            settings_store.set_setting("events.enabled", True, "test")  # flipped while the run is in flight
            return outcome

        monkeypatch.setattr(store, "apply_fetch", spy)

        make_handler(ScriptedTransport(bulk_responder)).run(context())

        assert passed == [False, True]

    def test_a_store_failure_for_one_item_is_charged_to_that_item_only(self, env, monkeypatch) -> None:
        enable_refresh()
        enqueue_items("MLA935110613", "MLA934406852")
        original = store.apply_fetch

        def flaky(spec, key, response, **kwargs):
            if key[0] == "MLA934406852":
                raise RuntimeError("lock timeout")
            return original(spec, key, response, **kwargs)

        monkeypatch.setattr(store, "apply_fetch", flaky)

        make_handler(ScriptedTransport(bulk_responder)).run(context())

        assert queue_row(env, "MLA935110613") is None
        row = queue_row(env, "MLA934406852")
        assert row["attempts"] == 1 and "lock timeout" in row["last_error"]

    def test_a_whole_batch_server_error_charges_every_entry_with_backoff(self, env) -> None:
        """Synthetic transport fault: HTTP 503 for the whole call."""
        enable_refresh()
        enqueue_items("MLA935110613", "MLA934406852")
        transport = ScriptedTransport(lambda r, n: json_response({"message": "unavailable"}, status=503))

        result = make_handler(transport).run(context())

        assert result.success is True
        assert len(transport.requests) == 1  # a failed batch is not retried within the run
        for item in ("MLA935110613", "MLA934406852"):
            row = queue_row(env, item)
            assert row["attempts"] == 1 and row["not_before"] > datetime.now(timezone.utc)

    def test_a_poison_entry_parks_after_max_attempts_and_stays_visible(self, env) -> None:
        enable_refresh()
        enqueue_items("MLA935110613")
        with env.begin() as conn:
            conn.execute(text("UPDATE ml_pub_refresh_queue SET attempts = :a"), {"a": settings.ML_PUB_MAX_ATTEMPTS - 1})
        transport = ScriptedTransport(lambda r, n: json_response({"message": "boom"}, status=500))

        make_handler(transport).run(context())

        row = queue_row(env, "MLA935110613")
        assert row["parked_at"] is not None and "HTTP 500" in row["last_error"]
        assert make_handler(ScriptedTransport(bulk_responder)).run(context()).success is True
        assert queue_row(env, "MLA935110613")["parked_at"] is not None  # never claimed again

    def test_manual_lane_is_served_before_backfill(self, env) -> None:
        enable_refresh(bulk_max_ids=1)
        enqueue_items("MLA935110613", lane=3)
        enqueue_items("MLA934406852", lane=1)
        transport = ScriptedTransport(bulk_responder)

        make_handler(transport).run(context())

        assert transport.ids() == [["MLA934406852"], ["MLA935110613"]]

    def test_turning_the_flag_off_mid_run_stops_claiming_at_the_next_batch(self, env) -> None:
        enable_refresh(bulk_max_ids=1)
        enqueue_items("MLA935110613", "MLA934406852")

        def responder(request, call):
            settings_store.set_setting("refresh.enabled", False, "test")
            return bulk_responder(request, call)

        transport = ScriptedTransport(responder)
        result = make_handler(transport).run(context())

        assert len(transport.requests) == 1
        assert result.detail.get("stopped") == "disabled"
        waiting = [i for i in ("MLA935110613", "MLA934406852") if queue_row(env, i)]
        assert len(waiting) == 1
        row = queue_row(env, waiting[0])
        assert (row["claimed_at"], row["attempts"]) == (None, 0)

    def test_a_run_whose_deadline_already_passed_claims_nothing(self, env) -> None:
        enable_refresh()
        enqueue_items("MLA935110613")
        transport = NoCallTransport()

        make_handler(transport).run(context(seconds=-1))

        assert queue_row(env, "MLA935110613")["claimed_at"] is None

    def test_pacing_that_would_cross_the_deadline_releases_the_claims_uncharged(self, env) -> None:
        enable_refresh()
        enqueue_items("MLA935110613", "MLA934406852")
        pacer = Pacer(clock=FakeClock())
        pacer.on_rate_limited("120")  # a 120 s cooldown: the wait crosses the 30 s deadline
        transport = NoCallTransport()

        make_handler(transport, pacer=pacer).run(context())

        for item in ("MLA935110613", "MLA934406852"):
            row = queue_row(env, item)
            assert (row["claimed_at"], row["attempts"]) == (None, 0)

    def test_a_second_401_releases_uncharged_and_fails_the_run(self, env) -> None:
        enable_refresh()
        enqueue_items("MLA935110613")
        reads: list[int] = []

        def loader():
            reads.append(1)
            return {"access_token": "tok", "expires_epoch": 9e12}

        transport = ScriptedTransport(lambda r, n: json_response({"message": "invalid token"}, status=401))

        result = make_handler(transport, token_loader=loader).run(context())

        assert result.success is False and result.detail["error"] == "unauthorized"
        assert len(reads) == 2 and len(transport.requests) == 2  # one token re-read, one retry
        row = queue_row(env, "MLA935110613")
        assert (row["claimed_at"], row["attempts"]) == (None, 0)

    def test_a_429_releases_uncharged_with_the_retry_after_cooldown_and_stops(self, env) -> None:
        enable_refresh(bulk_max_ids=1)
        enqueue_items("MLA935110613", "MLA934406852")
        transport = ScriptedTransport(
            lambda r, n: json_response({"message": "too many"}, status=429, headers={"Retry-After": "30"})
        )

        make_handler(transport).run(context())

        assert len(transport.requests) == 1
        released = [queue_row(env, i) for i in ("MLA935110613", "MLA934406852")]
        throttled = [r for r in released if r["not_before"] > datetime.now(timezone.utc) + timedelta(seconds=20)]
        assert len(throttled) == 1 and throttled[0]["attempts"] == 0 and throttled[0]["claimed_at"] is None
        assert sum(1 for r in released if r["claimed_at"] is None and r["attempts"] == 0) == 2


class TestResourcesThatCannotRun:
    def test_unfetchable_resources_are_dropped_uncharged_and_counted(self, env) -> None:
        enable_refresh()
        enqueue_items("MLA935110613", resources=("core", "description", "promotions"))
        transport = ScriptedTransport(bulk_responder)

        make_handler(transport).run(context())

        assert len(transport.requests) == 1
        assert queue_row(env, "MLA935110613") is None  # completed: nothing left, nothing charged
        counters = counters_of(env)
        assert counters["skipped_no_fetcher"] == {"promotions": 1}  # no fetcher yet
        assert counters["skipped_disabled"] == {"description": 1}  # has one, not in `bundle_resources`

    def test_an_entry_naming_only_unfetchable_resources_makes_no_ml_call(self, env) -> None:
        enable_refresh()
        enqueue_items("MLA935110613", resources=("description",))
        transport = NoCallTransport()

        make_handler(transport).run(context())

        assert queue_row(env, "MLA935110613") is None
        assert counters_of(env)["skipped_disabled"] == {"description": 1}

    def test_the_bundle_fetches_the_core_and_counts_each_enabled_resource_it_cannot_fetch(self, env) -> None:
        enable_refresh(bundle_resources=["core", "promotions"])
        enqueue_items("MLA935110613", resources=("bundle",))

        make_handler(ScriptedTransport(bulk_responder)).run(context())

        assert queue_row(env, "MLA935110613") is None
        assert sql_scalar(env, "SELECT raw->>'id' FROM ml_items WHERE item_id = 'MLA935110613'") == "MLA935110613"
        assert counters_of(env)["skipped_no_fetcher"] == {"promotions": 1}


class TestCounters:
    def test_counters_are_flushed_per_endpoint_and_outcome_and_accumulate_across_runs(self, env) -> None:
        enable_refresh()
        handler = make_handler(ScriptedTransport(bulk_responder))
        enqueue_items("MLA935110613", "MLA1")
        handler.run(context())
        first = counters_of(env)
        enqueue_items("MLA934406852")
        handler.run(context())
        second = counters_of(env)

        assert first["endpoints"]["items_bulk"] == {"2xx": 1}
        assert second["endpoints"]["items_bulk"] == {"2xx": 2}
        assert first["elements"] == {"200": 1, "404": 1, "failed": 0}
        assert second["elements"] == {"200": 2, "404": 1, "failed": 0}
        assert (first["stale_discarded"], first["noise_suppressed"]) == (0, 0)

    def test_a_stale_answer_is_counted(self, env) -> None:
        """Real payload, one field changed: the second answer's `last_updated` is a day older."""
        enable_refresh()
        handler = make_handler(ScriptedTransport(bulk_responder))
        enqueue_items("MLA935110613")
        handler.run(context())

        def older(request, call):
            answer = bulk_answer(["MLA935110613"])
            last = datetime.fromisoformat(answer[0]["body"]["last_updated"].replace("Z", "+00:00"))
            answer[0]["body"]["last_updated"] = (last - timedelta(days=1)).isoformat().replace("+00:00", ".000Z")
            return json_response(answer)

        handler._client_factory = lambda pacer: MlHttpClient(
            pacer=pacer,
            transport=ScriptedTransport(older),
            token_loader=lambda: {"access_token": "t", "expires_epoch": 9e12},
        )
        handler._client = None
        enqueue_items("MLA935110613")
        handler.run(context())

        assert counters_of(env)["stale_discarded"] == 1

    def test_counter_flush_keeps_the_runtime_owned_columns(self, env) -> None:
        enable_refresh()
        handler = make_handler(ScriptedTransport(bulk_responder))
        runtime = WorkerRuntime(registry=[handler], direct_url=None)
        enqueue_items("MLA935110613")

        assert runtime._run_handler(handler, datetime.now(timezone.utc)) is True

        row = sql_one(env, "SELECT * FROM worker_job_state WHERE name = :n", n=HANDLER_NAME)
        assert row["last_success_at"] is not None and row["detail"]["counters"]["endpoints"]["items_bulk"] == {"2xx": 1}
