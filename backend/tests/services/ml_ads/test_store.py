"""ml-billing-balance PR 1b -- ADS-3/ADS-4/ADS-8 store: idempotent upserts, stale-row cleanup, sums by query."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.models.ml_ads import MlAdsAdGroupDay, MlAdsDayLedger, MlAdsItemDay
from app.services.ml_ads import mapper, store
from tests.services.ml_ads.captures import group_ads, load
from tests.services.ml_ads.replay import active_zero_cost, gauss_day

DAY = date(2026, 10, 5)
GAUSS = 25713
TPLINK = 714700
T0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=1)


def _groups(advertiser_id: int = GAUSS):
    """Every group fact of the captured day: the 72 cost-bearing ones, then the 19 active ones without cost."""
    facts = [f for page in gauss_day()["pages"] for f in mapper.map_groups_page(advertiser_id, DAY, page)]
    return sorted(facts, key=lambda f: (not f.needs_drill, f.ad_group_id))


def _items(group_id: int = 953712626, advertiser_id: int = GAUSS):
    return mapper.map_ads_page(advertiser_id, group_id, DAY, {"results": group_ads(group_id)})


def _count(db, model) -> int:
    return db.execute(select(func.count()).select_from(model)).scalar_one()


class TestIdempotentUpsert:
    def test_reingesting_unchanged_groups_keeps_counts_and_sums(self, pg_ads_db) -> None:
        store.upsert_groups(pg_ads_db, _groups(), fetch_started_at=T0, now=T0)
        store.upsert_groups(pg_ads_db, _groups(), fetch_started_at=T0, now=T0)
        assert _count(pg_ads_db, MlAdsAdGroupDay) == 72 + 19
        assert store.group_cost_sum(pg_ads_db, GAUSS, DAY) == Decimal("614060.07")

    def test_reingesting_unchanged_items_keeps_counts_and_sums(self, pg_ads_db) -> None:
        store.upsert_items(pg_ads_db, _items(), now=T0)
        store.upsert_items(pg_ads_db, _items(), now=T0)
        assert _count(pg_ads_db, MlAdsItemDay) == 4
        assert store.item_cost_by_group(pg_ads_db, GAUSS, DAY) == {953712626: Decimal("64692.18")}

    def test_a_changed_value_updates_the_row_instead_of_duplicating_it(self, pg_ads_db) -> None:
        store.upsert_items(pg_ads_db, _items(), now=T0)
        item = next(f for f in _items() if f.item_id == "MLA1150587086")
        changed = mapper.map_item(GAUSS, 953712626, DAY, {**item.raw, "metrics": {**item.raw["metrics"], "cost": 12.5}})
        store.upsert_items(pg_ads_db, [changed], now=T1)
        row = pg_ads_db.get(MlAdsItemDay, (GAUSS, 953712626, "MLA1150587086", DAY))
        assert (_count(pg_ads_db, MlAdsItemDay), row.cost) == (4, Decimal("12.50"))

    def test_zero_cost_group_is_stored_as_not_needed(self, pg_ads_db) -> None:
        zero = mapper.map_group(GAUSS, DAY, active_zero_cost(gauss_day())[0])
        store.upsert_groups(pg_ads_db, [zero, *_groups()[:1]], fetch_started_at=T0, now=T0)
        statuses = dict(pg_ads_db.execute(select(MlAdsAdGroupDay.ad_group_id, MlAdsAdGroupDay.drill_status)).all())
        assert statuses[zero.ad_group_id] == "not_needed"
        assert statuses[_groups()[0].ad_group_id] == "pending"


class TestMovedAndForeign:
    def test_moved_group_is_keyed_by_the_reporting_advertiser(self, pg_ads_db) -> None:
        raw = load("moved_group_2678077237.json")["group"]
        under_tplink = mapper.map_group(TPLINK, DAY, raw)
        under_gauss = mapper.map_group(GAUSS, DAY, raw)
        store.upsert_groups(pg_ads_db, [under_tplink, under_gauss], fetch_started_at=T0, now=T0)
        rows = (
            pg_ads_db.execute(select(MlAdsAdGroupDay.advertiser_id).order_by(MlAdsAdGroupDay.advertiser_id))
            .scalars()
            .all()
        )
        assert rows == [GAUSS, TPLINK]

    def test_foreign_item_is_stored_without_any_ownership_check(self, pg_ads_db) -> None:
        page = load("moved_group_2678077237.json")["ads_page"]["body"]
        facts = mapper.map_ads_page(TPLINK, 2678077237, DAY, page)
        store.upsert_items(pg_ads_db, facts, now=T0)
        assert _count(pg_ads_db, MlAdsItemDay) == len(facts) > 0
        assert pg_ads_db.get(MlAdsItemDay, (TPLINK, 2678077237, "MLA3623134932", DAY)) is not None


class TestRefetchCleanup:
    def test_stale_rows_of_the_day_are_deleted_and_current_ones_kept(self, pg_ads_db) -> None:
        old_groups = _groups()
        store.upsert_groups(pg_ads_db, old_groups, fetch_started_at=T0, now=T0)
        store.upsert_items(pg_ads_db, _items(), now=T0)
        store.upsert_groups(pg_ads_db, old_groups[:10], fetch_started_at=T1, now=T1)
        store.upsert_items(pg_ads_db, _items()[:1], now=T1)
        store.delete_stale(pg_ads_db, GAUSS, DAY, fetch_started_at=T1)
        assert (_count(pg_ads_db, MlAdsAdGroupDay), _count(pg_ads_db, MlAdsItemDay)) == (10, 1)

    def test_other_days_and_advertisers_are_untouched(self, pg_ads_db) -> None:
        store.upsert_groups(pg_ads_db, _groups(TPLINK)[:3], fetch_started_at=T0, now=T0)
        other_day = [mapper.map_group(GAUSS, date(2026, 10, 4), g.raw) for g in _groups()[:2]]
        store.upsert_groups(pg_ads_db, other_day, fetch_started_at=T0, now=T0)
        store.upsert_groups(pg_ads_db, _groups()[:5], fetch_started_at=T0, now=T0)
        store.delete_stale(pg_ads_db, GAUSS, DAY, fetch_started_at=T1)
        assert _count(pg_ads_db, MlAdsAdGroupDay) == 3 + 2  # only the 5 stale rows of (25713, DAY) went away


class TestDrillStatusAcrossFetches:
    def test_replaying_a_page_inside_the_same_fetch_keeps_done(self, pg_ads_db) -> None:
        group = _groups()[0]
        store.upsert_groups(pg_ads_db, [group], fetch_started_at=T0, now=T0)
        store.set_drill(pg_ads_db, GAUSS, group.ad_group_id, DAY, status="done", ads_offset=0)
        store.upsert_groups(pg_ads_db, [group], fetch_started_at=T0, now=T1)
        assert store.pending_groups(pg_ads_db, GAUSS, DAY) == []

    def test_a_new_fetch_makes_the_group_pending_again(self, pg_ads_db) -> None:
        group = _groups()[0]
        store.upsert_groups(pg_ads_db, [group], fetch_started_at=T0, now=T0)
        store.set_drill(pg_ads_db, GAUSS, group.ad_group_id, DAY, status="done", ads_offset=50)
        store.upsert_groups(pg_ads_db, [group], fetch_started_at=T1, now=T1)
        assert store.pending_groups(pg_ads_db, GAUSS, DAY) == [(group.ad_group_id, 0)]

    def test_pending_groups_carry_their_resume_offset(self, pg_ads_db) -> None:
        a, b, c = _groups()[:3]
        store.upsert_groups(pg_ads_db, [c, a, b], fetch_started_at=T0, now=T0)
        store.set_drill(pg_ads_db, GAUSS, b.ad_group_id, DAY, status="pending", ads_offset=50)
        store.set_drill(pg_ads_db, GAUSS, a.ad_group_id, DAY, status="done", ads_offset=0)
        assert store.pending_groups(pg_ads_db, GAUSS, DAY) == sorted([(b.ad_group_id, 50), (c.ad_group_id, 0)])


class TestLedger:
    def test_first_fetch_creates_a_fetching_row(self, pg_ads_db) -> None:
        ledger = store.start_fetch(pg_ads_db, GAUSS, DAY, now=T0)
        assert (ledger.source, ledger.status, ledger.fetch_started_at, ledger.groups_offset) == (
            "product_ads",
            "fetching",
            T0,
            0,
        )

    def test_an_unfinished_fetch_resumes_instead_of_restarting(self, pg_ads_db) -> None:
        store.start_fetch(pg_ads_db, GAUSS, DAY, now=T0)
        store.set_groups_offset(pg_ads_db, GAUSS, DAY, 400)
        ledger = store.start_fetch(pg_ads_db, GAUSS, DAY, now=T1)
        assert (ledger.fetch_started_at, ledger.groups_offset) == (T0, 400)

    def test_a_refetch_restarts_from_the_first_page(self, pg_ads_db) -> None:
        store.start_fetch(pg_ads_db, GAUSS, DAY, now=T0)
        store.finish_day(
            pg_ads_db, GAUSS, DAY, status="closed", summary=mapper.DaySummary(Decimal("1.00"), {"cost": 1.0}), now=T0
        )
        pg_ads_db.get(MlAdsDayLedger, ("product_ads", GAUSS, DAY)).status = "refetch"
        ledger = store.start_fetch(pg_ads_db, GAUSS, DAY, now=T1)
        assert (ledger.status, ledger.fetch_started_at, ledger.groups_offset) == ("fetching", T1, 0)

    def test_finish_stores_mls_total_status_and_no_sum_of_ours(self, pg_ads_db) -> None:
        store.start_fetch(pg_ads_db, GAUSS, DAY, now=T0)
        summary = mapper.parse_summary(load("campaigns_summary_2026_10_05.json")["25713"]["body"])
        ledger = store.finish_day(pg_ads_db, GAUSS, DAY, status="closed", summary=summary, now=T1)
        assert (ledger.status, ledger.summary_cost, ledger.closed_at) == ("closed", Decimal("614060.07"), T1)
        assert ledger.summary_raw == summary.raw

    def test_a_mismatch_day_is_not_stamped_closed(self, pg_ads_db) -> None:
        store.start_fetch(pg_ads_db, GAUSS, DAY, now=T0)
        summary = mapper.DaySummary(Decimal("614060.07"), {"cost": 614060.07})
        ledger = store.finish_day(pg_ads_db, GAUSS, DAY, status="mismatch", summary=summary, now=T1)
        assert (ledger.status, ledger.closed_at) == ("mismatch", None)
