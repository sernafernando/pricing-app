"""ml-ads-display-contributions S2 -- brand contributions for Display: writes, overlap, locks and figures.

"si alguna marca nos aportó para el display también habría que descontarlo de ahí". A Display contribution covers
one Display campaign or, with no campaign, the whole Display account of its advertiser. It is validated against the
Display catalog, never overlaps another Display contribution covering the same spend, and covers that spend with
the Product Ads rules: `percentage` p% of each day row, `fixed_amount` spread by each row's share of its whole
range's spend.

Real Postgres. The Display days and catalog are the captured 2026-10-05 responses of advertiser 25713
(`display_day_2026_10_05_25713.json`): 335306 spent 27226.79, 301232 49464.21, 294806 68.67, 259859 45179.15
(121938.82 in all).
"""

from __future__ import annotations

import threading
import time
import dataclasses
from datetime import date
from decimal import Decimal
from typing import Optional

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models.ml_ads import MlAdsCampaign, MlAdsCampaignContribution, MlAdsDisplayCampaignDay
from app.models.producto import ProductoERP
from app.services.ml_ads import contributions, mapper, store
from tests.services.ml_ads.captures import load
from tests.services.ml_ads.test_display import _facts as display_facts
from tests.services.ml_ads.test_read_provider import T0

pytestmark = pytest.mark.postgres

GAUSS, TPLINK = 25713, 714700
XEROX, MIX, PVP, CATALOGO = 335306, 301232, 294806, 259859
PADS = 351001  # a Product Ads campaign of TPLINK (DERIVED catalog row)
OCT_5 = date(2026, 10, 5)
OCTOBER = (date(2026, 10, 1), date(2026, 10, 31))
COSTS = {XEROX: Decimal("27226.79"), MIX: Decimal("49464.21"), PVP: Decimal("68.67"), CATALOGO: Decimal("45179.15")}


def _seed(db) -> None:
    store.upsert_display_days(db, display_facts(), now=T0)
    body = load("display_day_2026_10_05_25713.json")["campaigns"]["body"]
    store.upsert_display_catalog(db, mapper.map_display_catalog(GAUSS, body), now=T0)
    db.add(MlAdsCampaign(advertiser_id=TPLINK, campaign_id=PADS, raw={}))  # DERIVED: a Product Ads catalog row
    db.add(ProductoERP(item_id=1, codigo="COD1", descripcion="Toner", marca="XEROX"))  # DERIVED: the brand's ERP row
    db.flush()


def _data(
    campaign_id: Optional[int],
    kind: str = "percentage",
    value: str = "10",
    first: date = OCTOBER[0],
    last: date = OCTOBER[1],
    settlement: Optional[str] = None,
    channel: str = "display",
    advertiser_id: int = GAUSS,
) -> contributions.ContributionData:
    return contributions.ContributionData(
        advertiser_id, campaign_id, kind, Decimal(value), first, last, "Xerox", None, settlement, channel
    )


def _rows(db) -> list[tuple]:
    db.expire_all()
    return [
        (r.advertiser_id, r.campaign_id, r.channel, r.kind, r.value)
        for r in db.query(MlAdsCampaignContribution).order_by(MlAdsCampaignContribution.id)
    ]


@pytest.fixture()
def db(pg_ads_db):
    _seed(pg_ads_db)
    return pg_ads_db


class TestCreate:
    def test_a_whole_account_contribution_is_stored_without_a_campaign(self, db) -> None:
        row = contributions.create(db, _data(None), 7)
        assert (row.channel, row.campaign_id, row.created_by_id) == ("display", None, 7)
        assert _rows(db) == [(GAUSS, None, "display", "percentage", Decimal("10.00"))]

    def test_a_campaign_contribution_names_a_display_campaign(self, db) -> None:
        contributions.create(db, _data(XEROX), 7)
        assert _rows(db) == [(GAUSS, XEROX, "display", "percentage", Decimal("10.00"))]

    def test_without_a_channel_it_is_product_ads_as_before(self, db) -> None:
        data = contributions.ContributionData(
            TPLINK, PADS, "percentage", Decimal("30"), *OCTOBER, "Xerox", None
        )  # the positional shape existing callers use
        assert contributions.create(db, data, 7).channel == "product_ads"

    @pytest.mark.parametrize(
        "data",
        [
            _data(999),  # not in the Display catalog
            _data(PADS, advertiser_id=TPLINK),  # a Product Ads campaign is not a Display one
            _data(XEROX, channel="product_ads"),  # a Display campaign is not a Product Ads one
            _data(None, advertiser_id=TPLINK),  # an advertiser without Display campaigns has no Display account
            _data(None, channel="product_ads"),  # Product Ads always names its campaign
        ],
        ids=["unknown", "pads-as-display", "display-as-pads", "no-display-account", "pads-without-campaign"],
    )
    def test_a_campaign_outside_its_channel_catalog_is_rejected_on_campaign_id(self, db, data) -> None:
        with pytest.raises(contributions.ContributionError) as err:
            contributions.create(db, data, 7)
        assert err.value.field == "campaign_id"
        assert _rows(db) == []


class TestOverlap:
    @pytest.mark.parametrize(
        "first, second",
        [(XEROX, XEROX), (None, None), (None, XEROX), (XEROX, None)],
        ids=["same-campaign", "whole-twice", "campaign-inside-whole", "whole-over-campaign"],
    )
    def test_display_ranges_covering_the_same_spend_are_rejected_on_date_from(self, db, first, second) -> None:
        contributions.create(db, _data(first), 7)
        with pytest.raises(contributions.ContributionError) as err:
            contributions.create(db, _data(second, first=date(2026, 10, 31), last=date(2026, 11, 15)), 7)
        assert err.value.field == "date_from"
        assert len(_rows(db)) == 1

    def test_ranges_that_never_cover_the_same_spend_are_fine(self, db) -> None:
        contributions.create(db, _data(None), 7)
        contributions.create(db, _data(None, first=date(2026, 11, 1), last=date(2026, 11, 30)), 7)  # adjacent
        contributions.create(db, _data(XEROX, first=date(2026, 12, 1), last=date(2026, 12, 31)), 7)
        contributions.create(db, _data(MIX, first=date(2026, 12, 1), last=date(2026, 12, 31)), 7)  # other campaign
        assert len(_rows(db)) == 4

    def test_a_product_ads_contribution_with_the_same_ids_and_days_is_another_channel(self, db) -> None:
        db.add(MlAdsCampaign(advertiser_id=GAUSS, campaign_id=XEROX, raw={}))  # DERIVED: an id in both catalogs
        db.flush()
        contributions.create(db, _data(XEROX), 7)
        contributions.create(db, _data(XEROX, channel="product_ads"), 7)
        assert {r[2] for r in _rows(db)} == {"display", "product_ads"}


class TestUpdate:
    def test_an_edit_keeps_its_own_range_out_of_the_overlap(self, db) -> None:
        row = contributions.create(db, _data(None), 7)
        edited = contributions.update(db, row.id, _data(None, value="25", last=date(2026, 10, 20)), 8)
        assert (edited.value, edited.date_to, edited.updated_by_id) == (Decimal("25.00"), date(2026, 10, 20), 8)

    @pytest.mark.parametrize(
        "change, field",
        [
            ({"campaign_id": XEROX}, "campaign_id"),  # whole account -> one campaign
            ({"advertiser_id": TPLINK}, "campaign_id"),  # the whole account of another advertiser
        ],
        ids=["to-a-campaign", "to-another-advertiser"],
    )
    def test_an_edit_cannot_move_the_contribution(self, db, change, field) -> None:
        row = contributions.create(db, _data(None), 7)
        base = dict(vars(_data(None)))
        with pytest.raises(contributions.ContributionError) as err:
            contributions.update(db, row.id, contributions.ContributionData(**{**base, **change}), 8)
        assert err.value.field == field
        assert _rows(db) == [(GAUSS, None, "display", "percentage", Decimal("10.00"))]

    def test_an_edit_cannot_change_the_channel(self, db) -> None:
        db.add(MlAdsCampaign(advertiser_id=GAUSS, campaign_id=XEROX, raw={}))  # DERIVED: an id in both catalogs
        db.flush()
        row = contributions.create(db, _data(XEROX), 7)
        with pytest.raises(contributions.ContributionError) as err:
            contributions.update(db, row.id, _data(XEROX, channel="product_ads"), 8)
        assert err.value.field == "channel"
        assert [r[2] for r in _rows(db)] == ["display"]


class TestRobust:
    """ml-ads-aportes-robust S1 on Postgres, for a Display aporte."""

    def test_the_brand_is_stored_as_the_catalog_spells_it(self, db) -> None:
        row = contributions.create(db, dataclasses.replace(_data(None), brand=" xerox "), 7)
        assert row.brand == "XEROX"

    def test_a_brand_with_no_products_is_rejected_on_brand(self, db) -> None:
        with pytest.raises(contributions.ContributionError) as error:
            contributions.create(db, dataclasses.replace(_data(None), brand="Epson"), 7)
        assert error.value.field == "brand"
        assert _rows(db) == []


def _saved(db, *data: contributions.ContributionData) -> None:
    for d in data:
        contributions.create(db, d, 7)


class TestFigures:
    def test_a_whole_account_percentage_covers_that_share_of_every_campaign(self, db) -> None:
        _saved(db, _data(None))
        got = contributions.display_contributions(db, OCT_5, OCT_5)
        assert got == {(GAUSS, c): cost / 10 for c, cost in COSTS.items()}
        assert sum(got.values()) == Decimal("12193.882")

    def test_a_campaign_contribution_covers_only_its_campaign(self, db) -> None:
        _saved(db, _data(MIX, value="50"))
        assert contributions.display_contributions(db, OCT_5, OCT_5) == {(GAUSS, MIX): Decimal("24732.105")}

    def test_a_fixed_amount_is_spread_by_the_share_of_its_whole_range_spend(self, db) -> None:
        # DERIVED: one more day of 335306 so the range spends 200000 and the window (10-05) holds 121938.82 of it.
        db.add(
            MlAdsDisplayCampaignDay(
                advertiser_id=GAUSS,
                campaign_id=XEROX,
                day=date(2026, 10, 6),
                consumed_budget=Decimal("78061.18"),
                raw={},
            )
        )
        _saved(db, _data(None, kind="fixed_amount", value="20000", settlement="full"))
        got = contributions.display_contributions(db, OCT_5, OCT_5)
        assert got[(GAUSS, XEROX)] == Decimal("2722.679")  # 20000 x 27226.79 / 200000
        assert sum(got.values()) == Decimal("12193.882")  # 20000 x 121938.82 / 200000
        whole = contributions.display_contributions(db, *OCTOBER)
        assert sum(whole.values()) == Decimal("20000")

    def test_a_refund_difference_counts_only_up_to_the_range_spend(self, db) -> None:
        _saved(db, _data(None, kind="fixed_amount", value="500000", settlement="refund_difference"))
        assert contributions.display_contributions(db, *OCTOBER) == {(GAUSS, c): cost for c, cost in COSTS.items()}

    def test_days_outside_the_window_or_another_channel_cover_nothing(self, db) -> None:
        db.add(MlAdsCampaign(advertiser_id=GAUSS, campaign_id=XEROX, raw={}))  # DERIVED: an id in both catalogs
        db.flush()
        _saved(db, _data(XEROX, channel="product_ads"), _data(MIX))
        assert contributions.display_contributions(db, date(2026, 10, 6), date(2026, 10, 31)) == {}
        assert contributions.display_contributions(db, OCT_5, OCT_5) == {(GAUSS, MIX): Decimal("4946.421")}

    def test_the_preview_of_a_display_contribution_reads_the_display_days(self, db) -> None:
        whole = contributions.preview(db, _data(None))
        assert (whole.spend, whole.counted) == (Decimal("121938.82"), Decimal("12193.882"))
        one = contributions.preview(
            db, _data(XEROX, kind="fixed_amount", value="30000", settlement="refund_difference")
        )
        assert (one.spend, one.counted) == (COSTS[XEROX], COSTS[XEROX])
        assert _rows(db) == []  # a preview writes nothing

    def test_the_product_ads_listing_ignores_display_contributions(self, db) -> None:
        db.add(MlAdsCampaign(advertiser_id=GAUSS, campaign_id=XEROX, raw={}))  # DERIVED: an id in both catalogs
        db.flush()
        _saved(db, _data(XEROX))
        rows = {
            (r.campaign.advertiser_id, r.campaign.campaign_id): r for r in contributions.list_campaigns(db, *OCTOBER)
        }
        assert (rows[(GAUSS, XEROX)].contributions, rows[(GAUSS, XEROX)].contribution) == ([], Decimal(0))


# ── concurrency: a whole-account load and a campaign load of one advertiser serialize ──

HOLD = 0.6  # seconds the first session keeps its locks


@pytest.fixture()
def sessions(pg_ads_engine):
    make = sessionmaker(bind=pg_ads_engine)
    with make() as db:
        _seed(db)
        db.commit()
    yield make
    with pg_ads_engine.begin() as conn:
        for table in ("ml_ads_campaign_contributions", "ml_ads_display_campaigns", "ml_ads_display_campaign_days"):
            conn.execute(text(f"DELETE FROM {table}"))
        conn.execute(text("DELETE FROM ml_ads_campaigns"))


def _hold(make, data: contributions.ContributionData, locked: threading.Event) -> None:
    with make() as db:
        contributions._check(db, data)
        db.add(MlAdsCampaignContribution(**vars(data), created_by_id=1, updated_by_id=1))
        db.flush()
        locked.set()
        time.sleep(HOLD)
        db.commit()


@pytest.mark.parametrize(
    "held, loaded",
    [(XEROX, None), (None, XEROX)],
    ids=["whole-waits-for-campaign", "campaign-waits-for-whole"],
)
def test_a_load_waits_for_the_other_scope_lock_and_is_rejected(sessions, held, loaded) -> None:
    locked = threading.Event()
    holder = threading.Thread(target=_hold, args=(sessions, _data(held), locked))
    holder.start()
    assert locked.wait(5)
    started = time.monotonic()
    with pytest.raises(contributions.ContributionError) as err:
        with sessions() as db:
            contributions.create(db, _data(loaded, first=date(2026, 10, 15), last=date(2026, 10, 20)), 2)
    elapsed = time.monotonic() - started
    holder.join()
    assert elapsed >= HOLD * 0.8 and err.value.field == "date_from"
    with sessions() as db:
        assert db.query(MlAdsCampaignContribution).count() == 1
