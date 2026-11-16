"""A change the store records on an active catalog listing queues its catalog-competition snapshot refresh.

Postgres only. Item and sub-resource bodies are the store's captured ones; a change is a deep copy of a real body
with one field changed. Snapshot rows are synthetic (only the MLA and the consultation time matter here).
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.models.catalog_competition_refresh_pending import CatalogCompetitionRefreshPending
from app.models.ml_catalog_competition import MLCatalogCompetition
from app.services import catalog_competition_refresh_queue as queue
from app.services.ml_publications import store as store_module
from app.services.ml_publications.resources import RESOURCES
from app.services.ml_publications.store import apply_fetch
from tests.services.ml_publications.conftest import sample_item, subresource_body
from tests.services.ml_publications.test_subresource_store import apply as apply_sub
from tests.services.ml_publications.test_subresource_store import logs, response

pytestmark = pytest.mark.postgres

CATALOG = "MLA882393030"  # captured active catalog listing
PLAIN = "MLA874027718"  # captured active listing, not in a catalog
DEBOUNCE = timedelta(seconds=120)


@pytest.fixture
def env(mlpub_pg):
    CatalogCompetitionRefreshPending.__table__.create(bind=mlpub_pg)
    MLCatalogCompetition.__table__.create(bind=mlpub_pg)
    return mlpub_pg


def apply_item(body: dict, item_id: str, minutes: float):
    return apply_fetch(RESOURCES["item"], (item_id,), response("item", body, minutes=minutes))


def repriced(item_id: str, delta: float = 100.0) -> dict:
    body = sample_item(item_id)
    changed = copy.deepcopy(body)
    changed["price"] = float(body["price"]) + delta
    return changed


def change_item(item_id: str, *, status: str | None = None) -> None:
    """First sighting at minute 0, then a real change (the price) at minute 5."""
    body = sample_item(item_id)
    if status is not None:
        body["status"] = status
    apply_item(body, item_id, minutes=0)
    changed = repriced(item_id)
    if status is not None:
        changed["status"] = status
    apply_item(changed, item_id, minutes=5)


def pending(engine) -> list[dict]:
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT mla, due_at, attempts, now() AS db_now FROM catalog_competition_refresh_pending ORDER BY id"
                )
            ).mappings()
        ]


def add_snapshot(engine, mla: str, age: timedelta) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_catalog_competition (mla, fecha_consulta, fetch_status, competitors, competitor_count) "
                "VALUES (:m, now() - make_interval(secs => :s), 'ok', '[]', 0)"
            ),
            {"m": mla, "s": age.total_seconds()},
        )


def seconds_until_due(row: dict) -> float:
    return (row["due_at"] - row["db_now"]).total_seconds()


class TestItemChange:
    def test_a_change_of_an_active_catalog_listing_queues_it_after_the_debounce(self, env) -> None:
        change_item(CATALOG)

        (row,) = pending(env)
        assert row["mla"] == CATALOG and row["attempts"] == 0
        assert abs(seconds_until_due(row) - DEBOUNCE.total_seconds()) < 60

    def test_a_first_sighting_alone_queues_nothing(self, env) -> None:
        apply_item(sample_item(CATALOG), CATALOG, minutes=0)

        assert pending(env) == []

    def test_an_unchanged_body_queues_nothing(self, env) -> None:
        body = sample_item(CATALOG)
        apply_item(body, CATALOG, minutes=0)
        apply_item(body, CATALOG, minutes=5)

        assert pending(env) == []

    def test_a_listing_outside_any_catalog_is_not_queued(self, env) -> None:
        change_item(PLAIN)

        assert logs(env, "item")  # the change itself was recorded
        assert pending(env) == []

    def test_a_paused_catalog_listing_is_not_queued(self, env) -> None:
        change_item(CATALOG, status="paused")

        assert pending(env) == []


class TestMinimumGap:
    def test_a_snapshot_younger_than_the_gap_skips_the_refresh(self, env) -> None:
        add_snapshot(env, CATALOG, timedelta(minutes=10))

        change_item(CATALOG)

        assert pending(env) == []

    def test_a_snapshot_older_than_the_gap_queues_the_refresh(self, env) -> None:
        add_snapshot(env, CATALOG, timedelta(minutes=45))

        change_item(CATALOG)

        assert [r["mla"] for r in pending(env)] == [CATALOG]

    def test_only_the_snapshots_of_the_same_mla_count(self, env) -> None:
        add_snapshot(env, PLAIN, timedelta(minutes=1))

        change_item(CATALOG)

        assert [r["mla"] for r in pending(env)] == [CATALOG]


class TestBurst:
    def test_later_changes_keep_the_earlier_due_time(self, env) -> None:
        change_item(CATALOG)
        (first,) = pending(env)

        apply_item(repriced(CATALOG, delta=200.0), CATALOG, minutes=10)

        (second,) = pending(env)
        assert second["due_at"] == first["due_at"]

    def test_an_mla_already_due_now_stays_due_now(self, env) -> None:
        """hay_mejores (and the manual queue) make an MLA due now; a later change must not push it back."""
        with store_module.database.get_background_db() as db:
            queue.enqueue(db, [CATALOG], datetime.now(timezone.utc))

        change_item(CATALOG)

        (row,) = pending(env)
        assert seconds_until_due(row) <= 1

    def test_the_hay_mejores_enqueue_still_makes_a_queued_mla_due_now(self, env) -> None:
        change_item(CATALOG)

        with store_module.database.get_background_db() as db:
            queue.enqueue(db, [CATALOG], datetime.now(timezone.utc))

        (row,) = pending(env)
        assert seconds_until_due(row) <= 1 and row["attempts"] == 0


class TestSubResourceChange:
    def test_a_competition_change_queues_the_catalog_listing(self, env) -> None:
        apply_item(sample_item(CATALOG), CATALOG, minutes=0)
        winning = subresource_body("competition", "price_to_win_MLA882393030")
        competing = copy.deepcopy(winning)
        competing["status"] = "competing"
        apply_sub("competition", CATALOG, winning, minutes=1)

        apply_sub("competition", CATALOG, competing, minutes=2)

        assert [r["mla"] for r in pending(env)] == [CATALOG]

    def test_a_promotions_change_does_not_queue_it(self, env) -> None:
        """Promotions reach the queue through hay_mejores (no sale_price here, so it stays off), never this rule."""
        apply_item(sample_item(CATALOG), CATALOG, minutes=0)
        apply_sub("promotions", CATALOG, subresource_body("promotions", "promotions_MLA874027718"), minutes=1)

        apply_sub("promotions", CATALOG, subresource_body("promotions", "promotions_started_MLA2146576013"), minutes=2)

        assert logs(env, "promotions")
        assert pending(env) == []


class TestQueueFailureIsIsolated:
    def test_a_broken_queue_never_costs_the_change_log_row(self, env) -> None:
        with env.begin() as conn:
            conn.execute(text("DROP TABLE catalog_competition_refresh_pending"))

        change_item(CATALOG)

        assert [r["kind"] for r in logs(env, "item")] == ["change"]
