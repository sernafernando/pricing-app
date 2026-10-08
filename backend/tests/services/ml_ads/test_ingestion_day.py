"""ml-billing-balance PR 1b -- ADS-1/2/4 one advertiser-day replayed from the 2026-10-05 captures."""

from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select

from app.models.ml_ads import MlAdsAdGroupDay, MlAdsDayLedger, MlAdsItemDay
from app.services.ml_ads import ingestion
from tests.services.ml_ads.replay import (
    ADS_RE,
    GROUPS_RE,
    SUMMARY_RE,
    FakeClock,
    Replay,
    active_zero_cost,
    cost_bearing,
    gauss_day,
    make_client,
    tplink_day,
)

DAY = date(2026, 10, 5)
GAUSS = 25713
TPLINK = 714700


@pytest.fixture()
def session_factory(pg_ads_db):
    @contextmanager
    def factory():
        try:
            yield pg_ads_db
            pg_ads_db.commit()
        except Exception:
            pg_ads_db.rollback()
            raise

    return factory


def _run(session_factory, replay, monkeypatch, advertiser_id, *, day=DAY, token=None, **kwargs):
    client = make_client(replay, monkeypatch, token=token)
    return ingestion.run_ads_step(session_factory, client, advertiser_id, day, now=replay.clock.now, **kwargs)


def _item_sum(db, group_id=None) -> Decimal:
    query = select(func.coalesce(func.sum(MlAdsItemDay.cost), 0))
    if group_id is not None:
        query = query.where(MlAdsItemDay.ad_group_id == group_id)
    return Decimal(db.execute(query).scalar_one())


def _ledger(db, advertiser_id=GAUSS) -> MlAdsDayLedger:
    return db.get(MlAdsDayLedger, ("product_ads", advertiser_id, DAY))


class TestGaussDayCloses:
    @pytest.fixture()
    def run(self, session_factory, pg_ads_db, monkeypatch):
        replay = Replay(FakeClock(), {GAUSS: gauss_day()})
        return replay, _run(session_factory, replay, monkeypatch, GAUSS)

    def test_day_closes_against_the_summary(self, run, pg_ads_db) -> None:
        _, result = run
        ledger = _ledger(pg_ads_db)
        assert (result.outcome, result.status) == ("closed", "closed")
        assert (ledger.status, ledger.summary_cost) == ("closed", Decimal("614060.07"))
        assert ledger.closed_at is not None
        assert _item_sum(pg_ads_db) == Decimal("614060.07")

    def test_all_28_group_pages_are_read(self, run) -> None:
        replay, _ = run
        assert replay.group_pages() == list(range(0, 5600, 200))

    def test_exactly_the_72_cost_bearing_groups_are_drilled(self, run, pg_ads_db) -> None:
        replay, _ = run
        spent = set(cost_bearing(gauss_day()))
        assert len(spent) == 72
        assert {group_id for group_id, _ in replay.ads_calls()} == spent
        statuses = [s for (s,) in pg_ads_db.execute(select(MlAdsAdGroupDay.drill_status)).all()]
        # The 19 real groups with organic units but no cost are stored too, and never drilled.
        assert (statuses.count("done"), statuses.count("not_needed")) == (72, len(active_zero_cost(gauss_day())))

    def test_ads_pages_are_read_by_paging_total_never_past_the_end(self, run) -> None:
        replay, _ = run
        # ML also answered an empty page past the end of two groups with exactly 50 ads; it is never requested.
        captured = {(g, p["paging"]["offset"]) for g, pages in gauss_day()["ads"].items() for p in pages}
        assert sorted(captured - set(replay.ads_calls())) == [(953674183, 50), (985516160, 50)]
        assert (len(captured), len(replay.ads_calls())) == (82, 80)

    def test_multi_page_group_sums_across_pages(self, run, pg_ads_db) -> None:
        replay, _ = run
        assert [o for g, o in replay.ads_calls() if g == 953639148] == [0, 50]
        assert _item_sum(pg_ads_db, group_id=953639148) == Decimal("36647.80")

    def test_one_summary_call_and_every_request_is_a_one_day_window(self, run) -> None:
        replay, _ = run
        assert len(replay.calls(SUMMARY_RE)) == 1
        for request in replay.requests:
            params = request.url.params
            assert params["date_from"] == params["date_to"] == "2026-10-05"
            assert "aggregation_type" not in params
            assert request.headers["Api-Version"] == "2"
        assert {r.url.params["limit"] for r in replay.calls(GROUPS_RE)} == {"200"}
        assert {r.url.params["limit"] for r in replay.calls(ADS_RE)} == {"50"}


class TestZeroSpendDay:
    def test_714700_closes_with_no_facts(self, session_factory, pg_ads_db, monkeypatch) -> None:
        replay = Replay(FakeClock(), {TPLINK: tplink_day()})
        result = _run(session_factory, replay, monkeypatch, TPLINK)
        ledger = _ledger(pg_ads_db, TPLINK)
        assert (result.outcome, ledger.status, ledger.summary_cost) == ("closed", "closed", Decimal("0.0"))
        assert replay.group_pages() == [0, 200]
        assert replay.ads_calls() == []
        assert pg_ads_db.execute(select(func.count()).select_from(MlAdsAdGroupDay)).scalar_one() == 0


class TestGroupsMustAddUpToTheDayTotal:
    def test_groups_that_do_not_add_up_to_the_summary_leave_the_day_in_mismatch(
        self, session_factory, pg_ads_db, monkeypatch
    ) -> None:
        day = copy.deepcopy(gauss_day())
        dropped = max(cost_bearing(day).values(), key=lambda g: g["metrics"]["cost"])
        for page in day["pages"]:
            page["results"] = [g for g in page["results"] if g["id"] != dropped["id"]]
        result = _run(session_factory, Replay(FakeClock(), {GAUSS: day}), monkeypatch, GAUSS)
        ledger = _ledger(pg_ads_db)
        assert (result.outcome, ledger.status, ledger.closed_at) == ("mismatch", "mismatch", None)
        # ML's figure is stored as received, so the gap stays visible.
        assert ledger.summary_cost == Decimal("614060.07")

    def test_a_few_cents_of_rounding_still_close(self, session_factory, pg_ads_db, monkeypatch) -> None:
        day = copy.deepcopy(gauss_day())
        day["summary"]["metrics_summary"]["cost"] = 614060.10
        result = _run(session_factory, Replay(FakeClock(), {GAUSS: day}), monkeypatch, GAUSS)
        assert (result.outcome, _ledger(pg_ads_db).summary_cost) == ("closed", Decimal("614060.1"))


class TestDrillMustAddUpToItsGroup:
    def test_ads_that_do_not_add_up_to_their_group_mark_the_drill_as_mismatch(
        self, session_factory, pg_ads_db, monkeypatch
    ) -> None:
        day = copy.deepcopy(gauss_day())
        ad = next(a for a in day["ads"][953712626][0]["results"] if a["item_id"] == "MLA1150587086")
        ad["metrics"]["cost"] = 63896.44  # 100.00 less than captured
        result = _run(session_factory, Replay(FakeClock(), {GAUSS: day}), monkeypatch, GAUSS)
        statuses = dict(pg_ads_db.execute(select(MlAdsAdGroupDay.ad_group_id, MlAdsAdGroupDay.drill_status)).all())
        assert statuses[953712626] == "mismatch"
        assert [g for g, s in statuses.items() if s == "mismatch"] == [953712626]
        assert _item_sum(pg_ads_db, group_id=953712626) == Decimal("64592.18")
        # The groups themselves add up to ML's total, yet the day does not close.
        ledger = _ledger(pg_ads_db)
        assert (result.outcome, ledger.status, ledger.closed_at) == ("mismatch", "mismatch", None)

    def test_a_cent_of_rounding_per_ad_still_marks_the_drill_done(
        self, session_factory, pg_ads_db, monkeypatch
    ) -> None:
        day = copy.deepcopy(gauss_day())
        ad = next(a for a in day["ads"][953712626][0]["results"] if a["item_id"] == "MLA1150587086")
        ad["metrics"]["cost"] = round(ad["metrics"]["cost"] + 0.01, 2)
        result = _run(session_factory, Replay(FakeClock(), {GAUSS: day}), monkeypatch, GAUSS)
        statuses = {s for (s,) in pg_ads_db.execute(select(MlAdsAdGroupDay.drill_status)).all()}
        assert "mismatch" not in statuses
        assert (result.outcome, _ledger(pg_ads_db).status) == ("closed", "closed")

    def test_an_ad_ml_no_longer_reports_does_not_count_against_a_refetched_drill(
        self, session_factory, pg_ads_db, monkeypatch
    ) -> None:
        clock = FakeClock()
        assert _run(session_factory, Replay(clock, {GAUSS: gauss_day()}), monkeypatch, GAUSS).outcome == "closed"
        # A previous fetch left an ad that ML no longer reports for this group.
        pg_ads_db.add(
            MlAdsItemDay(
                advertiser_id=GAUSS,
                ad_group_id=953712626,
                item_id="MLA_GONE",
                day=DAY,
                cost=Decimal("10.00"),
                raw={},
                fetched_at=clock.now(),
            )
        )
        pg_ads_db.flush()
        clock.sleep(3600)
        result = _run(session_factory, Replay(clock, {GAUSS: gauss_day()}), monkeypatch, GAUSS)
        statuses = {s for (s,) in pg_ads_db.execute(select(MlAdsAdGroupDay.drill_status)).all()}
        assert "mismatch" not in statuses
        assert (result.outcome, _ledger(pg_ads_db).status) == ("closed", "closed")
        assert _item_sum(pg_ads_db, group_id=953712626) == Decimal("64692.18")


class TestResumableInsideADay:
    def test_deadline_mid_groups_keeps_the_offset_and_resumes_there(
        self, session_factory, pg_ads_db, monkeypatch
    ) -> None:
        replay = Replay(FakeClock(), {GAUSS: gauss_day()})
        first = _run(session_factory, replay, monkeypatch, GAUSS, deadline=replay.clock.now() + timedelta(seconds=5))
        ledger = _ledger(pg_ads_db)
        assert (first.outcome, ledger.status, ledger.groups_offset) == ("deadline", "fetching", 1000)
        assert replay.group_pages() == [0, 200, 400, 600, 800]

        already = len(replay.requests)
        second = _run(session_factory, replay, monkeypatch, GAUSS)
        assert replay.group_pages()[5] == 1000 and replay.group_pages()[5:] == list(range(1000, 5600, 200))
        assert second.outcome == "closed" and len(replay.requests) > already
        assert _item_sum(pg_ads_db) == Decimal("614060.07")

    def test_deadline_mid_drill_resumes_the_half_read_group_and_skips_done_ones(
        self, session_factory, pg_ads_db, monkeypatch
    ) -> None:
        replay = Replay(FakeClock(), {GAUSS: gauss_day()})
        ids = sorted(cost_bearing(gauss_day()))
        # 28 group pages, every `/ads` page of the groups before 953635388, then the FIRST page of the 57-ad group.
        before = ids[: ids.index(953635388)]
        calls_before_stop = 28 + sum(len(gauss_day()["ads"][g]) for g in before) + 1
        first = _run(
            session_factory,
            replay,
            monkeypatch,
            GAUSS,
            deadline=replay.clock.now() + timedelta(seconds=calls_before_stop),
        )
        assert first.outcome == "deadline"
        half = pg_ads_db.get(MlAdsAdGroupDay, (GAUSS, 953635388, DAY))
        assert (half.drill_status, half.ads_offset) == ("pending", 50)
        done_before = {g for g, _ in replay.ads_calls()} - {953635388}
        assert len(done_before) == ids.index(953635388)

        already = len(replay.requests)
        second = _run(session_factory, replay, monkeypatch, GAUSS)
        resumed = [
            (int(r.url.path.split("/")[-2]), int(r.url.params["offset"]))
            for r in replay.requests[already:]
            if r.url.path.endswith("/ads")
        ]
        assert resumed[0] == (953635388, 50)
        assert not done_before & {g for g, _ in resumed}
        assert {g for g, _ in resumed} | done_before == set(ids)
        assert (second.outcome, _item_sum(pg_ads_db, group_id=953635388)) == ("closed", Decimal("31770.10"))

    def test_429_stops_the_run_with_the_day_still_fetching(self, session_factory, pg_ads_db, monkeypatch) -> None:
        replay = Replay(FakeClock(), {GAUSS: gauss_day()})
        replay.inject = lambda n, request: httpx.Response(429, headers={"retry-after": "60"}) if n == 40 else None
        result = _run(session_factory, replay, monkeypatch, GAUSS)
        ledger = _ledger(pg_ads_db)
        statuses = [s for (s,) in pg_ads_db.execute(select(MlAdsAdGroupDay.drill_status)).all()]
        assert (result.outcome, ledger.status, ledger.closed_at) == ("rate_limited", "fetching", None)
        assert 1 <= statuses.count("done") < 72 and statuses.count("done") + statuses.count("pending") == 72
        assert len(replay.requests) == 40  # nothing after the 429

        replay.inject = None
        again = _run(session_factory, replay, monkeypatch, GAUSS)
        assert (again.outcome, _item_sum(pg_ads_db)) == ("closed", Decimal("614060.07"))


class TestFailureHandling:
    def test_no_token_blocks_without_any_request(self, session_factory, monkeypatch) -> None:
        replay = Replay(FakeClock(), {GAUSS: gauss_day()})
        result = _run(session_factory, replay, monkeypatch, GAUSS, token={})
        assert (result.outcome, replay.requests) == ("blocked", [])

    def test_unauthorized_blocks(self, session_factory, monkeypatch) -> None:
        replay = Replay(FakeClock(), {GAUSS: gauss_day()})
        replay.inject = lambda n, request: httpx.Response(401, json={"message": "invalid token"})
        assert _run(session_factory, replay, monkeypatch, GAUSS).outcome == "blocked"

    def test_4xx_outside_the_retention_window_is_unavailable(self, session_factory, pg_ads_db, monkeypatch) -> None:
        old = date(2026, 6, 1)  # 129 days before the fake "today" (2026-10-08), retention is 90
        replay = Replay(FakeClock(), {GAUSS: gauss_day()})
        replay.inject = lambda n, request: httpx.Response(400, json={"message": "date out of range"})
        result = _run(session_factory, replay, monkeypatch, GAUSS, day=old)
        ledger = pg_ads_db.get(MlAdsDayLedger, ("product_ads", GAUSS, old))
        assert (result.outcome, ledger.status) == ("unavailable", "unavailable")
        assert "400" in ledger.last_error

    def test_4xx_inside_the_window_is_an_attempt_not_a_verdict(self, session_factory, pg_ads_db, monkeypatch) -> None:
        replay = Replay(FakeClock(), {GAUSS: gauss_day()})
        replay.inject = lambda n, request: httpx.Response(400, json={"message": "bad request"})
        result = _run(session_factory, replay, monkeypatch, GAUSS)
        ledger = _ledger(pg_ads_db)
        assert (result.outcome, ledger.status, ledger.attempts) == ("error", "fetching", 1)

    @pytest.mark.parametrize("failure", ["timeout", "503"])
    def test_failures_count_attempts_and_stop_after_five_per_local_day(
        self, failure, session_factory, pg_ads_db, monkeypatch
    ) -> None:
        def inject(n, request):
            if failure == "timeout":
                raise httpx.ReadTimeout("slow")
            return httpx.Response(503)

        clock = FakeClock()
        replay = Replay(clock, {GAUSS: gauss_day()})
        replay.inject = inject
        outcomes = [_run(session_factory, replay, monkeypatch, GAUSS).outcome for _ in range(5)]
        assert outcomes == ["error"] * 5
        assert _ledger(pg_ads_db).attempts == 5 and _ledger(pg_ads_db).last_error

        sent = len(replay.requests)
        assert _run(session_factory, replay, monkeypatch, GAUSS).outcome == "attempts_exhausted"
        assert len(replay.requests) == sent

        clock.advance(24 * 3600)  # next local day: the budget is renewed
        assert _run(session_factory, replay, monkeypatch, GAUSS).outcome == "error"
        assert (len(replay.requests) > sent, _ledger(pg_ads_db).attempts) == (True, 1)
