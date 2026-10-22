"""ml-ads-brand-contribution T1b -- two loads on one campaign serialize on the campaign row (regression pin).

Real Postgres sessions: A checks and inserts a range while holding the campaign lock; B loading an overlapping
range of the same campaign waits for A's commit and is then rejected (the API's 422 on `date_from`). A different
campaign does not wait.
"""

from __future__ import annotations

import threading
import time
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models.ml_ads import MlAdsCampaign, MlAdsCampaignContribution
from app.services.ml_ads import contributions

ADV, CAMP, OTHER = 714700, 351001, 351002
HOLD = 0.6  # seconds A keeps the lock


def _data(campaign_id: int, start: int, end: int) -> contributions.ContributionData:
    return contributions.ContributionData(
        ADV, campaign_id, "percentage", Decimal("30"), date(2026, 10, start), date(2026, 10, end), None, None
    )


@pytest.fixture()
def sessions(pg_ads_engine):
    make = sessionmaker(bind=pg_ads_engine)
    with make() as db:
        for campaign_id in (CAMP, OTHER):
            db.add(MlAdsCampaign(advertiser_id=ADV, campaign_id=campaign_id, raw={}))
        db.commit()
    yield make
    with pg_ads_engine.begin() as conn:
        conn.execute(text("DELETE FROM ml_ads_campaign_contributions"))
        conn.execute(text("DELETE FROM ml_ads_campaigns"))


def _hold_lock(make, locked: threading.Event) -> None:
    with make() as db:
        data = _data(CAMP, 1, 31)
        contributions._check(db, data)
        db.add(MlAdsCampaignContribution(**vars(data), created_by_id=1, updated_by_id=1))
        db.flush()
        locked.set()
        time.sleep(HOLD)
        db.commit()


def _load_while_locked(make, data: contributions.ContributionData):
    locked = threading.Event()
    holder = threading.Thread(target=_hold_lock, args=(make, locked))
    holder.start()
    assert locked.wait(5)
    started = time.monotonic()
    try:
        with make() as db:
            contributions.create(db, data, 2)
        outcome = None
    except contributions.ContributionError as exc:
        outcome = exc
    elapsed = time.monotonic() - started
    holder.join()
    return outcome, elapsed


def _count(make, campaign_id: int) -> int:
    with make() as db:
        return db.query(MlAdsCampaignContribution).filter_by(campaign_id=campaign_id).count()


@pytest.mark.postgres
def test_an_overlapping_load_waits_for_the_lock_and_is_rejected(sessions) -> None:
    error, elapsed = _load_while_locked(sessions, _data(CAMP, 15, 20))
    assert elapsed >= HOLD * 0.8
    assert error is not None and error.field == "date_from"
    assert _count(sessions, CAMP) == 1


@pytest.mark.postgres
def test_another_campaign_does_not_wait(sessions) -> None:
    error, elapsed = _load_while_locked(sessions, _data(OTHER, 15, 20))
    assert error is None and elapsed < HOLD * 0.5
    assert (_count(sessions, CAMP), _count(sessions, OTHER)) == (1, 1)
