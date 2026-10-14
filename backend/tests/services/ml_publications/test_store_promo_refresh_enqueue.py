"""Reactivation queues the promotions-mirror refresh, in the transaction that writes the event.

Postgres only. Item bodies are the store's captured ones; a transition is a deep copy with `status` changed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.models.ml_publications import MlChangeLog
from app.services.ml_publications import events_store
from app.services.ml_publications import store as store_module
from app.services.ml_publications.settings_store import set_setting
from tests.services.ml_publications.conftest import sample_item
from tests.services.ml_publications.test_store_apply_fetch import ACTIVE, apply
from tests.services.ml_publications.test_store_events import flipped

pytestmark = pytest.mark.postgres

PAUSED = "MLA862580589"  # captured paused item, never seen active


@pytest.fixture
def queue_env(mlpub_pg):
    set_setting("events.enabled", True, "test")
    return mlpub_pg


def pending(engine) -> list[str]:
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT mla FROM promo_refresh_reactivation ORDER BY id"))]


def reactivate(item_id: str):
    """Real active item -> paused -> active again."""
    body = sample_item(item_id)
    apply(body, item_id, minutes=1)
    apply(flipped(body, status="paused"), item_id, minutes=5)
    return apply(body, item_id, minutes=10)


class TestReactivationEnqueue:
    def test_a_reactivation_queues_the_mla_due_now(self, queue_env) -> None:
        reactivate(ACTIVE)

        assert pending(queue_env) == [ACTIVE]
        with queue_env.connect() as conn:
            row = conn.execute(text("SELECT due_at, attempts, now() AS db_now FROM promo_refresh_reactivation")).one()
        assert row.attempts == 0 and abs((row.db_now - row.due_at).total_seconds()) < 60

    def test_pausing_alone_queues_nothing(self, queue_env) -> None:
        body = sample_item(ACTIVE)
        apply(body, ACTIVE, minutes=1)
        apply(flipped(body, status="paused"), ACTIVE, minutes=5)

        assert pending(queue_env) == []

    def test_a_first_activation_queues_nothing(self, queue_env) -> None:
        """real paused item (never seen active) -> active: `is_reactivation` is false."""
        body = sample_item(PAUSED)
        apply(body, PAUSED, minutes=1)
        apply(flipped(body, status="active"), PAUSED, minutes=5)

        with queue_env.connect() as conn:
            payload = conn.execute(
                text("SELECT payload FROM ml_item_events WHERE event_type='status_activated'")
            ).scalar()
        assert payload == {"is_reactivation": False}
        assert pending(queue_env) == []

    def test_replaying_the_same_change_log_row_queues_it_once(self, queue_env) -> None:
        reactivate(ACTIVE)
        with queue_env.connect() as conn:
            conn.execute(text("DELETE FROM promo_refresh_reactivation"))
            conn.commit()
        with store_module.database.get_background_db() as db:
            last = db.query(MlChangeLog).order_by(MlChangeLog.id.desc()).first()
            assert events_store.write_events(db, last) == 0  # event already stored: nothing new

        assert pending(queue_env) == []

    def test_a_second_reactivation_does_not_duplicate_an_already_queued_mla(self, queue_env) -> None:
        body = sample_item(ACTIVE)
        apply(body, ACTIVE, minutes=1)
        for minutes in (5, 15):
            apply(flipped(body, status="paused"), ACTIVE, minutes=minutes)
            apply(body, ACTIVE, minutes=minutes + 5)

        assert pending(queue_env) == [ACTIVE]

    def test_rederiving_history_never_queues(self, queue_env) -> None:
        reactivate(ACTIVE)
        with queue_env.connect() as conn:
            conn.execute(text("DELETE FROM promo_refresh_reactivation"))
            conn.execute(text("DELETE FROM ml_item_events"))
            conn.commit()
        with store_module.database.get_background_db() as db:
            assert events_store.rederive_events(db) >= 1

        assert pending(queue_env) == []


class TestQueueFailureIsIsolated:
    def test_a_broken_queue_never_costs_the_change_log_row_or_its_events(self, queue_env) -> None:
        with queue_env.begin() as conn:
            conn.execute(text("DROP TABLE promo_refresh_reactivation"))

        reactivate(ACTIVE)

        with queue_env.connect() as conn:
            kinds = [r[0] for r in conn.execute(text("SELECT event_type FROM ml_item_events ORDER BY id"))]
        assert kinds == ["status_paused", "status_activated"]
