"""P12.T1: the status report of the ML publications store (`status.build_status`).

Postgres only (real migrations' tables in a throwaway schema). The report is read only: it never calls ML and
never writes. Every case below inserts the rows it reads with SQL, so the numbers asserted are the ones put in.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.ml_publications import settings_store, status
from app.services.ml_publications.ml_http import MlHttpClient
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401

pytestmark = pytest.mark.postgres

WORKER_STATE_DDL = (
    "CREATE TABLE worker_job_state (name varchar(64) PRIMARY KEY, last_run_at timestamptz, "
    "last_success_at timestamptz, state varchar(32), detail jsonb, heartbeat_at timestamptz)"
)


@pytest.fixture()
def store(mlpub_pg, monkeypatch):  # noqa: F811
    """Every table the report reads, empty: the store's own, `worker_job_state` and the product catalog."""
    from app.models.producto import ProductoERP

    ProductoERP.__table__.create(bind=mlpub_pg)
    with mlpub_pg.begin() as conn:
        conn.execute(text(WORKER_STATE_DDL))
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)

    def no_ml(*args, **kwargs):
        pytest.fail("the status report must not call ML")

    monkeypatch.setattr(MlHttpClient, "get", no_ml)
    return mlpub_pg


def run(engine, sql: str, **params) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def scalar(engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def report(engine) -> dict:
    session = sessionmaker(bind=engine)()
    try:
        return status.build_status(session)
    finally:
        session.close()


def job_of(result: dict, name: str) -> dict:
    return next(job for job in result["jobs"] if job["job"] == name)


def put_item(engine, item_id: str, *, state: str = "active", checked: str | None = "0 seconds", **columns) -> None:
    """One stored item; `checked` is how long ago it was last checked (None: never)."""
    values = {"item_id": item_id, "status": state, "http_status": 200, **columns}
    names = ", ".join(values)
    marks = ", ".join(f":{name}" for name in values)
    run(engine, f"INSERT INTO ml_items ({names}) VALUES ({marks})", **values)
    if checked is not None:
        run(
            engine,
            "UPDATE ml_items SET last_checked_at = now() - CAST(:ago AS interval) WHERE item_id = :i",
            ago=checked,
            i=item_id,
        )


def put_state(engine, name: str, **columns) -> None:
    values = {"name": name, **columns}
    for key in ("detail",):
        if key in values:
            values[key] = json.dumps(values[key])
    names = ", ".join(values)
    marks = ", ".join("CAST(:detail AS jsonb)" if key == "detail" else f":{key}" for key in values)
    run(engine, f"INSERT INTO worker_job_state ({names}) VALUES ({marks})", **values)


class TestEmptyStore:
    def test_returns_zeros_and_nulls_not_an_error(self, store) -> None:
        result = report(store)

        assert result["sections_failed"] == []
        assert result["kill_switch"] is False
        assert result["items"] == {"total": 0, "with_raw": 0, "gone": 0, "by_status": {}}
        assert result["queue"]["parked"] == [] and result["queue"]["parked_total"] == 0
        assert all(
            lane["waiting"] == 0 and lane["oldest_waiting_age_seconds"] is None for lane in result["queue"]["lanes"]
        )
        assert result["intake"]["cursors"] == [] and result["intake"]["stalled"] is False
        assert result["backfill"] == []
        assert result["missed_feeds"] == {
            "last_success_at": None,
            "age_seconds": None,
            "last_run": None,
            "coverage_gap": None,
        }
        assert result["sweep"] == {"last_run": None}
        assert result["freshness"]["items"] == {
            "rows": 0,
            "checked": 0,
            "p50_age_seconds": None,
            "p95_age_seconds": None,
            "max_age_seconds": None,
        }
        assert result["lag_p95_seconds_24h"] is None and result["lag_samples_24h"] == 0
        assert result["completeness"]["description"]["missing"] == 0
        assert result["completeness"]["description"]["non_2xx"] == {}
        assert result["counters"]["stale_discarded"] == 0 and result["counters"]["requests_429"] == 0
        assert result["events"]["by_type"] == {} and result["events"]["newest_age_seconds"] is None
        assert result["links"]["coverage"]["total_units"] == 0
        assert result["top_changed_paths"] == []

    def test_every_handler_is_listed_off_and_never_run(self, store) -> None:
        result = report(store)

        assert [job["job"] for job in result["jobs"]] == [
            "refresh",
            "intake",
            "relink",
            "scan",
            "missed_feeds",
            "sweep",
        ]
        for job in result["jobs"]:
            assert (job["enabled"], job["disabled"], job["failing"]) == (False, True, False)
            assert (job["last_run_at"], job["last_success_at"], job["last_error"]) == (None, None, None)
        assert result["flags"]["refresh"] is False and result["flags"]["events"] is False


class TestJobs:
    def test_enabled_state_and_last_run_come_from_the_flag_and_the_worker_row(self, store) -> None:
        settings_store.set_setting("refresh.enabled", True, "test")
        put_state(store, "ml_publications.refresh", state="requested")
        run(
            store,
            "UPDATE worker_job_state SET last_run_at = now() - interval '1 minute', "
            "last_success_at = now() - interval '1 minute' WHERE name = 'ml_publications.refresh'",
        )

        job = job_of(report(store), "refresh")

        assert (job["enabled"], job["disabled"], job["failing"], job["requested"]) == (True, False, False, True)
        assert job["last_run_at"] is not None and job["last_success_at"] is not None

    def test_a_run_newer_than_the_last_success_is_failing_and_carries_its_error(self, store) -> None:
        settings_store.set_setting("intake.enabled", True, "test")
        put_state(
            store,
            "ml_publications.intake",
            detail={"last_run": {"error": "bridge_unreachable", "at": "2026-10-07T10:00:00+00:00"}},
        )
        run(
            store,
            "UPDATE worker_job_state SET last_run_at = now(), last_success_at = now() - interval '1 hour' "
            "WHERE name = 'ml_publications.intake'",
        )

        job = job_of(report(store), "intake")

        assert (job["failing"], job["last_error"]) == (True, "bridge_unreachable")

    def test_a_disabled_job_is_not_a_failure_even_when_its_last_run_never_succeeded(self, store) -> None:
        put_state(store, "ml_publications.scan", detail={"disabled": True})
        run(store, "UPDATE worker_job_state SET last_run_at = now() WHERE name = 'ml_publications.scan'")

        job = job_of(report(store), "scan")

        assert (job["enabled"], job["disabled"], job["failing"]) == (False, True, False)

    def test_the_stored_disabled_marker_counts_as_disabled_even_if_the_flag_reads_on(self, store) -> None:
        settings_store.set_setting("scan.enabled", True, "test")
        put_state(store, "ml_publications.scan", detail={"disabled": True})

        job = job_of(report(store), "scan")

        assert (job["enabled"], job["disabled"]) == (True, True)

    def test_the_kill_switch_reads_every_flag_as_off(self, store, monkeypatch) -> None:
        settings_store.set_setting("refresh.enabled", True, "test")
        monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)

        result = report(store)

        assert result["kill_switch"] is True
        assert job_of(result, "refresh")["enabled"] is False and result["flags"]["refresh"] is False


class TestQueue:
    def test_depth_and_oldest_age_per_lane_and_parked_entries_with_their_last_error(self, store) -> None:
        run(
            store,
            "INSERT INTO ml_pub_refresh_queue (kind, entity_id, lane, first_enqueued_at) VALUES "
            "('item', 'MLA1', 0, now() - interval '10 seconds'), ('item', 'MLA2', 1, now() - interval '120 seconds'), "
            "('item', 'MLA3', 1, now() - interval '30 seconds')",
        )
        run(store, "UPDATE ml_pub_refresh_queue SET claimed_at = now() WHERE entity_id = 'MLA3'")
        run(
            store,
            "INSERT INTO ml_pub_refresh_queue (kind, entity_id, lane, attempts, last_error, parked_at) "
            "VALUES ('item', 'MLA9', 3, 8, 'http_500: boom', now())",
        )

        queue = report(store)["queue"]
        lanes = {lane["lane"]: lane for lane in queue["lanes"]}

        assert (lanes[0]["waiting"], lanes[1]["waiting"], lanes[1]["claimed"], lanes[3]["parked"]) == (1, 1, 1, 1)
        assert 100 < lanes[1]["oldest_waiting_age_seconds"] < 200
        assert lanes[2]["oldest_waiting_age_seconds"] is None
        assert queue["parked_total"] == 1
        assert queue["parked"][0]["entity_id"] == "MLA9"
        assert queue["parked"][0]["last_error"] == "http_500: boom" and queue["parked"][0]["attempts"] == 8

    def test_the_parked_list_is_bounded_but_the_total_is_not(self, store) -> None:
        run(
            store,
            "INSERT INTO ml_pub_refresh_queue (kind, entity_id, lane, parked_at, last_error) "
            "SELECT 'item', 'MLA' || g, 3, now(), 'e' FROM generate_series(1, :n) g",
            n=status.PARKED_LIMIT + 5,
        )

        queue = report(store)["queue"]

        assert len(queue["parked"]) == status.PARKED_LIMIT and queue["parked_total"] == status.PARKED_LIMIT + 5


class TestIntake:
    def _cursor(self, engine, topic: str, ago: str) -> None:
        run(
            engine,
            "INSERT INTO ml_pub_intake_cursors (topic, cursor_received_at, updated_at, rows_read, enqueued) "
            "VALUES (:t, now() - CAST(:ago AS interval), now() - CAST(:ago AS interval), 10, 4)",
            t=topic,
            ago=ago,
        )

    def test_a_cursor_that_did_not_advance_past_the_threshold_while_enabled_is_stalled(self, store) -> None:
        settings_store.set_setting("intake.enabled", True, "test")
        self._cursor(store, "items", f"{settings.ML_PUB_INTAKE_STALL_SECONDS + 60} seconds")

        intake = report(store)["intake"]

        assert intake["stalled"] is True and intake["cursors"][0]["stalled"] is True
        assert intake["cursors"][0]["age_seconds"] > settings.ML_PUB_INTAKE_STALL_SECONDS
        assert (intake["cursors"][0]["rows_read"], intake["cursors"][0]["enqueued"]) == (10, 4)

    def test_a_fresh_cursor_is_not_stalled(self, store) -> None:
        settings_store.set_setting("intake.enabled", True, "test")
        self._cursor(store, "items", "5 seconds")

        assert report(store)["intake"]["stalled"] is False

    def test_an_old_cursor_is_not_an_alarm_while_the_flag_is_off(self, store) -> None:
        self._cursor(store, "items", "1 day")

        intake = report(store)["intake"]

        assert intake["stalled"] is False and intake["cursors"][0]["stalled"] is False
        assert intake["cursors"][0]["age_seconds"] > 80_000


class TestBackfillMissedFeedsAndSweep:
    def test_backfill_progress_per_status(self, store) -> None:
        run(
            store,
            "INSERT INTO ml_pub_scan_state (status, mode, pages, enumerated, enqueued, restarts, last_error, "
            "completed_at) VALUES ('closed', 'full', 2, 39, 39, 0, NULL, now()), "
            "('active', 'full', 5, 4000, 3900, 1, 'timeout', NULL)",
        )

        rows = {row["status"]: row for row in report(store)["backfill"]}

        assert (rows["closed"]["enumerated"], rows["closed"]["complete"]) == (39, True)
        assert (rows["active"]["enqueued"], rows["active"]["complete"], rows["active"]["last_error"]) == (
            3900,
            False,
            "timeout",
        )

    def test_missed_feeds_reports_the_last_success_and_the_gap_since(self, store) -> None:
        run(
            store,
            "INSERT INTO ml_pub_job_runs (job, started_at, finished_at, outcome, counts) VALUES "
            "('missed_feeds', now() - interval '3 days', now() - interval '3 days', 'success', '{}'), "
            "('missed_feeds', now() - interval '1 hour', now() - interval '1 hour', 'partial', "
            ' \'{"coverage_gap": {"hours": 72.0, "last_success_at": "2026-10-04T00:00:00+00:00"}}\')',
        )

        feeds = report(store)["missed_feeds"]

        assert feeds["last_success_at"] is not None and feeds["age_seconds"] > 2 * 86_400
        assert feeds["last_run"]["outcome"] == "partial"
        assert feeds["coverage_gap"]["hours"] == 72.0 and feeds["coverage_gap"]["resolved"] is False

    def test_a_gap_followed_by_a_completed_run_is_resolved(self, store) -> None:
        run(
            store,
            "INSERT INTO ml_pub_job_runs (job, started_at, finished_at, outcome, counts) VALUES "
            "('missed_feeds', now() - interval '2 hours', now() - interval '2 hours', 'partial', "
            ' \'{"coverage_gap": {"hours": 60.0}}\'), '
            "('missed_feeds', now() - interval '1 hour', now() - interval '1 hour', 'success', '{}')",
        )

        assert report(store)["missed_feeds"]["coverage_gap"]["resolved"] is True

    def test_sweep_health_is_read_from_the_outcome_of_the_last_run_not_from_the_job_success(self, store) -> None:
        put_state(store, "ml_publications.sweep")
        run(store, "UPDATE worker_job_state SET last_run_at = now(), last_success_at = now()")
        run(
            store,
            "INSERT INTO ml_pub_job_runs (job, started_at, finished_at, outcome, counts, last_error) VALUES "
            "('sweep', now() - interval '20 minutes', now() - interval '20 minutes', 'success', '{}', NULL), "
            "('sweep', now() - interval '10 minutes', now() - interval '10 minutes', 'failed', "
            " '{\"yielded_in_a_row\": 0, \"enqueued\": 0}', 'internal_error: boom')",
        )

        result = report(store)

        assert job_of(result, "sweep")["failing"] is False  # the tick "succeeded": the outcome says otherwise
        assert result["sweep"]["last_run"]["outcome"] == "failed"
        assert result["sweep"]["last_run"]["error"] == "internal_error: boom"

    def test_the_yield_streak_is_reported(self, store) -> None:
        run(
            store,
            "INSERT INTO ml_pub_job_runs (job, started_at, finished_at, outcome, counts) VALUES "
            "('sweep', now(), now(), 'yielded', '{\"yielded_in_a_row\": 7, \"enqueued\": 0}')",
        )

        last = report(store)["sweep"]["last_run"]

        assert (last["outcome"], last["yielded_in_a_row"], last["enqueued"]) == ("yielded", 7, 0)


class TestFreshnessAndCompleteness:
    def test_age_distribution_over_last_checked_at(self, store) -> None:
        for index, age in enumerate((10, 20, 30, 40, 1000)):
            put_item(store, f"MLA{index}", checked=f"{age} seconds")
        put_item(store, "MLA99", checked=None)

        fresh = report(store)["freshness"]["items"]

        assert (fresh["rows"], fresh["checked"]) == (6, 5)
        assert 29 < fresh["p50_age_seconds"] < 32
        assert 800 < fresh["p95_age_seconds"] <= 1001
        assert 999 < fresh["max_age_seconds"] < 1010

    def test_every_sub_resource_table_has_its_own_distribution(self, store) -> None:
        run(
            store,
            "INSERT INTO ml_item_descriptions (item_id, last_checked_at) VALUES ('MLA1', now() - interval '60 seconds')",
        )

        freshness = report(store)["freshness"]

        assert freshness["description"]["rows"] == 1 and 59 < freshness["description"]["max_age_seconds"] < 70
        assert {"items", "prices", "stock", "family", "visits", "performance"} <= set(freshness)

    def test_notification_lag_p95_over_the_last_24_hours(self, store) -> None:
        for index, lag in enumerate((10, 20, 90)):
            put_item(store, f"MLA{index}")
            run(
                store,
                "UPDATE ml_items SET last_trigger_received_at = now() - interval '1 hour', "
                "fetched_at = now() - interval '1 hour' + CAST(:lag AS interval) WHERE item_id = :i",
                lag=f"{lag} seconds",
                i=f"MLA{index}",
            )
        put_item(store, "MLA50")  # fetched two days ago: outside the window
        run(
            store,
            "UPDATE ml_items SET last_trigger_received_at = now() - interval '2 days', "
            "fetched_at = now() - interval '2 days' + interval '1 hour' WHERE item_id = 'MLA50'",
        )

        result = report(store)

        assert result["lag_samples_24h"] == 3
        assert 80 < result["lag_p95_seconds_24h"] <= 90.001

    def test_missing_rows_and_non_2xx_by_status_code(self, store) -> None:
        for index in range(5):
            put_item(store, f"MLA{index}")
        run(
            store,
            "INSERT INTO ml_item_descriptions (item_id, http_status) VALUES ('MLA0', 200), ('MLA1', 403), ('MLA2', 403)",
        )
        run(store, "UPDATE ml_items SET gone_at = now() WHERE item_id = 'MLA4'")
        settings_store.set_setting("bundle_resources", ["core", "description"], "test")

        completeness = report(store)["completeness"]

        assert completeness["description"]["missing"] == 1  # MLA3: MLA4 is gone and is not expected to have one
        assert completeness["description"]["non_2xx"] == {"403": 2}
        assert completeness["description"]["expected"] is True
        assert completeness["prices"]["expected"] is False

    def test_items_by_status_with_raw_and_gone(self, store) -> None:
        put_item(store, "MLA1", state="active", raw=json.dumps({"id": "MLA1"}))
        put_item(store, "MLA2", state="closed")
        put_item(store, "MLA3", state="closed", gone_at="2026-10-01T00:00:00+00:00")

        items = report(store)["items"]

        assert items["total"] == 3 and items["gone"] == 1
        assert items["by_status"] == {"active": 1, "closed": 2}


class TestCountersEventsLinksAndPaths:
    def test_stale_noise_and_request_counters_come_from_the_refresh_run_state(self, store) -> None:
        put_state(
            store,
            "ml_publications.refresh",
            detail={
                "counters": {
                    "stale_discarded": 4,
                    "noise_suppressed": 9,
                    "endpoints": {"items_bulk": {"200": 40, "429": 2}, "description": {"200": 7, "429": 1}},
                    "elements": {"200": 47, "404": 1, "failed": 0},
                }
            },
        )

        counters = report(store)["counters"]

        assert (counters["stale_discarded"], counters["noise_suppressed"], counters["requests_429"]) == (4, 9, 3)
        assert counters["requests"]["items_bulk"] == {"200": 40, "429": 2}

    def test_event_counts_per_type_and_the_age_of_the_newest(self, store) -> None:
        run(
            store,
            "INSERT INTO ml_change_log (id, resource_type, entity_id, observed_at, changed_paths, changes) "
            "VALUES (1, 'item', 'MLA1', now(), '{price}', '{}')",
        )
        run(
            store,
            "INSERT INTO ml_item_events (event_type, item_id, observed_at, change_log_id, dedupe_key) VALUES "
            "('price_changed', 'MLA1', now() - interval '30 minutes', 1, '\\x01'), "
            "('price_changed', 'MLA1', now() - interval '3 days', 1, '\\x02'), "
            "('paused', 'MLA1', now() - interval '2 hours', 1, '\\x03')",
        )
        settings_store.set_setting("events.enabled", True, "test")

        events = report(store)["events"]

        assert events["enabled"] is True
        assert (events["by_type"]["price_changed"]["last_24h"], events["by_type"]["price_changed"]["last_7d"]) == (1, 2)
        assert events["by_type"]["paused"]["last_24h"] == 1
        assert 1700 < events["newest_age_seconds"] < 3600

    def test_link_coverage_comes_from_the_coverage_service_and_the_flag(self, store) -> None:
        put_item(store, "MLA1")
        run(
            store,
            "INSERT INTO ml_item_product_links (item_id, variation_id, source, match_status, linked_at) "
            "VALUES ('MLA1', 0, 'sku_auto', 'unmatched', now())",
        )
        settings_store.set_setting("links.enabled", True, "test")

        links = report(store)["links"]

        assert links["enabled"] is True
        assert links["coverage"]["total_units"] == 1 and links["coverage"]["classes"]["never_evaluated"] == 1
        assert links["coverage"]["samples"] == {name: [] for name in links["coverage"]["samples"]}

    def test_top_changed_paths_over_seven_days_are_bounded_and_ordered(self, store) -> None:
        run(
            store,
            "INSERT INTO ml_change_log (resource_type, entity_id, observed_at, changed_paths, changes) "
            "SELECT 'item', 'MLA' || g, now() - interval '1 day', '{price,status}', '{}' FROM generate_series(1, 3) g",
        )
        run(
            store,
            "INSERT INTO ml_change_log (resource_type, entity_id, observed_at, changed_paths, changes) VALUES "
            "('item', 'MLA9', now() - interval '1 day', '{health}', '{}'), "
            "('item', 'MLA9', now() - interval '30 days', '{old_path}', '{}')",
        )
        run(
            store,
            "INSERT INTO ml_change_log (resource_type, entity_id, observed_at, changed_paths, changes) "
            "SELECT 'item', 'MLA1', now(), ARRAY['p' || g], '{}' FROM generate_series(1, :n) g",
            n=status.TOP_PATHS_LIMIT + 10,
        )

        top = report(store)["top_changed_paths"]

        assert len(top) == status.TOP_PATHS_LIMIT
        assert [(row["resource_type"], row["path"], row["changes"]) for row in top[:2]] == [
            ("item", "price", 3),
            ("item", "status", 3),
        ]
        assert "old_path" not in {row["path"] for row in top}


class TestReadOnlyAndBounded:
    def test_it_applies_the_statement_timeout_and_runs_nothing_but_reads(self, store) -> None:
        seen: list[str] = []

        @event.listens_for(store, "before_cursor_execute")
        def capture(conn, cursor, statement, parameters, context, executemany):
            seen.append(" ".join(statement.split()))

        put_item(store, "MLA1")
        before = {
            table: scalar(store, f"SELECT count(*) FROM {table}")
            for table in ("ml_items", "ml_pub_refresh_queue", "ml_pub_settings", "ml_change_log", "worker_job_state")
        }
        seen.clear()

        report(store)

        after = {table: scalar(store, f"SELECT count(*) FROM {table}") for table in before}
        assert after == before
        assert any(sql.upper().startswith("SET LOCAL STATEMENT_TIMEOUT = '5S'") for sql in seen)
        assert any(sql.upper().startswith("SET TRANSACTION READ ONLY") for sql in seen)
        allowed = ("SELECT", "SET ", "SAVEPOINT", "RELEASE", "ROLLBACK", "BEGIN", "WITH")
        assert [sql for sql in seen if not sql.upper().startswith(allowed)] == []

    def test_the_session_is_read_only_at_the_database(self, store) -> None:
        session = sessionmaker(bind=store)()
        try:
            status.build_status(session)
            with pytest.raises(Exception, match="read-only"):
                session.execute(text("INSERT INTO ml_pub_settings (key, value) VALUES ('x', '1')"))
        finally:
            session.rollback()
            session.close()

    def test_it_also_works_on_a_session_whose_transaction_already_ran_a_query(self, store) -> None:
        """In production the permission check opens the transaction the report then joins."""
        session = sessionmaker(bind=store)()
        try:
            session.execute(text("SELECT 1"))
            assert status.build_status(session)["sections_failed"] == []
        finally:
            session.rollback()
            session.close()

    def test_one_failing_section_is_reported_and_the_rest_still_answers(self, store, monkeypatch) -> None:
        def broken(db):
            raise RuntimeError("boom")

        monkeypatch.setattr(status, "_events", broken)
        put_item(store, "MLA1")

        result = report(store)

        assert result["sections_failed"] == ["events"]
        assert result["events"] is None
        assert result["items"]["total"] == 1

    def test_a_worker_state_of_an_unexpected_shape_fails_only_its_own_sections(self, store) -> None:
        put_state(store, "ml_publications.refresh", detail={"counters": ["not", "a", "dict"]})
        put_state(store, "ml_publications.scan", detail="a bare string")
        put_item(store, "MLA1")

        result = report(store)

        assert set(result["sections_failed"]) == {"counters", "jobs"}
        assert result["counters"] == {} and result["jobs"] == []
        assert result["items"]["total"] == 1

    def test_a_statement_timeout_in_one_section_does_not_abort_the_others(self, store, monkeypatch) -> None:
        original = status._top_changed_paths

        def slow(db):
            db.execute(text("SELECT pg_sleep(1)"))  # the report asked for a 5 s timeout; shrink it to trip it
            return original(db)

        monkeypatch.setattr(status, "STATEMENT_TIMEOUT", "100ms")
        monkeypatch.setattr(status, "_top_changed_paths", slow)

        result = report(store)

        assert result["sections_failed"] == ["top_changed_paths"]
        assert result["items"]["total"] == 0 and result["queue"]["parked"] == []
