"""ml-billing-balance PR 3-iii -- Brand Ads day ingestion: one `(advertiser, day)` per `run_brand_step` (ADS-10).

The ML side is the real client over the captured Brand Ads answers of 2026-10-05 (one call per advertiser, every
figure zero). A test that needs spend edits a deep copy of a real body and says so: no number here was sent by ML.
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import date, timedelta

import httpx
import pytest
import sqlalchemy as sa

from app.models.ml_ads import MlAdsBrandDay, MlAdsDayLedger
from app.services.ml_ads import ingestion
from tests.services.ml_ads.replay import FakeClock, Replay, brand_ads, make_client

pytestmark = pytest.mark.postgres

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


def _replay(**kwargs) -> Replay:
    return Replay(FakeClock(), {}, **kwargs)  # no Product Ads day: Brand Ads is its own pipeline


def _step(session_factory, replay, monkeypatch, advertiser=GAUSS, day=DAY, **kwargs):
    client = make_client(replay, monkeypatch)
    return ingestion.run_brand_step(session_factory, client, advertiser, day, now=replay.clock.now, **kwargs)


def _ledger(db, advertiser=GAUSS, day=DAY) -> MlAdsDayLedger:
    return db.get(MlAdsDayLedger, ("brand_ads", advertiser, day))


def _spend(db) -> dict[tuple[int, date], str]:
    rows = db.execute(sa.select(MlAdsBrandDay)).scalars().all()
    return {(r.advertiser_id, r.day): str(r.cost) for r in rows}


def _spent(advertiser: int, cost: float, summary: float | None = None) -> dict:
    """A real body with the day's cost edited (test only); `summary` defaults to the same figure."""
    body = copy.deepcopy(brand_ads()[advertiser])
    body["dashboard"]["consumed_budget"][0]["y"] = cost
    body["summary"]["consumed_budget"] = cost if summary is None else summary
    return body


class TestBrandDay:
    @pytest.mark.parametrize("advertiser", [GAUSS, TPLINK])
    def test_an_all_zero_day_stores_nothing_but_the_ledger_closes(
        self, session_factory, pg_ads_db, monkeypatch, advertiser
    ) -> None:
        replay = _replay()

        step = _step(session_factory, replay, monkeypatch, advertiser=advertiser)

        assert (step.outcome, step.status, step.calls) == ("closed", "closed", 1)
        assert len(replay.brand_calls()) == 1
        ledger = _ledger(pg_ads_db, advertiser)
        assert (ledger.status, ledger.summary_cost, ledger.closed_at is not None) == ("closed", 0, True)
        assert ledger.summary_raw["consumed_budget"] == 0.0  # ML's own day total, kept as sent
        assert _spend(pg_ads_db) == {}
        assert pg_ads_db.get(MlAdsDayLedger, ("product_ads", advertiser, DAY)) is None

    def test_a_day_with_spend_is_stored_informationally_and_the_ledger_total_is_ML_s(
        self, session_factory, pg_ads_db, monkeypatch
    ) -> None:
        replay = _replay(brand={GAUSS: _spent(GAUSS, 321.5)})

        step = _step(session_factory, replay, monkeypatch)

        assert (step.outcome, step.status) == ("closed", "closed")
        assert _spend(pg_ads_db) == {(GAUSS, DAY): "321.50"}
        assert _ledger(pg_ads_db).summary_cost == 321.5

    def test_a_dashboard_that_disagrees_with_the_summary_keeps_the_day_open_as_mismatch(
        self, session_factory, pg_ads_db, monkeypatch
    ) -> None:
        replay = _replay(brand={GAUSS: _spent(GAUSS, 100, summary=90)})

        step = _step(session_factory, replay, monkeypatch)

        assert (step.outcome, step.status) == ("mismatch", "mismatch")
        assert _ledger(pg_ads_db).closed_at is None

    def test_refetching_drops_a_day_that_lost_its_activity(self, session_factory, pg_ads_db, monkeypatch) -> None:
        _step(session_factory, _replay(brand={GAUSS: _spent(GAUSS, 50)}), monkeypatch)
        assert _spend(pg_ads_db) == {(GAUSS, DAY): "50.00"}

        replay = _replay()  # ML restated the day: the real all-zero answer
        replay.clock.advance(3600)
        _step(session_factory, replay, monkeypatch)

        assert _spend(pg_ads_db) == {}
        assert _ledger(pg_ads_db).status == "closed"

    def test_rows_of_another_advertiser_or_day_survive_a_refetch(self, session_factory, pg_ads_db, monkeypatch) -> None:
        _step(session_factory, _replay(brand={TPLINK: _spent(TPLINK, 7)}), monkeypatch, advertiser=TPLINK)
        next_day = DAY + timedelta(days=1)
        redated = _spent(GAUSS, 9)
        redated["dashboard"]["consumed_budget"][0]["x"] = next_day.isoformat()  # real body re-dated, test only
        _step(session_factory, _replay(brand={GAUSS: redated}), monkeypatch, day=next_day)
        replay = _replay()  # the real all-zero answer for GAUSS on DAY
        replay.clock.advance(3600)

        _step(session_factory, replay, monkeypatch)

        assert _spend(pg_ads_db) == {(TPLINK, DAY): "7.00", (GAUSS, next_day): "9.00"}

    def test_brand_days_are_never_verified(self, session_factory, monkeypatch) -> None:
        run = ingestion._BrandRun(session_factory, make_client(_replay(), monkeypatch), GAUSS, DAY, lambda: None, None)
        with pytest.raises(NotImplementedError):
            run.verify()


class TestFailures:
    def test_a_429_stops_with_the_day_still_fetching(self, session_factory, pg_ads_db, monkeypatch) -> None:
        replay = _replay()
        replay.inject = lambda n, request: httpx.Response(429, headers={"retry-after": "60"})

        step = _step(session_factory, replay, monkeypatch)

        assert (step.outcome, step.status) == ("rate_limited", "fetching")
        assert _spend(pg_ads_db) == {}

    def test_a_5xx_counts_one_attempt(self, session_factory, pg_ads_db, monkeypatch) -> None:
        replay = _replay()
        replay.inject = lambda n, request: httpx.Response(503)

        step = _step(session_factory, replay, monkeypatch)

        ledger = _ledger(pg_ads_db)
        assert (step.outcome, ledger.attempts, ledger.last_error) == ("error", 1, "HTTP 503")

    def test_an_answer_without_summary_cost_is_an_error_not_a_zero_day(
        self, session_factory, pg_ads_db, monkeypatch
    ) -> None:
        body = brand_ads()[GAUSS]
        del body["summary"]  # a real body missing the part the ledger closes on (test only)
        replay = _replay(brand={GAUSS: body})

        step = _step(session_factory, replay, monkeypatch)

        ledger = _ledger(pg_ads_db)
        assert (step.outcome, ledger.status, ledger.attempts) == ("error", "fetching", 1)
        assert "summary" in ledger.last_error

    def test_a_deadline_before_the_call_sends_nothing(self, session_factory, monkeypatch) -> None:
        replay = _replay()

        step = _step(session_factory, replay, monkeypatch, deadline=replay.clock.now())

        assert (step.outcome, step.calls, replay.brand_calls()) == ("deadline", 0, [])
