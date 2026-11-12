"""`ads_owner_select` on real Postgres (#2230): narrowing to the requested MLAs happens BEFORE the last-sale
aggregate, and the owner is still the same one the un-narrowed query resolves -- whatever the board's period, since
the owner reads ALL history (a sale long before any period still decides it)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import literal, select, text, union_all

from app.core.config import settings
from app.services.ml_ads.owner import NO_PRODUCT, ads_owner_select
from tests.services.ml_daily_metrics.test_board_postgres import _group, _order

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
OLD_ONLY = "MLA8100000001"  # no publication; its only sales are 400 and 500 days old
PUBLISHED = "MLA8100000002"  # published as product 42; sold as product 43 last year
UNKNOWN = "MLA8100000009"  # no publication, no sale


@pytest.fixture(autouse=True)
def _seller(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)


def _sell(db, order_id: int, product: int, mla: str, ago: timedelta) -> None:
    _order(db, order_id, [(product, mla, 1, 50)])
    _group(db, f"o:{order_id}", [order_id], NOW - ago)


@pytest.fixture()
def history(board_pg):
    db = board_pg
    _sell(db, 2000081000000001, 31, OLD_ONLY, timedelta(days=500))
    _sell(db, 2000081000000002, 32, OLD_ONLY, timedelta(days=400))
    _sell(db, 2000081000000003, 43, PUBLISHED, timedelta(days=380))
    db.execute(
        text(
            "INSERT INTO tb_mercadolibre_items_publicados (mlp_id, mlp_publicationid, item_id) "
            "VALUES (8100001, :mla, 42)"
        ),
        {"mla": PUBLISHED},
    )
    db.flush()
    return db


def _requested(*mlas: str):
    return select(union_all(*(select(literal(m)) for m in mlas)).subquery().c[0])


@pytest.mark.postgres
def test_an_mla_sold_only_outside_any_recent_period_still_resolves_to_its_last_sale(history) -> None:
    rows = dict(history.execute(ads_owner_select(sqlite=False, mlas=_requested(OLD_ONLY, PUBLISHED, UNKNOWN))).all())

    assert rows == {OLD_ONLY: 32, PUBLISHED: 42, UNKNOWN: NO_PRODUCT}


@pytest.mark.postgres
def test_narrowing_resolves_the_same_owners_as_the_whole_history(history) -> None:
    """Parity with the un-narrowed query (the path #2230 did not touch, as on origin/main)."""
    everyone = dict(history.execute(ads_owner_select(sqlite=False)).all())
    narrowed = dict(history.execute(ads_owner_select(sqlite=False, mlas=_requested(OLD_ONLY, PUBLISHED))).all())

    assert narrowed == {mla: everyone[mla] for mla in (OLD_ONLY, PUBLISHED)}
