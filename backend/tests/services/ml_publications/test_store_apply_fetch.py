"""`store.apply_fetch`: the transactional upsert of one fetched item (design D8).

Postgres only (row locks, jsonb, arrays). Every payload is a real capture; a
transition is a deep copy of a real body with the named fields changed.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services.ml_publications import diff as diff_module
from app.services.ml_publications.canonical import canonical_hash
from app.services.ml_publications.ml_http import MlResponse
from app.services.ml_publications.resources import RESOURCES
from app.services.ml_publications.store import ApplyCounters, apply_fetch
from tests.services.ml_publications.conftest import bulk_item, sample_item

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
