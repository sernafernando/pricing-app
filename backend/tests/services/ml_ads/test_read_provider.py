"""ml-billing-balance 6-ii -- the native `MlAdsCostProvider` (design D9) and its adapter to the publications
view's `AdsCostProvider` Protocol. Cost comes from the captured, drilled 2026-10-05 group 953712626 (4 items)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.models.ml_ads import MlAdsDayLedger
from app.services.ml_ads import iva, mapper, read, store
from app.services.ml_publications.view.ads import AdsAvailability, UnavailableAdsProvider, get_ads_provider
from tests.services.ml_ads.captures import group_ads

DAY = date(2026, 10, 5)
GAUSS, TPLINK = 25713, 714700
T0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
GROUP = 953712626


def _seed(db, day: date = DAY, group: int = GROUP) -> dict[str, Decimal]:
    """Store the real ads of `group` on `day`; returns the MLA -> cost the capture says."""
    items = mapper.map_ads_page(GAUSS, group, day, {"results": group_ads(GROUP)})
    store.upsert_items(db, items, now=T0)
    costs: dict[str, Decimal] = {}
    for item in items:
        costs[item.item_id] = costs.get(item.item_id, Decimal(0)) + item.cost
    return costs


def _close(db, advertiser: int, day: date, status: str = "closed") -> None:
    db.add(MlAdsDayLedger(source="product_ads", advertiser_id=advertiser, day=day, status=status))
    db.flush()


class TestCostByMla:
    def test_sums_the_cost_per_mla_as_decimal(self, pg_ads_db) -> None:
        expected = _seed(pg_ads_db)
        result = read.MlAdsCostProvider().cost_by_mla(pg_ads_db, None, DAY, DAY)
        assert result == {mla: cost for mla, cost in expected.items() if cost > 0}
        assert sum(result.values()) == Decimal("64692.18")

    def test_sums_over_the_ad_days_in_range_only(self, pg_ads_db) -> None:
        one = _seed(pg_ads_db)
        _seed(pg_ads_db, DAY + timedelta(days=1))
        _seed(pg_ads_db, DAY + timedelta(days=30))
        result = read.MlAdsCostProvider().cost_by_mla(pg_ads_db, None, DAY, DAY + timedelta(days=1))
        assert result == {mla: cost * 2 for mla, cost in one.items() if cost > 0}

    def test_two_ad_groups_on_the_same_mla_add_up(self, pg_ads_db) -> None:
        one = _seed(pg_ads_db)
        _seed(pg_ads_db, group=GROUP + 1)  # the same real ad rows, reported under another group id
        result = read.MlAdsCostProvider().cost_by_mla(pg_ads_db, None, DAY, DAY)
        assert result == {mla: cost * 2 for mla, cost in one.items() if cost > 0}

    def test_mlas_narrows_and_unknown_mlas_are_absent(self, pg_ads_db) -> None:
        one = _seed(pg_ads_db)
        mla = next(m for m, c in one.items() if c > 0)
        result = read.MlAdsCostProvider().cost_by_mla(pg_ads_db, [mla, "MLA0"], DAY, DAY)
        assert result == {mla: one[mla]}

    def test_no_data_is_an_empty_mapping(self, pg_ads_db) -> None:
        assert read.MlAdsCostProvider().cost_by_mla(pg_ads_db, None, DAY, DAY) == {}

    def test_the_amount_goes_through_the_single_iva_function(self, pg_ads_db, monkeypatch) -> None:
        one = _seed(pg_ads_db)
        monkeypatch.setitem(iva.API_COST_INCLUDES_IVA, "product_ads", True)
        result = read.MlAdsCostProvider().cost_by_mla(pg_ads_db, None, DAY, DAY)
        assert result == {mla: cost / iva.IVA_ML_DIVISOR for mla, cost in one.items() if cost > 0}


class TestAvailability:
    def test_no_closed_day_is_no_data(self, pg_ads_db) -> None:
        _close(pg_ads_db, GAUSS, DAY, "fetching")
        got = read.MlAdsCostProvider().availability(pg_ads_db)
        assert (got.available, got.reason, got.data_through) == (False, "no_data", None)

    def test_data_through_stops_before_the_first_day_one_advertiser_misses(self, pg_ads_db) -> None:
        for advertiser in (GAUSS, TPLINK):
            _close(pg_ads_db, advertiser, DAY)
            _close(pg_ads_db, advertiser, DAY + timedelta(days=2))
        _close(pg_ads_db, GAUSS, DAY + timedelta(days=1), "mismatch")  # TPLINK has no row for D+1
        got = read.MlAdsCostProvider().availability(pg_ads_db)
        assert (got.available, got.reason, got.data_through) == (True, "ok", DAY)

    def test_an_advertiser_with_no_closed_day_holds_data_through_back(self, pg_ads_db) -> None:
        _close(pg_ads_db, GAUSS, DAY)
        _close(pg_ads_db, TPLINK, DAY, "fetching")
        got = read.MlAdsCostProvider().availability(pg_ads_db)
        assert (got.available, got.reason, got.data_through) == (True, "ok", None)

    def test_mismatch_days_count_as_covered(self, pg_ads_db) -> None:
        for offset, status in enumerate(["closed", "mismatch", "closed"]):
            _close(pg_ads_db, GAUSS, DAY + timedelta(days=offset), status)
        assert read.MlAdsCostProvider().availability(pg_ads_db).data_through == DAY + timedelta(days=2)


class TestTheViewAdapter:
    def test_it_is_available_when_the_native_answer_is(self, pg_ads_db) -> None:
        _close(pg_ads_db, GAUSS, DAY)
        assert read.ViewAdsProvider(pg_ads_db).availability() is AdsAvailability.AVAILABLE

    def test_it_is_unavailable_without_data(self, pg_ads_db) -> None:
        assert read.ViewAdsProvider(pg_ads_db).availability() is AdsAvailability.UNAVAILABLE

    def test_amounts_are_floats_and_none_means_every_mla_with_cost(self, pg_ads_db) -> None:
        expected = _seed(pg_ads_db)
        amounts = read.ViewAdsProvider(pg_ads_db).amounts(None, DAY, DAY)
        assert amounts == {mla: float(cost) for mla, cost in expected.items() if cost > 0}
        assert all(isinstance(v, float) for v in amounts.values())

    def test_amounts_honours_the_requested_mlas(self, pg_ads_db) -> None:
        mla = next(m for m, c in _seed(pg_ads_db).items() if c > 0)
        assert set(read.ViewAdsProvider(pg_ads_db).amounts([mla], DAY, DAY)) == {mla}


class TestWiring:
    def test_the_dependency_returns_the_adapter_bound_to_the_session(self, pg_ads_db) -> None:
        provider = get_ads_provider(pg_ads_db)
        assert isinstance(provider, read.ViewAdsProvider)

    def test_the_unavailable_stub_stays_for_tests(self) -> None:
        assert UnavailableAdsProvider().availability() is AdsAvailability.UNAVAILABLE
