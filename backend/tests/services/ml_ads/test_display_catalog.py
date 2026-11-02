"""ml-ads-cupones-display T1 (S6) -- the Display campaign catalog stored by the Display day step.

Replays the real `display/campaigns` answer of advertiser 25713 for 2026-10-05 (7 campaigns), captured in
`tests/fixtures/ml_ads/display_day_2026_10_05_25713.json`.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime

import pytest
import sqlalchemy as sa

from app.models.ml_ads import MlAdsDisplayCampaign
from app.services.ml_ads import ingestion, mapper
from tests.services.ml_ads.captures import load
from tests.services.ml_ads.replay import FakeClock, Replay, make_client

DAY = date(2026, 10, 5)
GAUSS = 25713
CAMPAIGNS = [259859, 281280, 290925, 294806, 301232, 335306, 340339]


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


def _step(session_factory, replay, monkeypatch) -> ingestion.StepResult:
    client = make_client(replay, monkeypatch)
    return ingestion.run_display_step(session_factory, client, GAUSS, DAY, now=replay.clock.now)


def _catalog(db) -> list[MlAdsDisplayCampaign]:
    return db.execute(sa.select(MlAdsDisplayCampaign).order_by(MlAdsDisplayCampaign.campaign_id)).scalars().all()


def test_the_mapper_ignores_entries_without_a_numeric_id() -> None:
    body = load("display_day_2026_10_05_25713.json")["campaigns"]["body"]
    real = body["results"][0]
    body["results"] += [{**real, "id": "340339"}, {**real, "id": None}, "not an entry"]  # perturbed copies

    rows = mapper.map_display_catalog(GAUSS, body)

    assert sorted(r.campaign_id for r in rows) == CAMPAIGNS == mapper.parse_display_campaigns(body)


@pytest.mark.postgres
def test_a_display_day_stores_the_catalog_and_a_second_run_updates_it_in_place(
    session_factory, pg_ads_db, monkeypatch
) -> None:
    replay = Replay(FakeClock(), {})
    assert _step(session_factory, replay, monkeypatch).outcome == "closed"

    rows = _catalog(pg_ads_db)
    assert [r.campaign_id for r in rows] == CAMPAIGNS
    assert {r.advertiser_id for r in rows} == {GAUSS}
    first = next(r for r in rows if r.campaign_id == 340339)
    assert (first.name, first.status, first.type, first.goal, first.site_id) == (
        "B110creativa",
        "paused",
        "PROGRAMMATIC",
        "conversion",
        "MLA",
    )
    assert (first.start_date, first.end_date) == (datetime(2026, 9, 11, 15, 0), datetime(2026, 9, 30, 23, 59, 59))
    assert first.raw["id"] == 340339 and first.raw["advertiser_id"] == GAUSS
    consideration = next(r for r in rows if r.campaign_id == 281280)
    assert (consideration.name, consideration.goal) == ("DisplayCatalogo-Consideracion", "consideration")
    updated_at = first.updated_at

    # ML renames a campaign (a perturbed copy of the real list): the row is updated, never duplicated.
    renamed = load("display_day_2026_10_05_25713.json")["campaigns"]["body"]
    renamed["results"][0]["name"] = "B110creativa v2"
    replay.display[GAUSS]["campaigns"] = renamed
    assert _step(session_factory, replay, monkeypatch).outcome == "closed"

    pg_ads_db.expire_all()
    rows = _catalog(pg_ads_db)
    assert [r.campaign_id for r in rows] == CAMPAIGNS
    again = next(r for r in rows if r.campaign_id == 340339)
    assert again.name == "B110creativa v2"
    assert again.updated_at > updated_at
