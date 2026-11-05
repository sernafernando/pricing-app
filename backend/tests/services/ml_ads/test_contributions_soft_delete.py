"""ml-ads-aportes-robust S6 -- "soft delete": deleting an aporte marks it (who and when) instead of removing it.

The row stays with `deleted_at` and `deleted_by_id`; every read ignores it: the loading page, the Display tab, the
overlap check, edit and delete. Runs on real Postgres (`pg_ads_write_db`). Campaigns, item days, Display days and the
ERP product are DERIVED rows.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import pytest

from app.models.ml_ads import (
    MlAdsCampaign,
    MlAdsCampaignContribution,
    MlAdsDisplayCampaign,
    MlAdsDisplayCampaignDay,
    MlAdsItemDay,
)
from app.models.producto import ProductoERP
from app.services.ml_ads import contributions

pytestmark = pytest.mark.postgres

ADV, CAMP, GAUSS, DISPLAY_CAMP = 714700, 351001, 25713, 335306
USER, OTHER_USER = 7, 8
OCTOBER = (date(2026, 10, 1), date(2026, 10, 31))


@pytest.fixture()
def db(pg_ads_write_db):
    s = pg_ads_write_db
    s.add(MlAdsCampaign(advertiser_id=ADV, campaign_id=CAMP, raw={}))
    s.add(MlAdsDisplayCampaign(advertiser_id=GAUSS, campaign_id=DISPLAY_CAMP, raw={}))
    s.add(ProductoERP(item_id=1, codigo="COD1", descripcion="Router", marca="TP-Link"))
    s.add(
        MlAdsItemDay(
            advertiser_id=ADV,
            ad_group_id=1,
            item_id="MLA1",
            day=date(2026, 10, 5),
            campaign_id=CAMP,
            cost=Decimal("1000"),
            raw={},
        )
    )
    s.add(
        MlAdsDisplayCampaignDay(
            advertiser_id=GAUSS, campaign_id=DISPLAY_CAMP, day=date(2026, 10, 5), consumed_budget=Decimal("400"), raw={}
        )
    )
    s.flush()
    return s


def _data(
    value: str = "30", channel: str = "product_ads", campaign: Optional[int] = CAMP, advertiser: int = ADV
) -> contributions.ContributionData:
    return contributions.ContributionData(
        advertiser, campaign, "percentage", Decimal(value), *OCTOBER, "tp-link", None, None, channel
    )


def _display() -> contributions.ContributionData:
    return _data("25", channel="display", campaign=DISPLAY_CAMP, advertiser=GAUSS)


def test_a_delete_keeps_the_row_marked_with_who_and_when(db) -> None:
    row = contributions.create(db, _data(), USER)
    assert contributions.delete(db, row.id, OTHER_USER) is True
    db.expire_all()
    [kept] = db.query(MlAdsCampaignContribution).all()
    assert (kept.id, kept.deleted_by_id, kept.value) == (row.id, OTHER_USER, Decimal("30.00"))
    assert kept.deleted_at is not None


def test_a_delete_keeps_the_last_edit_as_it_was(db) -> None:
    """`updated_at` / `updated_by_id` keep describing the last edit; who deleted it and when live in their own columns."""
    row = contributions.create(db, _data(), USER)
    edited_at = datetime(2026, 10, 2, 9, 30, tzinfo=timezone.utc)
    db.query(MlAdsCampaignContribution).filter_by(id=row.id).update({"updated_at": edited_at})
    db.flush()
    contributions.delete(db, row.id, OTHER_USER)
    db.expire_all()
    kept = db.get(MlAdsCampaignContribution, row.id)
    assert (kept.updated_at, kept.updated_by_id, kept.deleted_by_id) == (edited_at, USER, OTHER_USER)


def test_a_deleted_aporte_cannot_be_deleted_or_edited_again(db) -> None:
    row = contributions.create(db, _data(), USER)
    contributions.delete(db, row.id, USER)
    assert contributions.delete(db, row.id, USER) is False
    assert contributions.update(db, row.id, _data("50"), USER) is None
    db.expire_all()
    assert db.get(MlAdsCampaignContribution, row.id).value == Decimal("30.00")


def test_the_loading_page_ignores_a_deleted_aporte(db) -> None:
    row = contributions.create(db, _data(), USER)
    contributions.delete(db, row.id, USER)
    [campaign] = contributions.list_campaigns(db, *OCTOBER)
    assert (campaign.contributions, campaign.contribution, campaign.cost) == ([], Decimal(0), Decimal("1000"))


def test_a_deleted_range_no_longer_blocks_loading_it_again(db) -> None:
    row = contributions.create(db, _data(), USER)
    contributions.delete(db, row.id, USER)
    again = contributions.create(db, _data("40"), USER)
    [campaign] = contributions.list_campaigns(db, *OCTOBER)
    assert [c.id for c in campaign.contributions] == [again.id]
    assert campaign.contribution == Decimal("400.00")


def test_the_display_tab_ignores_a_deleted_display_aporte(db) -> None:
    row = contributions.create(db, _display(), USER)
    assert contributions.display_contributions(db, *OCTOBER) == {(GAUSS, DISPLAY_CAMP): Decimal("100.00")}
    contributions.delete(db, row.id, USER)
    assert sum(contributions.display_contributions(db, *OCTOBER).values(), Decimal(0)) == Decimal(0)
    contributions.create(db, _display(), USER)  # the same range loads again
