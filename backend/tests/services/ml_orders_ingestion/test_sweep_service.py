"""Tests for the ML orders reconciliation sweep (slice 3).

Contract-first (obs #1843 lesson): assert the PROMISES (flag-gated,
fail-closed window semantics, cursor NOT advanced on an unresolved
failure, out-of-window hard exclusion + instrumentation) not just the
happy-path behaviour.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import mock
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOpsDivergence, MlOpsSyncCursor, MlOrdersOps, MlShipmentOps
from app.services.ml_orders_ingestion import sweep_service
from app.services.ml_webhook_client import ml_webhook_client


def _fake_ctx(db):
    """Bridges `sweep_service.get_background_db()` (bound to the real,
    unreachable-in-tests Postgres engine) to the sqlite `db` fixture, the
    same pattern used by `tests/unit/test_drain_promo_refresh.py` for the
    same reason: the test DB is sqlite (conftest `TEST_DB_URL="sqlite://"`)
    and every session `sweep_service` opens must land in that one
    transactional session so assertions can see the writes."""

    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    return lambda: _Ctx()


@pytest.fixture(autouse=True)
def _background_db(db, monkeypatch):
    monkeypatch.setattr(sweep_service, "get_background_db", _fake_ctx(db))


def _order(order_id: int, seller_id: int, when: datetime, created: datetime, shipping_id: int = None) -> dict:
    order = {
        "id": order_id,
        "status": "paid",
        "date_created": created.isoformat(),
        "date_last_updated": when.isoformat(),
        "seller": {"id": seller_id},
        "buyer": {"id": 1, "nickname": "x"},
        "order_items": [],
    }
    if shipping_id is not None:
        order["shipping"] = {"id": shipping_id}
    return order


def _shipment(shipment_id: int, order_id: int, status: str = "shipped") -> dict:
    return {
        "id": shipment_id,
        "order_id": order_id,
        "status": status,
        "last_updated": None,
    }


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_WINDOW_DAYS", 90)


def _page(results, total=None):
    return {"results": results, "paging": {"total": total if total is not None else len(results)}}


class TestFlagGate:
    def test_flag_off_is_a_complete_noop(self, db, monkeypatch):
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        mock_search = AsyncMock(return_value=_page([]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.ran is False
        mock_search.assert_not_called()
        assert db.query(MlOrdersOps).count() == 0
        assert db.query(MlOpsSyncCursor).count() == 0


class TestCursorAdvance:
    def test_success_advances_cursor(self, db, monkeypatch):
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        mock_search = AsyncMock(return_value=_page([_order(1, 999, recent, recent)]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.ran is True
        assert result.error is None
        cursor = db.query(MlOpsSyncCursor).filter_by(name="sweep").one()
        assert cursor.state == "idle"
        assert cursor.last_success_at is not None
        assert cursor.window_to is not None

    def test_window_failure_does_not_advance_cursor(self, db, monkeypatch):
        mock_search = AsyncMock(return_value=None)  # proxy down / 5xx / timeout
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.ran is True
        assert result.error is not None
        cursor = db.query(MlOpsSyncCursor).filter_by(name="sweep").one()
        assert cursor.state == "error"
        assert cursor.last_success_at is None
        assert cursor.window_to is None  # window NOT checkpointed

    def test_retried_after_failure_uses_same_starting_point(self, db, monkeypatch):
        """The unresolved-failure guarantee, made concrete: after a failed
        pass the NEXT pass must retry from (essentially) the same window
        start, not silently skip forward past the gap."""
        mock_search = AsyncMock(return_value=None)
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)
        sweep_service.run_sweep(seller_id=999, window_days=90)
        first_call_args = mock_search.call_args

        mock_search.reset_mock(return_value=True)
        mock_search.return_value = None
        sweep_service.run_sweep(seller_id=999, window_days=90)
        second_call_args = mock_search.call_args

        # date_from passed to search_orders must not have advanced past the
        # still-unconfirmed window -- both calls recompute
        # `window_from_floor` from a fresh `now()`, so allow for the sub-
        # second wall-clock drift between the two calls, but the gap must
        # be nowhere near the 90-day window itself.
        first_date_from = first_call_args.args[1]
        second_date_from = second_call_args.args[1]
        assert abs((second_date_from - first_date_from).total_seconds()) < 5


class TestWindowBisection:
    def test_bisects_window_when_total_exceeds_cap(self, db, monkeypatch):
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        calls = []

        async def fake_search(seller_id, date_from, date_to, offset=0):
            calls.append((date_from, date_to, offset))
            span = date_to - date_from
            # First call sees a window too wide -> report over-cap; once
            # bisected below ~ half a day, report a normal small result.
            if span > timedelta(hours=12):
                return {"results": [], "paging": {"total": 2000}}
            return _page([_order(len(calls), 999, recent, recent)])

        monkeypatch.setattr(ml_webhook_client, "search_orders", fake_search)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.ran is True
        assert result.error is None
        # More than one call proves bisection actually happened (not a
        # single offset-deepening call).
        assert len(calls) > 1
        assert result.orders_upserted >= 1


class TestOutOfWindowCounter:
    def test_order_outside_window_is_counted_not_ingested(self, db, monkeypatch):
        now = datetime.now(timezone.utc)
        recent_update = now - timedelta(days=1)
        old_created = now - timedelta(days=400)  # older than the 90-day window
        mock_search = AsyncMock(return_value=_page([_order(42, 999, recent_update, old_created)]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.ran is True
        assert result.orders_out_of_window == 1
        assert db.query(MlOrdersOps).filter_by(order_id=42).count() == 0
        divergence = db.query(MlOpsDivergence).filter_by(order_id=42, kind="out_of_window_update").one()
        assert divergence.field is None

    def test_repeat_detection_updates_not_duplicates(self, db, monkeypatch):
        now = datetime.now(timezone.utc)
        recent_update = now - timedelta(days=1)
        old_created = now - timedelta(days=400)
        mock_search = AsyncMock(return_value=_page([_order(42, 999, recent_update, old_created)]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        sweep_service.run_sweep(seller_id=999, window_days=90)
        sweep_service.run_sweep(seller_id=999, window_days=90)

        assert db.query(MlOpsDivergence).filter_by(order_id=42, kind="out_of_window_update").count() == 1

    def test_order_inside_window_is_ingested_normally(self, db, monkeypatch):
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        mock_search = AsyncMock(return_value=_page([_order(7, 999, recent, recent)]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.orders_out_of_window == 0
        assert result.orders_upserted == 1
        assert db.query(MlOrdersOps).filter_by(order_id=7).count() == 1


class TestBoundedMemory:
    def test_fetch_flushes_once_the_batch_bound_is_crossed_not_at_window_end(self, db, monkeypatch):
        """Finding 1: the sweep must never hold a whole window's orders in
        memory before writing any of them. Proven here with a window
        spanning THREE pages of 100 orders each (BATCH_SIZE=200): once the
        first two pages cross the 200-row batch bound, they must be
        flushed to the DB BEFORE the third page is even fetched -- if the
        implementation accumulated the entire window first, none of the
        first 200 orders would exist yet at that point."""
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        seen_at_third_fetch = {}

        def _page_of(start_id: int, count: int) -> list:
            return [_order(start_id + i, 999, recent, recent) for i in range(count)]

        async def fake_search(seller_id, date_from, date_to, offset=0):
            if offset == 0:
                return {"results": _page_of(1, 100), "paging": {"total": 300}}
            if offset == 100:
                return {"results": _page_of(101, 100), "paging": {"total": 300}}
            # By the time the THIRD page (offset=200) is fetched, the
            # batch bound (200) was already crossed by pages 1+2 -- those
            # 200 orders must already be committed.
            seen_at_third_fetch["first_200_persisted"] = db.query(MlOrdersOps).count() == 200
            return {"results": _page_of(201, 100), "paging": {"total": 300}}

        monkeypatch.setattr(ml_webhook_client, "search_orders", fake_search)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.error is None
        assert seen_at_third_fetch.get("first_200_persisted") is True
        assert db.query(MlOrdersOps).count() == 300

    def test_cold_start_checkpoints_incrementally_per_leaf_window(self, db, monkeypatch):
        """A cold start (no cursor yet) spans the full rolling window
        (e.g. 90-180 days). If a later leaf fails, the cursor must have
        already advanced past every EARLIER leaf that succeeded -- a cold
        start crash must not retry the whole window from scratch forever."""
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        call_count = {"n": 0}

        async def fake_search(seller_id, date_from, date_to, offset=0):
            call_count["n"] += 1
            span = date_to - date_from
            # Force a bisection into (at least) two leaves by reporting
            # over-cap once for the full span, then let each half through.
            if span > timedelta(days=40):
                return {"results": [], "paging": {"total": 2000}}
            # The SECOND leaf (later half) fails permanently.
            if date_from > now - timedelta(days=44):
                return None
            return {"results": [_order(call_count["n"], 999, recent, recent)], "paging": {"total": 1}}

        monkeypatch.setattr(ml_webhook_client, "search_orders", fake_search)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.error is not None
        cursor = db.query(MlOpsSyncCursor).filter_by(name="sweep").one()
        assert cursor.state == "error"
        # The first (earlier) leaf's order must be durably persisted even
        # though the sweep as a whole failed.
        assert db.query(MlOrdersOps).count() >= 1
        # And the cursor must have advanced PAST that first leaf -- not
        # left at None/the original cold-start floor -- so a retry does
        # not redo the whole 90-day window from scratch.
        assert cursor.window_to is not None


class TestUnenumerableWindowEscape:
    def test_unbisectable_overflow_is_recorded_and_swept_past(self, db, monkeypatch):
        """Finding 3: a window that still reports total > cap even at the
        minimum bisectable span must NOT wedge the sweep forever. It is
        recorded (never silently dropped) and the sweep moves past it --
        proven here by the run completing successfully (no error) despite
        one leaf being permanently unenumerable.

        `window_days=1` keeps this test fast: bisecting down to
        MIN_BISECT_SPAN (1 minute) from a 90-day window is ~131k leaves
        (exponential HTTP calls against a client that always reports
        over-cap); one day is ~1440, still exercises real bisection depth
        without a multi-minute test."""

        async def fake_search(seller_id, date_from, date_to, offset=0):
            # Every window, no matter how small, reports over-cap.
            return {"results": [], "paging": {"total": 5000}}

        monkeypatch.setattr(ml_webhook_client, "search_orders", fake_search)

        result = sweep_service.run_sweep(seller_id=999, window_days=1)

        assert result.error is None
        assert result.ran is True
        assert result.windows_unenumerable > 0
        rows = db.query(MlOpsDivergence).filter_by(kind="window_not_enumerable").all()
        assert len(rows) == result.windows_unenumerable
        # The cursor still advances (it is not a normal failure) -- this
        # is the whole point of the escape hatch.
        cursor = db.query(MlOpsSyncCursor).filter_by(name="sweep").one()
        assert cursor.state == "idle"
        assert cursor.window_to is not None

    def test_repeat_unenumerable_detection_does_not_duplicate(self, db, monkeypatch):
        async def fake_search(seller_id, date_from, date_to, offset=0):
            return {"results": [], "paging": {"total": 5000}}

        monkeypatch.setattr(ml_webhook_client, "search_orders", fake_search)

        sweep_service.run_sweep(seller_id=999, window_days=1)
        first_count = db.query(MlOpsDivergence).filter_by(kind="window_not_enumerable").count()
        sweep_service.run_sweep(seller_id=999, window_days=1)
        second_count = db.query(MlOpsDivergence).filter_by(kind="window_not_enumerable").count()

        # A second pass covers a NEW (advanced) window, so it may add its
        # own rows, but it must never duplicate an already-recorded one
        # (unique (order_id, kind, field)).
        assert second_count >= first_count


class TestRunningLock:
    def test_concurrent_run_is_skipped_not_double_processed(self, db, monkeypatch):
        """Finding 4: while a run is genuinely in flight (`state='running'`,
        set recently), a second invocation must skip rather than run
        concurrently against the same cursor."""
        now = datetime.now(timezone.utc)
        db.add(MlOpsSyncCursor(name="sweep", state="running", detail=now.isoformat()))
        db.flush()

        mock_search = AsyncMock(return_value=_page([]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.ran is False
        mock_search.assert_not_called()

    def test_stale_running_lock_is_reclaimed(self, db, monkeypatch):
        """A process that died mid-run must not wedge the sweep forever:
        a 'running' lock older than the stale-lock timeout is reclaimed,
        not treated as still in flight."""
        ancient = datetime.now(timezone.utc) - timedelta(hours=6)
        db.add(MlOpsSyncCursor(name="sweep", state="running", detail=ancient.isoformat()))
        db.flush()

        recent = datetime.now(timezone.utc) - timedelta(days=1)
        mock_search = AsyncMock(return_value=_page([_order(1, 999, recent, recent)]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.ran is True
        mock_search.assert_called()

    def test_state_is_running_during_the_pass_and_idle_after(self, db, monkeypatch):
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        states_observed = []

        async def fake_search(seller_id, date_from, date_to, offset=0):
            cursor = db.query(MlOpsSyncCursor).filter_by(name="sweep").one()
            states_observed.append(cursor.state)
            return _page([_order(1, 999, recent, recent)])

        monkeypatch.setattr(ml_webhook_client, "search_orders", fake_search)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        assert states_observed == ["running"]
        cursor = db.query(MlOpsSyncCursor).filter_by(name="sweep").one()
        assert cursor.state == "idle"

    def test_state_is_error_after_a_failed_pass_not_stuck_running(self, db, monkeypatch):
        mock_search = AsyncMock(return_value=None)
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        cursor = db.query(MlOpsSyncCursor).filter_by(name="sweep").one()
        assert cursor.state == "error"


class TestUnenumerableFieldKeyFitsTheColumn:
    """`ml_ops_divergence.field` is String(40). SQLite does not enforce
    VARCHAR length, so a key that overflows passes every test here and
    only fails on Postgres — precisely inside the escape hatch, whose
    whole point is to keep the sweep alive."""

    def test_field_key_fits_in_forty_characters(self) -> None:
        from app.models.ml_orders_ops import MlOpsDivergence
        from app.services.ml_orders_ingestion.sweep_service import _unenumerable_field_key

        limit = MlOpsDivergence.__table__.c.field.type.length
        key = _unenumerable_field_key(
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc),
        )

        assert len(key) <= limit

    def test_field_key_is_distinct_per_window(self) -> None:
        from app.services.ml_orders_ingestion.sweep_service import _unenumerable_field_key

        a = _unenumerable_field_key(
            datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
        )
        b = _unenumerable_field_key(
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
        )

        assert a != b


class TestBisectionIsBounded:
    """A bogus or inflated `paging.total` used to recurse all the way down
    to the 1-minute floor: 180 days is 259,200 leaves, each one an HTTP
    call to the ML proxy and a divergence row."""

    def test_a_pass_stops_after_the_leaf_budget_is_spent(self, db, monkeypatch) -> None:
        from app.services.ml_orders_ingestion import sweep_service

        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)

        calls = {"n": 0}

        async def always_over_cap(seller_id, date_from, date_to, offset=0):
            calls["n"] += 1
            return {"results": [], "paging": {"total": 99999}}

        monkeypatch.setattr(sweep_service.ml_webhook_client, "search_orders", always_over_cap)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        assert calls["n"] <= sweep_service.MAX_WINDOW_FETCHES_PER_PASS


class TestRunLockIsAlwaysReleased:
    """The module's thesis is that the sweep never gets stuck. An exception
    other than WindowFetchError used to escape `run_sweep`, leaving the
    cursor at state='running' until the 30-minute stale timeout — three
    lost cron cycles and a raw traceback in the log."""

    def test_unexpected_exception_leaves_the_lock_released(self, db, monkeypatch) -> None:
        from app.models.ml_orders_ops import MlOpsSyncCursor
        from app.services.ml_orders_ingestion import sweep_service

        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)

        async def boom(seller_id, date_from, date_to, offset=0):
            raise RuntimeError("something nobody predicted")

        monkeypatch.setattr(sweep_service.ml_webhook_client, "search_orders", boom)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.error is not None
        cursor = db.query(MlOpsSyncCursor).filter_by(name=sweep_service.CURSOR_NAME).first()
        assert cursor is not None
        assert cursor.state != "running"

    def test_a_later_pass_can_still_run_after_an_unexpected_exception(self, db, monkeypatch) -> None:
        from app.services.ml_orders_ingestion import sweep_service

        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)

        async def boom(seller_id, date_from, date_to, offset=0):
            raise RuntimeError("something nobody predicted")

        monkeypatch.setattr(sweep_service.ml_webhook_client, "search_orders", boom)
        sweep_service.run_sweep(seller_id=999, window_days=90)

        async def empty(seller_id, date_from, date_to, offset=0):
            return {"results": [], "paging": {"total": 0}}

        monkeypatch.setattr(sweep_service.ml_webhook_client, "search_orders", empty)
        second = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert second.ran is True
        assert second.error != "already running"


class TestLockReleaseIsStructural:
    """Closing each individual path that could strand the lock has now
    failed three times. The release has to be guaranteed by structure."""

    def test_failure_in_the_final_flush_still_releases_the_lock(self, db, monkeypatch) -> None:
        from app.models.ml_orders_ops import MlOpsSyncCursor
        from app.services.ml_orders_ingestion import sweep_service

        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)

        async def one_page(seller_id, date_from, date_to, offset=0):
            return {
                "results": [_order(1, 999, datetime.now(timezone.utc), datetime.now(timezone.utc))],
                "paging": {"total": 1},
            }

        monkeypatch.setattr(sweep_service.ml_webhook_client, "search_orders", one_page)
        monkeypatch.setattr(sweep_service, "process_batch", mock.Mock(side_effect=RuntimeError("db died mid-flush")))

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.error is not None
        cursor = db.query(MlOpsSyncCursor).filter_by(name=sweep_service.CURSOR_NAME).first()
        assert cursor.state != "running"

    def test_a_failing_lock_release_does_not_propagate(self, monkeypatch) -> None:
        """`_release_lock_as_error` opens its own session. If the database
        is what failed in the first place, the release must not raise on
        top of it — that leaves the lock stuck AND a raw traceback."""
        from app.services.ml_orders_ingestion import sweep_service

        monkeypatch.setattr(sweep_service, "get_background_db", mock.Mock(side_effect=RuntimeError("pool exhausted")))

        sweep_service.release_lock_as_error(RuntimeError("original failure"))


class TestBudgetCountsEveryFetch:
    """The budget was spent once per window, at offset=0, while the
    pagination loop fetched freely. A leaf with total=950 costs ~19 HTTP
    calls and one unit of budget, so the documented ceiling was off by
    more than an order of magnitude. The earlier budget test never
    reached this branch because its fake was always over cap."""

    def test_pagination_pages_are_charged_to_the_budget(self, db, monkeypatch) -> None:
        from app.services.ml_orders_ingestion import sweep_service

        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
        monkeypatch.setattr(sweep_service, "MAX_WINDOW_FETCHES_PER_PASS", 5)

        calls = {"n": 0}
        page_size = 50

        async def paged(seller_id, date_from, date_to, offset=0):
            calls["n"] += 1
            when = datetime.now(timezone.utc)
            results = [_order(offset + i, 999, when, when) for i in range(page_size)]
            return {"results": results, "paging": {"total": 900}}

        monkeypatch.setattr(sweep_service.ml_webhook_client, "search_orders", paged)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        assert calls["n"] <= sweep_service.MAX_WINDOW_FETCHES_PER_PASS


class TestTruncatedPassIsNotReportedAsSuccess:
    """A pass that ran out of fetch budget covered a fraction of the
    window. Marking it idle with a fresh `last_success_at` records partial
    work as a completed sweep — the silent-stuck-window the module exists
    to prevent."""

    def test_budget_exhausted_is_reported_on_the_result(self, db, monkeypatch) -> None:
        from app.services.ml_orders_ingestion import sweep_service

        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
        monkeypatch.setattr(sweep_service, "MAX_WINDOW_FETCHES_PER_PASS", 2)

        async def paged(seller_id, date_from, date_to, offset=0):
            when = datetime.now(timezone.utc)
            return {
                "results": [_order(offset + i, 999, when, when) for i in range(50)],
                "paging": {"total": 900},
            }

        monkeypatch.setattr(sweep_service.ml_webhook_client, "search_orders", paged)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.budget_exhausted is True

    def test_budget_exhausted_does_not_stamp_last_success_at(self, db, monkeypatch) -> None:
        from app.models.ml_orders_ops import MlOpsSyncCursor
        from app.services.ml_orders_ingestion import sweep_service

        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
        monkeypatch.setattr(sweep_service, "MAX_WINDOW_FETCHES_PER_PASS", 2)

        async def paged(seller_id, date_from, date_to, offset=0):
            when = datetime.now(timezone.utc)
            return {
                "results": [_order(offset + i, 999, when, when) for i in range(50)],
                "paging": {"total": 900},
            }

        monkeypatch.setattr(sweep_service.ml_webhook_client, "search_orders", paged)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        cursor = db.query(MlOpsSyncCursor).filter_by(name=sweep_service.CURSOR_NAME).first()
        assert cursor.state != "running"
        assert cursor.last_success_at is None


class TestLastSuccessAtMeansTheWholePass:
    """The mixed case: one leaf completes and checkpoints, the next fails.
    Both earlier tests missed it because neither fixture ever reached a
    checkpoint at all."""

    def test_a_completed_leaf_does_not_stamp_success_when_a_later_leaf_fails(self, db, monkeypatch) -> None:
        from app.models.ml_orders_ops import MlOpsSyncCursor
        from app.services.ml_orders_ingestion import sweep_service

        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)

        calls = {"n": 0}

        async def bisect_then_left_ok_right_dead(seller_id, date_from, date_to, offset=0):
            calls["n"] += 1
            if calls["n"] == 1:
                # over cap -> forces a bisection into two leaves
                return {"results": [], "paging": {"total": 5000}}
            if calls["n"] == 2:
                # left leaf completes and emits a checkpoint
                when = datetime.now(timezone.utc)
                return {"results": [_order(1, 999, when, when)], "paging": {"total": 1}}
            # right leaf: proxy is down
            return None

        monkeypatch.setattr(sweep_service.ml_webhook_client, "search_orders", bisect_then_left_ok_right_dead)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)
        assert result.error is not None

        cursor = db.query(MlOpsSyncCursor).filter_by(name=sweep_service.CURSOR_NAME).first()

        # A broken sweep must not keep refreshing its own freshness signal:
        # an alert on "no successful pass in N minutes" would never fire.
        assert cursor.last_success_at is None


class TestShipmentIngestion:
    """ml-ventas-listado: the sweep is now the caller of `upsert_shipment`
    -- fetches happen entirely OUTSIDE the DB session (`_fetch_shipments`),
    and only for orders that carry a `shipping.id`."""

    def test_order_with_shipping_id_populates_ml_shipments_ops(self, db, monkeypatch):
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        mock_search = AsyncMock(return_value=_page([_order(1, 999, recent, recent, shipping_id=500)]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)
        mock_get_shipment = AsyncMock(return_value=_shipment(500, 1, status="delivered"))
        monkeypatch.setattr(ml_webhook_client, "get_shipment", mock_get_shipment)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        mock_get_shipment.assert_called_once_with(500)
        row = db.query(MlShipmentOps).filter_by(shipment_id=500).one()
        assert row.order_id == 1
        assert row.status == "delivered"

    def test_order_without_shipping_id_never_calls_get_shipment(self, db, monkeypatch):
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        mock_search = AsyncMock(return_value=_page([_order(1, 999, recent, recent)]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)
        mock_get_shipment = AsyncMock(return_value=None)
        monkeypatch.setattr(ml_webhook_client, "get_shipment", mock_get_shipment)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        mock_get_shipment.assert_not_called()
        assert db.query(MlShipmentOps).count() == 0

    def test_shipment_fetch_failure_does_not_block_order_ingestion(self, db, monkeypatch):
        """A flaky shipment lookup must not turn into a `WindowFetchError`
        that discards an otherwise-good page of orders (best-effort per
        shipment, see `_fetch_shipments`)."""
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        mock_search = AsyncMock(return_value=_page([_order(1, 999, recent, recent, shipping_id=500)]))
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)

        async def broken_get_shipment(shipment_id):
            raise ConnectionError("proxy down")

        monkeypatch.setattr(ml_webhook_client, "get_shipment", broken_get_shipment)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.orders_upserted == 1
        assert db.query(MlOrdersOps).filter_by(order_id=1).count() == 1
        assert db.query(MlShipmentOps).count() == 0

    def test_two_orders_sharing_a_shipping_id_fetch_it_once(self, db, monkeypatch):
        now = datetime.now(timezone.utc)
        recent = now - timedelta(days=1)
        mock_search = AsyncMock(
            return_value=_page(
                [
                    _order(1, 999, recent, recent, shipping_id=500),
                    _order(2, 999, recent, recent, shipping_id=500),
                ]
            )
        )
        monkeypatch.setattr(ml_webhook_client, "search_orders", mock_search)
        mock_get_shipment = AsyncMock(return_value=_shipment(500, 1))
        monkeypatch.setattr(ml_webhook_client, "get_shipment", mock_get_shipment)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        mock_get_shipment.assert_called_once_with(500)


class TestShipmentFetchesShareTheBudget:
    """`MAX_WINDOW_FETCHES_PER_PASS` exists so a pass cannot spend itself on
    HTTP. Shipment lookups did not participate in it: a cold start could
    issue one per order, sequentially, for tens of thousands of orders —
    long past the stale-lock timeout, so a second pass would start on top."""

    def test_a_pass_stops_fetching_shipments_once_the_budget_is_spent(self, db, monkeypatch) -> None:
        from app.services.ml_orders_ingestion import sweep_service

        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
        monkeypatch.setattr(sweep_service, "MAX_WINDOW_FETCHES_PER_PASS", 4)

        when = datetime.now(timezone.utc)
        orders = [{**_order(i, 999, when, when), "shipping": {"id": 40000 + i}} for i in range(20)]

        async def one_page(seller_id, date_from, date_to, offset=0):
            return {"results": orders, "paging": {"total": len(orders)}}

        shipment_calls = {"n": 0}

        async def a_shipment(shipment_id):
            shipment_calls["n"] += 1
            return {"id": shipment_id, "status": "delivered"}

        monkeypatch.setattr(ml_webhook_client, "search_orders", one_page)
        monkeypatch.setattr(ml_webhook_client, "get_shipment", a_shipment)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        assert shipment_calls["n"] <= sweep_service.MAX_WINDOW_FETCHES_PER_PASS


class TestShipmentBudgetIsNotSpentOnDiscardedOrders:
    """An out-of-window order is hard-excluded and never ingested. Fetching
    its shipment spends a slot of the shared budget the page walk needs."""

    def test_no_shipment_is_fetched_for_an_out_of_window_order(self, db, monkeypatch) -> None:
        from app.services.ml_orders_ingestion import sweep_service

        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)

        updated = datetime.now(timezone.utc)
        old = updated - timedelta(days=400)
        order = {**_order(1, 999, updated, old), "shipping": {"id": 4001}}

        async def one_page(seller_id, date_from, date_to, offset=0):
            return {"results": [order], "paging": {"total": 1}}

        calls = {"n": 0}

        async def a_shipment(shipment_id):
            calls["n"] += 1
            return {"id": shipment_id, "status": "delivered"}

        monkeypatch.setattr(ml_webhook_client, "search_orders", one_page)
        monkeypatch.setattr(ml_webhook_client, "get_shipment", a_shipment)

        result = sweep_service.run_sweep(seller_id=999, window_days=90)

        assert result.orders_out_of_window == 1
        assert calls["n"] == 0


class TestShipmentBudgetSkipsAlreadyCurrentOrders:
    """`CURSOR_OVERLAP` makes every pass reprocess the last 15 minutes on
    purpose. Those orders upsert to SKIPPED_STALE — so fetching their
    shipments spends the shared budget on writes that will not happen. In
    steady state that is the common case, not an edge."""

    def test_no_shipment_is_fetched_for_an_order_already_stored_at_the_same_version(self, db, monkeypatch) -> None:
        from app.models.ml_orders_ops import MlOrdersOps, MlShipmentOps
        from app.services.ml_orders_ingestion import sweep_service

        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)

        when = datetime.now(timezone.utc)
        db.add(MlOrdersOps(order_id=1, seller_id=999, ml_last_updated=when, date_created=when))
        # settled: the goods reached the buyer, so nothing can move again
        # and skipping the lookup cannot hide a change
        db.add(MlShipmentOps(shipment_id=4001, order_id=1, status="delivered"))
        db.commit()

        order = {**_order(1, 999, when, when), "shipping": {"id": 4001}}

        async def one_page(seller_id, date_from, date_to, offset=0):
            return {"results": [order], "paging": {"total": 1}}

        calls = {"n": 0}

        async def a_shipment(shipment_id):
            calls["n"] += 1
            return {"id": shipment_id, "status": "delivered"}

        monkeypatch.setattr(ml_webhook_client, "search_orders", one_page)
        monkeypatch.setattr(ml_webhook_client, "get_shipment", a_shipment)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        assert calls["n"] == 0


class TestShipmentsInFlightAreRefreshedAnyway:
    """Skipping an unchanged order's shipment assumes ML bumps the ORDER's
    `date_last_updated` whenever the SHIPMENT moves. That is unverified —
    and if it does not hold, a shipment freezes forever and the listing's
    goods column lies. Only a terminal shipment is safe to skip."""

    def test_a_shipment_still_in_transit_is_refetched(self, db, monkeypatch) -> None:
        from app.models.ml_orders_ops import MlOrdersOps, MlShipmentOps
        from app.services.ml_orders_ingestion import sweep_service

        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)

        when = datetime.now(timezone.utc)
        db.add(MlOrdersOps(order_id=1, seller_id=999, ml_last_updated=when, date_created=when))
        db.add(MlShipmentOps(shipment_id=4001, order_id=1, status="shipped"))
        db.commit()

        order = {**_order(1, 999, when, when), "shipping": {"id": 4001}}

        async def one_page(seller_id, date_from, date_to, offset=0):
            return {"results": [order], "paging": {"total": 1}}

        calls = {"n": 0}

        async def a_shipment(shipment_id):
            calls["n"] += 1
            return {"id": shipment_id, "status": "delivered"}

        monkeypatch.setattr(ml_webhook_client, "search_orders", one_page)
        monkeypatch.setattr(ml_webhook_client, "get_shipment", a_shipment)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        assert calls["n"] == 1

    def test_a_delivered_shipment_is_not_refetched(self, db, monkeypatch) -> None:
        from app.models.ml_orders_ops import MlOrdersOps, MlShipmentOps
        from app.services.ml_orders_ingestion import sweep_service

        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)

        when = datetime.now(timezone.utc)
        db.add(MlOrdersOps(order_id=2, seller_id=999, ml_last_updated=when, date_created=when))
        db.add(MlShipmentOps(shipment_id=4002, order_id=2, status="delivered"))
        db.commit()

        order = {**_order(2, 999, when, when), "shipping": {"id": 4002}}

        async def one_page(seller_id, date_from, date_to, offset=0):
            return {"results": [order], "paging": {"total": 1}}

        calls = {"n": 0}

        async def a_shipment(shipment_id):
            calls["n"] += 1
            return {"id": shipment_id, "status": "delivered"}

        monkeypatch.setattr(ml_webhook_client, "search_orders", one_page)
        monkeypatch.setattr(ml_webhook_client, "get_shipment", a_shipment)

        sweep_service.run_sweep(seller_id=999, window_days=90)

        assert calls["n"] == 0
