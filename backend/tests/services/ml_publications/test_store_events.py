"""Events written by `apply_fetch` in the same transaction as the change-log row (design D8, D15).

Postgres only. Every payload is a real capture; a transition is a deep copy of a real body
with the named fields changed. The `events.enabled` flag is a DB setting, off by default.
"""

from __future__ import annotations

import copy
import time

import pytest
from sqlalchemy import text

from app.services.ml_publications import events_store
from app.services.ml_publications import store as store_module
from app.services.ml_publications.events import ChangeRow, dedupe_key, derive_events
from app.services.ml_publications.settings_store import set_setting
from tests.services.ml_publications.conftest import bulk_item, sample_item
from tests.services.ml_publications.test_store_apply_fetch import (
    ACTIVE,
    PAUSED,
    apply,
    at,
    count,
    log_rows,
    only_not_found,
    run_concurrently,
)

pytestmark = pytest.mark.postgres


@pytest.fixture
def events_on(mlpub_pg):
    set_setting("events.enabled", True, "test")
    return mlpub_pg


def event_rows(engine, item_id: str | None = None):
    sql = "SELECT * FROM ml_item_events" + (" WHERE item_id = :i" if item_id else "") + " ORDER BY id"
    with engine.connect() as conn:
        return conn.execute(text(sql), {"i": item_id} if item_id else {}).mappings().all()


def types(engine, item_id: str) -> list[str]:
    return [row["event_type"] for row in event_rows(engine, item_id)]


def flipped(body: dict, **fields) -> dict:
    out = copy.deepcopy(body)
    out.update(fields)
    return out


class TestWriteWithTheChangeLog:
    def test_a_real_change_writes_its_events_with_the_denormalized_attribution(self, events_on) -> None:
        """real active item (store 57997) with status -> paused and sub_status -> ["out_of_stock"]."""
        body = sample_item(ACTIVE)
        apply(body, ACTIVE, minutes=1)

        outcome = apply(flipped(body, status="paused", sub_status=["out_of_stock"]), ACTIVE, minutes=5)

        (entry,) = log_rows(events_on, ACTIVE)
        (event,) = event_rows(events_on, ACTIVE)
        assert outcome.kind == "changed" and outcome.change_log_id == entry["id"] and outcome.events == 1
        assert event["event_type"] == "status_paused"
        assert (event["old_value"], event["new_value"]) == ("active", "paused")
        assert event["payload"] == {"old_sub_status": [], "new_sub_status": ["out_of_stock"]}
        assert event["change_log_id"] == entry["id"]
        assert event["observed_at"] == at(5) and event["source_last_updated"] == entry["source_last_updated"]
        assert event["official_store_id"] == 57997 and event["brand"] == entry["context"]["brand"]
        assert bytes(event["dedupe_key"]) == dedupe_key(entry["id"], "status_paused", None, None)

    def test_one_fetch_changing_status_and_title_yields_two_events_on_one_row(self, events_on) -> None:
        body = sample_item(ACTIVE)
        apply(body, ACTIVE, minutes=1)

        outcome = apply(flipped(body, status="paused", title=body["title"] + "!"), ACTIVE, minutes=5)

        (entry,) = log_rows(events_on, ACTIVE)
        assert outcome.events == 2
        assert sorted(types(events_on, ACTIVE)) == ["status_paused", "title_changed"]
        assert {row["change_log_id"] for row in event_rows(events_on, ACTIVE)} == {entry["id"]}

    def test_a_change_that_maps_to_no_event_still_writes_the_change_log_row(self, events_on) -> None:
        body = sample_item(ACTIVE)
        apply(body, ACTIVE, minutes=1)
        outcome = apply(flipped(body, warranty="Garantia de fabrica: 12 meses"), ACTIVE, minutes=5)
        assert outcome.kind == "changed" and outcome.events == 0
        assert len(log_rows(events_on, ACTIVE)) == 1 and event_rows(events_on) == []

    def test_gone_and_restored_write_item_gone_and_item_restored(self, events_on) -> None:
        body = sample_item(ACTIVE)
        apply(body, ACTIVE, minutes=1)
        only_not_found(ACTIVE, 2)
        apply(copy.deepcopy(body), ACTIVE, minutes=3)
        assert types(events_on, ACTIVE) == ["item_gone", "item_restored"]


class TestNoEventWithoutAChange:
    def test_first_sighting_identical_and_stale_fetches_create_none(self, events_on) -> None:
        body = sample_item(ACTIVE)
        apply(body, ACTIVE, minutes=5)
        apply(copy.deepcopy(body), ACTIVE, minutes=6)
        stale = flipped(body, status="paused")
        stale["last_updated"] = "2020-01-01T00:00:00.000Z"
        apply(stale, ACTIVE, minutes=7)
        assert event_rows(events_on) == [] and log_rows(events_on) == []

    def test_a_never_existing_404_creates_none(self, events_on) -> None:
        only_not_found("MLA1", 1)
        assert event_rows(events_on) == []


class TestFlag:
    def test_off_by_default_writes_the_change_log_and_no_event(self, mlpub_pg) -> None:
        body = sample_item(ACTIVE)
        apply(body, ACTIVE, minutes=1)

        outcome = apply(flipped(body, status="paused"), ACTIVE, minutes=5)

        assert outcome.kind == "changed" and outcome.events == 0
        assert len(log_rows(mlpub_pg, ACTIVE)) == 1 and event_rows(mlpub_pg) == []

    def test_explicitly_off_writes_no_event(self, mlpub_pg) -> None:
        set_setting("events.enabled", False, "test")
        body = sample_item(ACTIVE)
        apply(body, ACTIVE, minutes=1)
        apply(flipped(body, status="paused"), ACTIVE, minutes=5)
        assert len(log_rows(mlpub_pg, ACTIVE)) == 1 and event_rows(mlpub_pg) == []

    def test_an_unreadable_flag_fails_closed_and_never_blocks_the_change_log(self, mlpub_pg, monkeypatch) -> None:
        def broken(_handler):
            raise RuntimeError("settings store down")

        monkeypatch.setattr(store_module.settings_store, "is_enabled", broken)
        body = sample_item(ACTIVE)
        apply(body, ACTIVE, minutes=1)
        apply(flipped(body, status="paused"), ACTIVE, minutes=5)
        assert len(log_rows(mlpub_pg, ACTIVE)) == 1 and event_rows(mlpub_pg) == []


class TestAtomicity:
    def test_a_failure_on_the_event_insert_rolls_back_the_change_log_and_the_state(
        self, events_on, monkeypatch
    ) -> None:
        body = sample_item(ACTIVE)
        apply(body, ACTIVE, minutes=1)
        real = events_store.write_events

        def insert_then_fail(db, entry):
            real(db, entry)  # the events ARE in the transaction when it fails
            raise RuntimeError("injected failure after the event insert")

        monkeypatch.setattr(store_module.events_store, "write_events", insert_then_fail)
        with pytest.raises(RuntimeError, match="injected"):
            apply(flipped(body, status="paused"), ACTIVE, minutes=5)

        assert log_rows(events_on, ACTIVE) == [] and event_rows(events_on) == []
        with events_on.connect() as conn:
            assert (
                conn.execute(text("SELECT status FROM ml_items WHERE item_id = :i"), {"i": ACTIVE}).scalar() == "active"
            )


class TestIdempotencyAndOrdering:
    def test_flip_and_flip_back_produce_distinct_events(self, events_on) -> None:
        """real paused item: paused -> active -> paused -> active."""
        body = bulk_item(PAUSED)
        active = flipped(body, status="active", sub_status=[])
        apply(body, PAUSED, minutes=1)
        apply(active, PAUSED, minutes=2)
        apply(copy.deepcopy(body), PAUSED, minutes=3)
        apply(copy.deepcopy(active), PAUSED, minutes=4)

        rows = event_rows(events_on, PAUSED)
        assert [r["event_type"] for r in rows] == ["status_activated", "status_paused", "status_activated"]
        assert len({r["change_log_id"] for r in rows}) == 3 and len({bytes(r["dedupe_key"]) for r in rows}) == 3

    def test_two_concurrent_applies_of_one_transition_yield_one_event(self, events_on, monkeypatch) -> None:
        real = store_module.diff
        monkeypatch.setattr(store_module, "diff", lambda *a, **k: (time.sleep(0.3), real(*a, **k))[1])
        body = bulk_item(PAUSED)
        apply(body, PAUSED, minutes=1)
        changed = flipped(body, status="active", sub_status=[], available_quantity=3)

        run_concurrently(
            lambda: apply(copy.deepcopy(changed), PAUSED, minutes=5),
            lambda: apply(copy.deepcopy(changed), PAUSED, minutes=6),
        )

        assert len(log_rows(events_on, PAUSED)) == 1
        assert sorted(types(events_on, PAUSED)) == ["status_activated", "stock_replenished"]

    def test_writing_the_events_of_an_existing_row_again_is_a_no_op(self, events_on) -> None:
        body = sample_item(ACTIVE)
        apply(body, ACTIVE, minutes=1)
        apply(flipped(body, status="paused"), ACTIVE, minutes=5)

        with store_module.database.get_background_db() as db:
            entry = db.query(store_module.MlChangeLog).one()
            assert events_store.write_events(db, entry) == 0
        assert count(events_on, "ml_item_events") == 1


def snapshot(engine):
    """Every event column except the surrogate id, to compare two derivations."""
    return [
        {k: (bytes(v) if k == "dedupe_key" else v) for k, v in row.items() if k != "id"} for row in event_rows(engine)
    ]


class TestReDerivation:
    def test_deleted_events_are_rebuilt_identically_from_the_change_log_alone(self, events_on) -> None:
        a = sample_item(ACTIVE)
        paused = bulk_item(PAUSED)
        apply(a, ACTIVE, minutes=1)
        apply(flipped(a, status="paused", sub_status=["out_of_stock"], available_quantity=0), ACTIVE, minutes=2)
        apply(copy.deepcopy(a), ACTIVE, minutes=3)
        apply(paused, PAUSED, minutes=1)
        apply(flipped(paused, title=paused["title"] + "?"), PAUSED, minutes=2)
        only_not_found(PAUSED, 3)
        before = snapshot(events_on)
        assert len(before) >= 6

        with events_on.begin() as conn:  # the test, not the application, removes them
            conn.execute(text("DELETE FROM ml_item_events"))
            conn.execute(
                text("UPDATE ml_items SET status = 'x', brand = 'x', official_store_id = 1")
            )  # no state needed
        with store_module.database.get_background_db() as db:
            created = events_store.rederive_events(db)

        assert created == len(before)
        assert snapshot(events_on) == before

    def test_rederiving_over_existing_events_creates_nothing(self, events_on) -> None:
        body = sample_item(ACTIVE)
        apply(body, ACTIVE, minutes=1)
        apply(flipped(body, status="paused"), ACTIVE, minutes=2)
        with store_module.database.get_background_db() as db:
            assert events_store.rederive_events(db) == 0
        assert count(events_on, "ml_item_events") == 1

    def test_it_can_be_limited_to_one_item_and_runs_in_bounded_batches(self, events_on) -> None:
        for item_id, minutes in ((ACTIVE, 1), ("MLA882393030", 1)):
            body = sample_item(item_id)
            apply(body, item_id, minutes=minutes)
            apply(flipped(body, status="paused"), item_id, minutes=minutes + 1)
        with events_on.begin() as conn:
            conn.execute(text("DELETE FROM ml_item_events"))

        with store_module.database.get_background_db() as db:
            assert events_store.rederive_events(db, item_id=ACTIVE, batch_size=1) == 1
        assert [r["item_id"] for r in event_rows(events_on)] == [ACTIVE]

        with store_module.database.get_background_db() as db:
            assert events_store.rederive_events(db, batch_size=1) == 1  # the other item only
        assert count(events_on, "ml_item_events") == 2

    @pytest.mark.parametrize("size", [0, -1, events_store.MAX_BATCH_SIZE + 1])
    def test_an_out_of_range_batch_size_is_refused(self, events_on, size) -> None:
        with store_module.database.get_background_db() as db:
            with pytest.raises(ValueError, match="batch_size"):
                events_store.rederive_events(db, batch_size=size)

    def test_each_batch_is_committed_so_a_late_failure_keeps_the_earlier_batches(self, events_on, monkeypatch) -> None:
        for item_id in (ACTIVE, "MLA882393030"):
            body = sample_item(item_id)
            apply(body, item_id, minutes=1)
            apply(flipped(body, status="paused"), item_id, minutes=2)
        with events_on.begin() as conn:
            conn.execute(text("DELETE FROM ml_item_events"))
        real = events_store._insert
        calls = []

        def fail_on_the_second_batch(db, rows):
            calls.append([row.id for row in rows])
            if len(calls) == 2:
                raise RuntimeError("injected failure in batch 2")
            return real(db, rows)

        monkeypatch.setattr(events_store, "_insert", fail_on_the_second_batch)
        with pytest.raises(RuntimeError, match="batch 2"):
            with store_module.database.get_background_db() as db:
                events_store.rederive_events(db, batch_size=1)

        assert count(events_on, "ml_item_events") == 1

    def test_the_live_events_equal_the_ones_derived_from_the_stored_row(self, events_on) -> None:
        body = sample_item(ACTIVE)
        apply(body, ACTIVE, minutes=1)
        apply(flipped(body, status="paused", available_quantity=0), ACTIVE, minutes=2)
        (entry,) = log_rows(events_on, ACTIVE)
        derived = derive_events(
            ChangeRow(
                id=entry["id"],
                resource_type=entry["resource_type"],
                item_id=entry["item_id"],
                kind=entry["kind"],
                observed_at=entry["observed_at"],
                source_last_updated=entry["source_last_updated"],
                changes=entry["changes"],
                context=entry["context"],
            )
        )
        assert sorted(e.event_type for e in derived) == sorted(types(events_on, ACTIVE))
