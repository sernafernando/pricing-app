"""P5.T5: the honest-state block of the list (spec HON-1, UI-7), built from `status.build_status`.

`build_block` is pure over a report; the report cache is exercised with a fake builder and a fake clock.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from app.services.ml_publications.view import status_block
from app.services.ml_publications.view.status_block import ReportCache, build_block

GENERATED = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
DAY = 86400


def healthy(**overrides) -> dict:
    """A `build_status` report with every flag on, every resource collected and fresh data."""
    report = {
        "generated_at": GENERATED,
        "kill_switch": False,
        "flags": {"refresh": True, "intake": True, "events": True, "links": True},
        "items": {"total": 25000, "gone": 10, "by_status": {"active": 24000}},
        "completeness": {
            "sale_price": {"expected": True, "missing": 0, "non_2xx": {}},
            "stock": {"expected": True, "missing": 0, "non_2xx": {}},
        },
        "freshness": {"items": {"rows": 25000, "checked": 25000, "p95_age_seconds": 3600.0}},
        "sections_failed": [],
    }
    report.update(overrides)
    return report


def codes(block: dict) -> list[tuple[str, str]]:
    return [(d["code"], d.get("flag") or d.get("resource") or "") for d in block["degradations"]]


class TestBuildBlock:
    def test_all_flags_on_and_fresh_data_is_no_degradation(self) -> None:
        block = build_block(healthy())
        assert block["available"] is True
        assert block["degradations"] == [] and block["degraded"] is False
        assert block["store_empty"] is False and block["kill_switch"] is False
        assert block["generated_at"] == GENERATED

    def test_events_and_prices_disabled_are_both_named_with_what_they_affect(self) -> None:
        report = healthy(
            flags={"refresh": True, "intake": True, "events": False, "links": True},
            completeness={
                "sale_price": {"expected": False, "missing": 0, "non_2xx": {}},
                "stock": {"expected": True, "missing": 0, "non_2xx": {}},
            },
        )
        block = build_block(report)
        assert block["degraded"] is True
        assert codes(block) == [("flag_disabled", "events"), ("resource_not_collected", "sale_price")]
        by_code = {d["code"]: d for d in block["degradations"]}
        assert by_code["flag_disabled"]["affects"] == ["last_event", "evento"]
        assert by_code["resource_not_collected"]["affects"] == ["price"]

    def test_a_disabled_links_flag_and_an_uncollected_stock_resource(self) -> None:
        report = healthy(
            flags={"refresh": True, "intake": True, "events": True, "links": False},
            completeness={
                "sale_price": {"expected": True, "missing": 0, "non_2xx": {}},
                "stock": {"expected": False, "missing": 0, "non_2xx": {}},
            },
        )
        assert codes(build_block(report)) == [("flag_disabled", "links"), ("resource_not_collected", "stock")]

    def test_a_refresh_that_is_off_means_the_data_may_be_stale(self) -> None:
        report = healthy(flags={"refresh": False, "intake": True, "events": True, "links": True})
        (degradation,) = build_block(report)["degradations"]
        assert (degradation["code"], degradation["flag"]) == ("flag_disabled", "refresh")

    def test_the_kill_switch_is_reported_and_degrades(self) -> None:
        block = build_block(healthy(kill_switch=True))
        assert block["kill_switch"] is True and block["degraded"] is True
        assert ("kill_switch", "") in codes(block)

    def test_an_empty_store_is_flagged_as_such(self) -> None:
        block = build_block(healthy(items={"total": 0, "gone": 0, "by_status": {}}))
        assert block["store_empty"] is True and block["degraded"] is False

    def test_data_older_than_the_stale_window_is_a_degradation(self) -> None:
        fresh = build_block(healthy(freshness={"items": {"rows": 5, "checked": 5, "p95_age_seconds": 6 * DAY}}))
        stale = build_block(healthy(freshness={"items": {"rows": 5, "checked": 5, "p95_age_seconds": 8 * DAY}}))
        assert fresh["degradations"] == []
        assert codes(stale) == [("stale_data", "items")]

    def test_a_failed_section_is_reported_not_hidden(self) -> None:
        report = healthy(items=None, completeness=None, freshness=None, sections_failed=["items", "completeness"])
        block = build_block(report)
        assert block["available"] is True
        assert block["sections_failed"] == ["items", "completeness"]
        assert block["store_empty"] is None  # unknown, neither empty nor not
        assert block["degraded"] is True

    def test_a_report_without_a_sections_list_is_still_readable(self) -> None:
        report = healthy()
        del report["sections_failed"]
        assert build_block(report)["sections_failed"] == []


class TestReportCache:
    def make(self, builds: list[dict | Exception]):
        calls: list[int] = []
        clock = [1000.0]

        def build() -> dict:
            calls.append(1)
            result = builds[min(len(calls), len(builds)) - 1]
            if isinstance(result, Exception):
                raise result
            return result

        return ReportCache(build, ttl=60.0, failure_ttl=10.0, clock=lambda: clock[0]), calls, clock

    def test_a_block_within_the_ttl_is_served_without_rebuilding(self) -> None:
        cache, calls, clock = self.make([healthy()])
        first = cache.get()
        clock[0] += 59
        second = cache.get()
        assert len(calls) == 1 and first == second and first["available"] is True

    def test_after_the_ttl_the_report_is_built_again(self) -> None:
        cache, calls, clock = self.make([healthy(), healthy(kill_switch=True)])
        assert cache.get()["kill_switch"] is False
        clock[0] += 61
        assert cache.get()["kill_switch"] is True and len(calls) == 2

    def test_a_failing_build_answers_unavailable_and_retries_soon(self) -> None:
        cache, calls, clock = self.make([RuntimeError("db down"), healthy()])
        block = cache.get()
        assert block == {
            "available": False,
            "reason": "status_unavailable",
            "degraded": True,
            "degradations": [],
            "sections_failed": [],
            "store_empty": None,
            "kill_switch": None,
            "generated_at": None,
        }
        clock[0] += 5
        assert cache.get()["available"] is False and len(calls) == 1  # still inside the failure ttl
        clock[0] += 6
        assert cache.get()["available"] is True and len(calls) == 2

    def test_a_request_during_a_rebuild_gets_the_expired_block_instead_of_waiting(self) -> None:
        release, started = threading.Event(), threading.Event()
        clock = [1000.0]
        builds: list[int] = []

        def build() -> dict:
            builds.append(1)
            if len(builds) == 2:  # the rebuild after the ttl hangs until released
                started.set()
                assert release.wait(5)
                return healthy(kill_switch=True)
            return healthy()

        cache = ReportCache(build, ttl=60.0, failure_ttl=10.0, clock=lambda: clock[0])
        assert cache.get()["kill_switch"] is False
        clock[0] += 61
        rebuilding = threading.Thread(target=cache.get)
        rebuilding.start()
        assert started.wait(5)
        answered = []
        waiter = threading.Thread(target=lambda: answered.append(cache.get()))
        waiter.start()
        waiter.join(2)
        assert not waiter.is_alive(), "a request must not wait for the report to be rebuilt"
        assert answered[0]["kill_switch"] is False  # the expired block, still honest about its own time
        release.set()
        rebuilding.join(5)
        assert cache.get()["kill_switch"] is True and len(builds) == 2

    def test_a_build_that_is_cut_short_does_not_block_the_next_one(self) -> None:
        class Cancelled(BaseException):  # what a cancelled worker raises: not an Exception
            pass

        calls: list[int] = []

        def build() -> dict:
            calls.append(1)
            if len(calls) == 1:
                raise Cancelled()
            return healthy()

        cache = ReportCache(build, clock=lambda: 1000.0)
        try:
            cache.get()
        except Cancelled:
            pass
        assert cache.get()["available"] is True and len(calls) == 2  # not stuck on "someone is building"

    def test_a_reset_during_a_build_discards_that_build(self) -> None:
        release, started = threading.Event(), threading.Event()
        builds: list[int] = []

        def build() -> dict:
            builds.append(1)
            if len(builds) == 1:
                started.set()
                assert release.wait(5)
                return healthy(kill_switch=True)  # the report the reset made obsolete
            return healthy()

        cache = ReportCache(build, clock=lambda: 1000.0)
        building = threading.Thread(target=cache.get)
        building.start()
        assert started.wait(5)
        cache.reset()
        release.set()
        building.join(5)
        block = cache.get()  # not the discarded build: a new one runs
        assert block["kill_switch"] is False and len(builds) == 2

    def test_the_very_first_request_during_the_first_build_gets_a_pending_block(self) -> None:
        release, started = threading.Event(), threading.Event()

        def build() -> dict:
            started.set()
            assert release.wait(5)
            return healthy()

        cache = ReportCache(build, clock=lambda: 1000.0)
        first = threading.Thread(target=cache.get)
        first.start()
        assert started.wait(5)
        block = cache.get()
        assert block["available"] is False and block["reason"] == "status_pending"
        release.set()
        first.join(5)
        assert cache.get()["available"] is True

    def test_reset_forgets_the_cached_block(self) -> None:
        cache, calls, _ = self.make([healthy()])
        cache.get()
        cache.reset()
        cache.get()
        assert len(calls) == 2


def test_the_module_cache_is_a_report_cache_over_build_status() -> None:
    assert isinstance(status_block.REPORT, ReportCache)
