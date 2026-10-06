"""`store.apply_fetch`: the transactional upsert of one fetched item (design D8).

Postgres only (row locks, jsonb, arrays). Every payload is a real capture; a
transition is a deep copy of a real body with the named fields changed.
"""

from __future__ import annotations

import copy
import dataclasses
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services.ml_publications import diff as diff_module
from app.services.ml_publications import store as store_module
from app.services.ml_publications.canonical import canonical_hash
from app.services.ml_publications.ml_http import MlResponse
from app.services.ml_publications.resources import RESOURCES
from app.services.ml_publications.store import ApplyCounters, apply_fetch
from tests.services.ml_publications.conftest import (
    bulk_item,
    item_404_bulk_element,
    item_404_single,
    item_with_variations,
    sample_item,
)

pytestmark = pytest.mark.postgres

SPEC = RESOURCES["item"]
T0 = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def ok(body, minutes: float = 0, status: int = 200) -> MlResponse:
    """A response whose request started one second before it was received."""
    received = at(minutes)
    return MlResponse(
        endpoint="items_bulk",
        status=status,
        body=body,
        headers={},
        request_started_at=received - timedelta(seconds=1),
        received_at=received,
    )


def apply(body, item_id: str, minutes: float = 0, status: int = 200, **kwargs):
    return apply_fetch(SPEC, (item_id,), ok(body, minutes, status), **kwargs)


def item_row(engine, item_id: str):
    with engine.connect() as conn:
        return conn.execute(text("SELECT * FROM ml_items WHERE item_id = :i"), {"i": item_id}).mappings().first()


def log_rows(engine, item_id: str | None = None):
    sql = "SELECT * FROM ml_change_log" + (" WHERE item_id = :i" if item_id else "") + " ORDER BY id"
    with engine.connect() as conn:
        return conn.execute(text(sql), {"i": item_id} if item_id else {}).mappings().all()


def count(engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()


PAUSED = "MLA935110613"  # paused, sub_status ["out_of_stock"], available_quantity 0


class TestFirstSighting:
    def test_writes_raw_typed_hash_and_first_seen_without_log_or_event(self, mlpub_pg) -> None:
        body = bulk_item(PAUSED)
        outcome = apply(body, PAUSED, minutes=1)

        row = item_row(mlpub_pg, PAUSED)
        assert outcome.kind == "first_seen"
        assert outcome.change_log_id is None and outcome.events == 0
        assert row["raw"] == body
        assert bytes(row["raw_hash"]) == canonical_hash(body, SPEC)
        assert row["status"] == "paused" and row["sub_status"] == ["out_of_stock"] and row["brand"] == "Marvo"
        assert row["http_status"] == 200 and row["never_existed"] is False and row["gone_at"] is None
        assert row["first_seen_at"] is not None
        assert row["fetched_at"] == at(1) and row["last_checked_at"] == at(1)
        assert count(mlpub_pg, "ml_change_log") == 0
        assert count(mlpub_pg, "ml_item_events") == 0

    def test_unknown_extra_top_level_field_is_preserved_in_raw(self, mlpub_pg) -> None:
        """real payload, one field added (a top-level field the mapper does not know)."""
        body = bulk_item(PAUSED)
        body["brand_new_ml_field"] = {"nested": [1, 2, 3]}
        apply(body, PAUSED)
        assert item_row(mlpub_pg, PAUSED)["raw"]["brand_new_ml_field"] == {"nested": [1, 2, 3]}

    def test_other_items_do_not_share_state(self, mlpub_pg) -> None:
        apply(bulk_item(PAUSED), PAUSED)
        apply(bulk_item("MLA934406852"), "MLA934406852")
        assert item_row(mlpub_pg, "MLA934406852")["catalog_listing"] is True
        assert item_row(mlpub_pg, PAUSED)["catalog_listing"] is False


class TestIdenticalFetch:
    def test_updates_only_last_checked_at(self, mlpub_pg) -> None:
        body = bulk_item(PAUSED)
        apply(body, PAUSED, minutes=1)
        before = dict(item_row(mlpub_pg, PAUSED))

        outcome = apply(copy.deepcopy(body), PAUSED, minutes=10)

        after = dict(item_row(mlpub_pg, PAUSED))
        assert outcome.kind == "unchanged"
        assert after.pop("last_checked_at") == at(10)
        assert before.pop("last_checked_at") == at(1)
        assert after == before  # raw, raw_hash, typed columns and fetched_at untouched
        assert count(mlpub_pg, "ml_change_log") == 0

    def test_key_reordering_is_not_a_change(self, mlpub_pg) -> None:
        """real payload, keys / attributes / tags reordered."""
        body = bulk_item(PAUSED)
        apply(body, PAUSED, minutes=1)
        reordered = {key: body[key] for key in reversed(list(body))}
        reordered["attributes"] = list(reversed(body["attributes"]))
        reordered["tags"] = list(reversed(body["tags"]))
        assert reordered != body

        outcome = apply(reordered, PAUSED, minutes=2)

        assert outcome.kind == "unchanged"
        assert count(mlpub_pg, "ml_change_log") == 0
        assert item_row(mlpub_pg, PAUSED)["raw"] == body  # stored state untouched


class TestChangedFetch:
    def test_writes_one_change_log_row_and_updates_state(self, mlpub_pg) -> None:
        """real payload, status paused->active and available_quantity 0->3 (last_updated moves forward)."""
        body = bulk_item(PAUSED)
        apply(body, PAUSED, minutes=1)
        changed = copy.deepcopy(body)
        changed["status"] = "active"
        changed["available_quantity"] = 3
        changed["last_updated"] = "2026-10-06T11:59:00.000Z"

        outcome = apply(changed, PAUSED, minutes=5)

        logs = log_rows(mlpub_pg, PAUSED)
        assert outcome.kind == "changed" and outcome.events == 0 and outcome.change_log_id == logs[0]["id"]
        assert len(logs) == 1
        entry = logs[0]
        assert (entry["resource_type"], entry["entity_id"], entry["item_id"], entry["kind"]) == (
            "item",
            PAUSED,
            PAUSED,
            "change",
        )
        assert sorted(entry["changed_paths"]) == ["available_quantity", "last_updated", "status"]
        by_path = {c["p"]: c for c in entry["changes"]}
        assert by_path["status"] == {"p": "status", "op": "replace", "old": "paused", "new": "active"}
        assert by_path["available_quantity"]["old"] == 0 and by_path["available_quantity"]["new"] == 3
        assert entry["observed_at"] == at(5)
        assert bytes(entry["prev_hash"]) == canonical_hash(body, SPEC)
        assert bytes(entry["new_hash"]) == canonical_hash(changed, SPEC)
        assert entry["source_last_updated"] == datetime(2026, 10, 6, 11, 59, tzinfo=timezone.utc)

        row = item_row(mlpub_pg, PAUSED)
        assert row["raw"] == changed and bytes(row["raw_hash"]) == canonical_hash(changed, SPEC)
        assert row["status"] == "active" and row["available_quantity"] == 3
        assert row["fetched_at"] == at(5) and row["last_checked_at"] == at(5)

    def test_unknown_field_appearing_later_is_logged_as_an_add(self, mlpub_pg) -> None:
        """real payload, one top-level field added."""
        body = bulk_item(PAUSED)
        apply(body, PAUSED, minutes=1)
        changed = copy.deepcopy(body)
        changed["brand_new_ml_field"] = "x"

        apply(changed, PAUSED, minutes=2)

        (entry,) = log_rows(mlpub_pg, PAUSED)
        assert entry["changes"] == [{"p": "brand_new_ml_field", "op": "add", "new": "x"}]
        assert item_row(mlpub_pg, PAUSED)["raw"]["brand_new_ml_field"] == "x"


class TestStaleProtection:
    def test_older_last_updated_is_discarded_and_counted(self, mlpub_pg) -> None:
        """real payload, last_updated moved to 2026-09-30 and the title changed."""
        body = sample_item("MLA874027718")  # last_updated 2026-10-02T19:21:52.100Z
        apply(body, "MLA874027718", minutes=1)
        before = dict(item_row(mlpub_pg, "MLA874027718"))
        older = copy.deepcopy(body)
        older["last_updated"] = "2026-09-30T00:00:00.000Z"
        older["title"] = "an older title"
        counters = ApplyCounters()

        outcome = apply(older, "MLA874027718", minutes=9, counters=counters)

        assert outcome.kind == "stale" and outcome.change_log_id is None
        assert dict(item_row(mlpub_pg, "MLA874027718")) == before
        assert count(mlpub_pg, "ml_change_log") == 0
        assert counters.stale_discarded == 1

    def test_equal_last_updated_with_different_content_is_evaluated_as_a_change(self, mlpub_pg) -> None:
        """real payload, title changed, last_updated untouched (ML mutates sub-fields without bumping it)."""
        body = sample_item("MLA874027718")
        apply(body, "MLA874027718", minutes=1)
        changed = copy.deepcopy(body)
        changed["title"] = "same last_updated, new title"
        counters = ApplyCounters()

        outcome = apply(changed, "MLA874027718", minutes=2, counters=counters)

        assert outcome.kind == "changed" and counters.stale_discarded == 0
        (entry,) = log_rows(mlpub_pg, "MLA874027718")
        assert entry["changed_paths"] == ["title"]

    def test_newer_last_updated_is_applied(self, mlpub_pg) -> None:
        """real payload, last_updated moved forward and the title changed."""
        body = sample_item("MLA874027718")
        apply(body, "MLA874027718", minutes=1)
        newer = copy.deepcopy(body)
        newer["last_updated"] = "2026-10-03T00:00:00.000Z"
        newer["title"] = "newer title"

        assert apply(newer, "MLA874027718", minutes=2).kind == "changed"
        assert item_row(mlpub_pg, "MLA874027718")["title"] == "newer title"


class TestExcludedNoise:
    def test_excluded_only_diff_updates_state_without_a_log_row(self, mlpub_pg, monkeypatch) -> None:
        """real payload, title changed; the test-local EXCLUDED_NOISE lists `title`."""
        monkeypatch.setattr(diff_module, "EXCLUDED_NOISE", {("item", "title"): "test-local justification"})
        body = sample_item("MLA874027718")
        apply(body, "MLA874027718", minutes=1)
        changed = copy.deepcopy(body)
        changed["title"] = "noisy title"
        counters = ApplyCounters()

        outcome = apply(changed, "MLA874027718", minutes=2, counters=counters)

        row = item_row(mlpub_pg, "MLA874027718")
        assert outcome.kind == "noise_only" and outcome.change_log_id is None
        assert row["raw"]["title"] == "noisy title" and row["title"] == "noisy title"
        assert bytes(row["raw_hash"]) == canonical_hash(changed, SPEC) and row["fetched_at"] == at(2)
        assert count(mlpub_pg, "ml_change_log") == 0
        assert counters.noise_suppressed[("item", "title")] == 1

    def test_mixed_diff_logs_only_the_non_excluded_paths(self, mlpub_pg, monkeypatch) -> None:
        """real payload, title and available_quantity changed; the test-local list excludes `title`."""
        monkeypatch.setattr(diff_module, "EXCLUDED_NOISE", {("item", "title"): "test-local justification"})
        body = sample_item("MLA874027718")
        apply(body, "MLA874027718", minutes=1)
        changed = copy.deepcopy(body)
        changed["title"] = "noisy title"
        changed["available_quantity"] = 1
        counters = ApplyCounters()

        outcome = apply(changed, "MLA874027718", minutes=2, counters=counters)

        (entry,) = log_rows(mlpub_pg, "MLA874027718")
        assert outcome.kind == "changed"
        assert entry["changed_paths"] == ["available_quantity"]
        assert item_row(mlpub_pg, "MLA874027718")["title"] == "noisy title"
        assert counters.noise_suppressed[("item", "title")] == 1


NOT_FOUND_BODIES = {
    "single-item 404 (GET /items/MLA1)": item_404_single(),
    "bulk-element 404": item_404_bulk_element(),
}


def only_not_found(item_id: str, minutes: float, body=None, **kwargs):
    return apply(body if body is not None else item_404_single(), item_id, minutes=minutes, status=404, **kwargs)


class TestGone:
    @pytest.mark.parametrize("not_found_body", NOT_FOUND_BODIES.values(), ids=NOT_FOUND_BODIES.keys())
    def test_404_on_a_stored_item_marks_gone_and_keeps_the_last_known_data(self, mlpub_pg, not_found_body) -> None:
        body = bulk_item(PAUSED)
        apply(body, PAUSED, minutes=1)
        before = dict(item_row(mlpub_pg, PAUSED))

        outcome = only_not_found(PAUSED, 5, not_found_body)

        row = dict(item_row(mlpub_pg, PAUSED))
        (entry,) = log_rows(mlpub_pg, PAUSED)
        assert outcome.kind == "gone" and outcome.change_log_id == entry["id"]
        assert row["gone_at"] == at(5) and row["http_status"] == 404 and row["never_existed"] is False
        for kept in ("raw", "raw_hash", "status", "brand", "sub_status", "fetched_at", "ml_last_updated"):
            assert row[kept] == before[kept]
        assert entry["kind"] == "gone" and entry["observed_at"] == at(5)
        assert entry["context"]["status_old"] == "paused" and entry["context"]["status_new"] == "paused"

    def test_classification_is_by_status_never_by_body_shape(self, mlpub_pg) -> None:
        """real payload: a complete, healthy item body delivered with HTTP 404 is still gone."""
        body = bulk_item(PAUSED)
        apply(body, PAUSED, minutes=1)

        assert only_not_found(PAUSED, 2, body=copy.deepcopy(body)).kind == "gone"
        assert item_row(mlpub_pg, PAUSED)["gone_at"] == at(2)

    def test_repeated_404_does_not_re_stamp_or_log(self, mlpub_pg) -> None:
        apply(bulk_item(PAUSED), PAUSED, minutes=1)
        only_not_found(PAUSED, 5)

        outcome = only_not_found(PAUSED, 9)

        assert outcome.kind == "unchanged"
        assert item_row(mlpub_pg, PAUSED)["gone_at"] == at(5)
        assert item_row(mlpub_pg, PAUSED)["last_checked_at"] == at(9)
        assert len(log_rows(mlpub_pg, PAUSED)) == 1

    def test_a_404_after_a_transient_error_realigns_http_status_with_gone_at(self, mlpub_pg) -> None:
        apply(bulk_item(PAUSED), PAUSED, minutes=1)
        only_not_found(PAUSED, 2)
        apply({"message": "boom"}, PAUSED, minutes=3, status=500)
        assert item_row(mlpub_pg, PAUSED)["http_status"] == 500

        outcome = only_not_found(PAUSED, 4)

        row = item_row(mlpub_pg, PAUSED)
        assert outcome.kind == "unchanged" and row["gone_at"] == at(2)
        assert row["http_status"] == 404 and row["last_error"] == "HTTP 404"
        assert len(log_rows(mlpub_pg, PAUSED)) == 1

    def test_never_seen_id_returning_404_is_recorded_as_never_existed(self, mlpub_pg) -> None:
        outcome = only_not_found("MLA1", 3)

        row = item_row(mlpub_pg, "MLA1")
        assert outcome.kind == "never_existed" and outcome.change_log_id is None
        assert row["never_existed"] is True and row["http_status"] == 404 and row["raw"] is None
        assert count(mlpub_pg, "ml_change_log") == 0 and count(mlpub_pg, "ml_item_events") == 0

    def test_a_second_404_on_a_never_existing_id_stays_silent(self, mlpub_pg) -> None:
        only_not_found("MLA1", 3)
        first = dict(item_row(mlpub_pg, "MLA1"))

        outcome = only_not_found("MLA1", 8)

        assert outcome.kind == "unchanged" and count(mlpub_pg, "ml_change_log") == 0
        assert item_row(mlpub_pg, "MLA1")["gone_at"] == first["gone_at"]

    def test_a_never_existing_id_that_later_appears_is_a_first_sighting(self, mlpub_pg) -> None:
        only_not_found(PAUSED, 1)

        outcome = apply(bulk_item(PAUSED), PAUSED, minutes=2)

        row = item_row(mlpub_pg, PAUSED)
        assert outcome.kind == "first_seen" and count(mlpub_pg, "ml_change_log") == 0
        assert row["never_existed"] is False and row["gone_at"] is None and row["status"] == "paused"

    def test_gone_then_200_restores_and_logs_the_diff_against_the_last_known_raw(self, mlpub_pg) -> None:
        """real payload, available_quantity 0->3 and last_updated moved forward while the item was gone."""
        body = bulk_item(PAUSED)
        apply(body, PAUSED, minutes=1)
        only_not_found(PAUSED, 2)
        back = copy.deepcopy(body)
        back["available_quantity"] = 3
        back["last_updated"] = "2026-10-06T11:59:00.000Z"

        outcome = apply(back, PAUSED, minutes=7)

        row = item_row(mlpub_pg, PAUSED)
        gone_row, restored_row = log_rows(mlpub_pg, PAUSED)
        assert outcome.kind == "restored" and outcome.change_log_id == restored_row["id"]
        assert row["gone_at"] is None and row["http_status"] == 200
        assert row["raw"] == back and row["available_quantity"] == 3
        assert gone_row["kind"] == "gone" and restored_row["kind"] == "restored"
        assert sorted(restored_row["changed_paths"]) == ["available_quantity", "last_updated"]

    def test_restore_with_unchanged_content_is_still_logged(self, mlpub_pg) -> None:
        body = bulk_item(PAUSED)
        apply(body, PAUSED, minutes=1)
        only_not_found(PAUSED, 2)

        assert apply(copy.deepcopy(body), PAUSED, minutes=3).kind == "restored"

        restored = log_rows(mlpub_pg, PAUSED)[-1]
        assert restored["kind"] == "restored" and restored["changed_paths"] == []
        assert item_row(mlpub_pg, PAUSED)["gone_at"] is None

    def test_closed_but_retrievable_item_is_stored_normally(self, mlpub_pg) -> None:
        outcome = apply(item_with_variations(), "MLA1207279308")

        row = item_row(mlpub_pg, "MLA1207279308")
        assert outcome.kind == "first_seen"
        assert row["status"] == "closed" and row["gone_at"] is None and row["http_status"] == 200

    def test_a_404_older_than_the_committed_fetch_is_discarded(self, mlpub_pg) -> None:
        apply(bulk_item(PAUSED), PAUSED, minutes=10)
        counters = ApplyCounters()

        outcome = only_not_found(PAUSED, 2, counters=counters)

        assert outcome.kind == "stale" and counters.stale_discarded == 1
        assert item_row(mlpub_pg, PAUSED)["gone_at"] is None and count(mlpub_pg, "ml_change_log") == 0


class TestNonSuccessResponses:
    @pytest.mark.parametrize("status", [403, 429, 500, 503])
    def test_error_is_recorded_without_touching_raw_or_the_log(self, mlpub_pg, status) -> None:
        apply(bulk_item(PAUSED), PAUSED, minutes=1)
        before = dict(item_row(mlpub_pg, PAUSED))

        outcome = apply({"message": "denied", "status": status}, PAUSED, minutes=4, status=status)

        row = dict(item_row(mlpub_pg, PAUSED))
        assert outcome.kind == "error_recorded"
        assert row["http_status"] == status and row["error_body"] == {"message": "denied", "status": status}
        assert row["last_error"] == f"HTTP {status}"
        for kept in ("raw", "raw_hash", "status", "fetched_at", "last_checked_at", "gone_at"):
            assert row[kept] == before[kept]
        assert count(mlpub_pg, "ml_change_log") == 0

    def test_error_on_a_never_seen_id_keeps_it_unseen_not_never_existing(self, mlpub_pg) -> None:
        apply(None, PAUSED, minutes=1, status=0)

        row = item_row(mlpub_pg, PAUSED)
        assert row["raw"] is None and row["never_existed"] is False and row["http_status"] is None
        assert row["last_error"] == "no response"

    def test_a_later_identical_200_clears_the_recorded_error(self, mlpub_pg) -> None:
        body = bulk_item(PAUSED)
        apply(body, PAUSED, minutes=1)
        apply({"message": "boom"}, PAUSED, minutes=2, status=500)

        assert apply(copy.deepcopy(body), PAUSED, minutes=3).kind == "unchanged"

        row = item_row(mlpub_pg, PAUSED)
        assert row["http_status"] == 200 and row["error_body"] is None and row["last_error"] is None
        assert row["last_checked_at"] == at(3)

    def test_a_2xx_body_for_another_item_is_an_error_not_a_write(self, mlpub_pg) -> None:
        outcome = apply(bulk_item("MLA934406852"), PAUSED)

        row = item_row(mlpub_pg, PAUSED)
        assert outcome.kind == "error_recorded" and row["raw"] is None and row["last_error"] == "body id mismatch"


class TestNegativeStates:
    """`ResourceSpec.negative_states`: a declared HTTP status that is a state of the resource, not an error."""

    SPEC_WITH_STATE = dataclasses.replace(SPEC, negative_states={404: "test_negative_state"})

    def test_declared_negative_state_is_stored_like_a_2xx_state_and_never_gone(self, mlpub_pg) -> None:
        """test-local negative state for 404; real captured 404 body."""
        apply(bulk_item(PAUSED), PAUSED, minutes=1)

        outcome = apply_fetch(self.SPEC_WITH_STATE, (PAUSED,), ok(item_404_single(), 5, status=404))

        row = item_row(mlpub_pg, PAUSED)
        (entry,) = log_rows(mlpub_pg, PAUSED)
        assert outcome.kind == "changed"
        assert row["gone_at"] is None and row["http_status"] == 404 and row["raw"] == item_404_single()
        assert entry["kind"] == "change"

    def test_undeclared_status_is_unaffected_by_the_hook(self, mlpub_pg) -> None:
        apply(bulk_item(PAUSED), PAUSED, minutes=1)

        outcome = apply_fetch(self.SPEC_WITH_STATE, (PAUSED,), ok({"message": "denied"}, 5, status=403))

        assert outcome.kind == "error_recorded"

    def test_items_declare_no_negative_states(self) -> None:
        assert dict(SPEC.negative_states) == {}


class TestGoneOrdering:
    def test_a_200_whose_request_started_before_the_404_is_discarded(self, mlpub_pg) -> None:
        """the item vanished; a slow, older 200 answer must not resurrect it."""
        body = bulk_item(PAUSED)
        apply(body, PAUSED, minutes=1)
        only_not_found(PAUSED, 10)
        counters = ApplyCounters()

        outcome = apply(copy.deepcopy(body), PAUSED, minutes=6, counters=counters)

        assert outcome.kind == "stale" and counters.stale_discarded == 1
        assert item_row(mlpub_pg, PAUSED)["gone_at"] == at(10)
        assert len(log_rows(mlpub_pg, PAUSED)) == 1  # only the gone row

    def test_a_repeated_404_moves_the_ordering_bound_forward(self, mlpub_pg) -> None:
        body = bulk_item(PAUSED)
        apply(body, PAUSED, minutes=1)
        only_not_found(PAUSED, 10)
        only_not_found(PAUSED, 20)

        assert apply(copy.deepcopy(body), PAUSED, minutes=15).kind == "stale"
        assert item_row(mlpub_pg, PAUSED)["gone_at"] == at(10)


class TestTriggerTimestamp:
    def test_trigger_time_is_kept_as_the_latest_received(self, mlpub_pg) -> None:
        apply(bulk_item(PAUSED), PAUSED, minutes=1, trigger_received_at=at(0.5))
        assert item_row(mlpub_pg, PAUSED)["last_trigger_received_at"] == at(0.5)

        apply(bulk_item(PAUSED), PAUSED, minutes=3, trigger_received_at=at(2))
        assert item_row(mlpub_pg, PAUSED)["last_trigger_received_at"] == at(2)

        apply(bulk_item(PAUSED), PAUSED, minutes=4, trigger_received_at=at(1))  # an older trigger never moves it back
        assert item_row(mlpub_pg, PAUSED)["last_trigger_received_at"] == at(2)

    def test_no_trigger_leaves_the_column_alone(self, mlpub_pg) -> None:
        apply(bulk_item(PAUSED), PAUSED, minutes=1, trigger_received_at=at(0.5))
        apply(bulk_item(PAUSED), PAUSED, minutes=3)
        assert item_row(mlpub_pg, PAUSED)["last_trigger_received_at"] == at(0.5)


def run_concurrently(*calls):
    """Run each callable on its own thread, released together; re-raise the first failure."""
    barrier = threading.Barrier(len(calls))
    errors: list[BaseException] = []

    def runner(call):
        try:
            barrier.wait(timeout=10)
            call()
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=runner, args=(call,)) for call in calls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    if errors:
        raise errors[0]


@pytest.fixture
def slow_diff(monkeypatch):
    """Widen the read-compare-write window so an unserialized pair of writers would interleave."""
    real = store_module.diff

    def slow(*args, **kwargs):
        time.sleep(0.3)
        return real(*args, **kwargs)

    monkeypatch.setattr(store_module, "diff", slow)


class TestConcurrencyAndIdempotency:
    def test_two_concurrent_applies_of_the_same_transition_log_exactly_one_row(self, mlpub_pg, slow_diff) -> None:
        """real payload, status paused->active and available_quantity 0->3 applied by two threads."""
        body = bulk_item(PAUSED)
        apply(body, PAUSED, minutes=1)
        changed = copy.deepcopy(body)
        changed["status"] = "active"
        changed["available_quantity"] = 3
        outcomes = []

        run_concurrently(
            lambda: outcomes.append(apply(copy.deepcopy(changed), PAUSED, minutes=5).kind),
            lambda: outcomes.append(apply(copy.deepcopy(changed), PAUSED, minutes=6).kind),
        )

        assert sorted(outcomes) == ["changed", "unchanged"]
        (entry,) = log_rows(mlpub_pg, PAUSED)
        assert entry["changed_paths"] == ["available_quantity", "status"]

    def test_two_concurrent_first_sightings_write_one_row_and_no_log(self, mlpub_pg) -> None:
        body = bulk_item(PAUSED)
        outcomes = []

        run_concurrently(
            lambda: outcomes.append(apply(copy.deepcopy(body), PAUSED, minutes=1).kind),
            lambda: outcomes.append(apply(copy.deepcopy(body), PAUSED, minutes=2).kind),
        )

        assert sorted(outcomes) == ["first_seen", "unchanged"]
        assert count(mlpub_pg, "ml_items") == 1 and count(mlpub_pg, "ml_change_log") == 0

    def test_replay_after_commit_writes_no_second_row(self, mlpub_pg) -> None:
        body = bulk_item(PAUSED)
        apply(body, PAUSED, minutes=1)
        changed = copy.deepcopy(body)
        changed["available_quantity"] = 3

        assert apply(copy.deepcopy(changed), PAUSED, minutes=2).kind == "changed"
        assert apply(copy.deepcopy(changed), PAUSED, minutes=3).kind == "unchanged"
        assert len(log_rows(mlpub_pg, PAUSED)) == 1

    def test_a_stale_response_applied_late_after_a_newer_one_creates_no_row(self, mlpub_pg) -> None:
        """real payload: the newer body is applied first, then a body with an older last_updated."""
        base = sample_item("MLA874027718")
        apply(base, "MLA874027718", minutes=1)
        newer = copy.deepcopy(base)
        newer["last_updated"] = "2026-10-05T00:00:00.000Z"
        newer["title"] = "newer"
        older = copy.deepcopy(base)
        older["last_updated"] = "2026-10-03T00:00:00.000Z"
        older["title"] = "older"

        assert apply(newer, "MLA874027718", minutes=2).kind == "changed"
        assert apply(older, "MLA874027718", minutes=3).kind == "stale"

        (entry,) = log_rows(mlpub_pg, "MLA874027718")
        assert entry["changed_paths"] == ["last_updated", "title"]
        assert item_row(mlpub_pg, "MLA874027718")["title"] == "newer"

    def test_concurrent_newer_and_older_responses_end_with_the_newer_state(self, mlpub_pg, slow_diff) -> None:
        base = sample_item("MLA874027718")
        apply(base, "MLA874027718", minutes=1)
        newer = copy.deepcopy(base)
        newer["last_updated"] = "2026-10-05T00:00:00.000Z"
        newer["title"] = "newer"
        older = copy.deepcopy(base)
        older["last_updated"] = "2026-10-03T00:00:00.000Z"
        older["title"] = "older"

        run_concurrently(
            lambda: apply(older, "MLA874027718", minutes=2),
            lambda: apply(newer, "MLA874027718", minutes=3),
        )

        assert item_row(mlpub_pg, "MLA874027718")["title"] == "newer"
        assert item_row(mlpub_pg, "MLA874027718")["ml_last_updated"] == datetime(2026, 10, 5, tzinfo=timezone.utc)


MULTI = "MLA1207279308"
VARIATION_IDS = [175550253195, 175550253196, 175550253197, 175550253198]


def variation_rows(engine, item_id: str = MULTI):
    with engine.connect() as conn:
        return (
            conn.execute(
                text("SELECT * FROM ml_item_variations WHERE item_id = :i ORDER BY variation_id"), {"i": item_id}
            )
            .mappings()
            .all()
        )


class TestVariations:
    def test_captured_item_writes_one_row_per_variation(self, mlpub_pg) -> None:
        body = item_with_variations()
        apply(body, MULTI, minutes=1)

        rows = variation_rows(mlpub_pg)
        assert [r["variation_id"] for r in rows] == VARIATION_IDS
        for row, variation in zip(rows, body["variations"]):
            assert row["raw"] == variation
            assert row["user_product_id"] == variation["user_product_id"]
            assert row["seller_custom_field"] is None and row["seller_sku"] is None
            assert row["available_quantity"] == variation["available_quantity"]
            assert row["gone_at"] is None and row["fetched_at"] == at(1) and row["raw_hash"] is not None
        assert count(mlpub_pg, "ml_change_log") == 0

    def test_item_without_variations_writes_no_rows(self, mlpub_pg) -> None:
        apply(bulk_item(PAUSED), PAUSED)  # MLA935110613: `variations: []`
        assert variation_rows(mlpub_pg, PAUSED) == []

    def test_a_vanished_variation_is_kept_marked_gone_and_logged_under_the_item(self, mlpub_pg) -> None:
        """real payload, one of the 4 variations removed."""
        body = item_with_variations()
        apply(body, MULTI, minutes=1)
        smaller = copy.deepcopy(body)
        removed = smaller["variations"].pop(1)

        outcome = apply(smaller, MULTI, minutes=5)

        rows = {r["variation_id"]: r for r in variation_rows(mlpub_pg)}
        assert len(rows) == 4
        assert rows[removed["id"]]["gone_at"] == at(5) and rows[removed["id"]]["raw"] == removed
        assert all(r["gone_at"] is None for vid, r in rows.items() if vid != removed["id"])
        logs = log_rows(mlpub_pg, MULTI)
        assert outcome.kind == "changed" and len(logs) == 1  # no separate variation log row
        assert logs[0]["changed_paths"] == [f"variations[{removed['id']}]"]
        assert logs[0]["changes"][0]["op"] == "remove"

    def test_a_returning_variation_clears_gone_at(self, mlpub_pg) -> None:
        body = item_with_variations()
        apply(body, MULTI, minutes=1)
        smaller = copy.deepcopy(body)
        removed = smaller["variations"].pop(1)
        apply(smaller, MULTI, minutes=2)

        apply(body, MULTI, minutes=3)

        rows = {r["variation_id"]: r for r in variation_rows(mlpub_pg)}
        assert rows[removed["id"]]["gone_at"] is None and rows[removed["id"]]["fetched_at"] == at(3)

    def test_changing_one_variation_logs_only_its_sub_path_and_rewrites_only_that_row(self, mlpub_pg) -> None:
        """real payload, one variation's seller_custom_field set to "ABC-1"."""
        body = item_with_variations()
        apply(body, MULTI, minutes=1)
        changed = copy.deepcopy(body)
        target = changed["variations"][2]
        target["seller_custom_field"] = "ABC-1"

        apply(changed, MULTI, minutes=5)

        (entry,) = log_rows(mlpub_pg, MULTI)
        assert entry["changed_paths"] == [f"variations[{target['id']}].seller_custom_field"]
        rows = {r["variation_id"]: r for r in variation_rows(mlpub_pg)}
        assert rows[target["id"]]["seller_custom_field"] == "ABC-1" and rows[target["id"]]["fetched_at"] == at(5)
        others = [r for vid, r in rows.items() if vid != target["id"]]
        assert len(others) == 3 and all(r["fetched_at"] == at(1) for r in others)

    def test_identical_fetch_leaves_every_variation_row_alone(self, mlpub_pg) -> None:
        body = item_with_variations()
        apply(body, MULTI, minutes=1)
        before = [dict(r) for r in variation_rows(mlpub_pg)]

        apply(copy.deepcopy(body), MULTI, minutes=9)

        assert [dict(r) for r in variation_rows(mlpub_pg)] == before

    def test_restoring_a_gone_item_projects_its_variations_again(self, mlpub_pg) -> None:
        body = item_with_variations()
        apply(body, MULTI, minutes=1)
        only_not_found(MULTI, 2)

        assert apply(copy.deepcopy(body), MULTI, minutes=3).kind == "restored"
        assert len(variation_rows(mlpub_pg)) == 4


ACTIVE = "MLA874027718"  # active, sub_status [], available_quantity 2, official store 57997, brand from attributes


class TestChangeLogContext:
    def test_context_holds_the_derivation_inputs_for_a_change(self, mlpub_pg) -> None:
        """real payload, status paused->active, sub_status cleared and available_quantity 0->3."""
        body = bulk_item(PAUSED)
        apply(body, PAUSED, minutes=1)
        changed = copy.deepcopy(body)
        changed["status"] = "active"
        changed["sub_status"] = []
        changed["available_quantity"] = 3

        apply(changed, PAUSED, minutes=5)

        (entry,) = log_rows(mlpub_pg, PAUSED)
        assert entry["context"] == {
            "status_old": "paused",
            "status_new": "active",
            "sub_status_old": ["out_of_stock"],
            "sub_status_new": [],
            "available_quantity_old": 0,
            "available_quantity_new": 3,
            "first_active_at_before": None,
            "official_store_id": 57997,
            "brand": "Marvo",
        }

    def test_first_active_at_is_set_on_the_first_observed_active_status(self, mlpub_pg) -> None:
        body = bulk_item(PAUSED)
        apply(body, PAUSED, minutes=1)
        assert item_row(mlpub_pg, PAUSED)["first_active_at"] is None

        changed = copy.deepcopy(body)
        changed["status"] = "active"
        apply(changed, PAUSED, minutes=5)

        assert item_row(mlpub_pg, PAUSED)["first_active_at"] == at(5)

    def test_first_active_at_is_set_on_a_first_sighting_that_is_already_active(self, mlpub_pg) -> None:
        apply(sample_item(ACTIVE), ACTIVE, minutes=2)
        assert item_row(mlpub_pg, ACTIVE)["first_active_at"] == at(2)

    def test_first_active_at_is_never_moved_by_later_reactivations(self, mlpub_pg) -> None:
        """real payload, active -> paused -> active again."""
        body = sample_item(ACTIVE)
        apply(body, ACTIVE, minutes=2)
        paused = copy.deepcopy(body)
        paused["status"] = "paused"
        apply(paused, ACTIVE, minutes=3)
        apply(copy.deepcopy(body), ACTIVE, minutes=4)

        assert item_row(mlpub_pg, ACTIVE)["first_active_at"] == at(2)
        reactivation = log_rows(mlpub_pg, ACTIVE)[-1]
        assert reactivation["context"]["first_active_at_before"] == at(2).isoformat()
        assert reactivation["context"]["status_old"] == "paused" and reactivation["context"]["status_new"] == "active"

    def test_context_of_a_gone_row_carries_the_unchanged_state(self, mlpub_pg) -> None:
        apply(sample_item(ACTIVE), ACTIVE, minutes=2)
        only_not_found(ACTIVE, 6)

        (entry,) = log_rows(mlpub_pg, ACTIVE)
        assert entry["context"]["status_old"] == "active" and entry["context"]["status_new"] == "active"
        assert entry["context"]["first_active_at_before"] == at(2).isoformat()
        assert entry["context"]["official_store_id"] == 57997
