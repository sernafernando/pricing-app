"""`store.apply_fetch`: the transactional upsert of one fetched item (design D8).

Postgres only (row locks, jsonb, arrays). Every payload is a real capture; a
transition is a deep copy of a real body with the named fields changed.
"""

from __future__ import annotations

import copy
import dataclasses
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services.ml_publications import diff as diff_module
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
