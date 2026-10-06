"""Pure item-core event rules (design D16): `derive_events` over a stored change-log row.

Every row is built the way the store builds it: the real diff between a captured item and
a deep copy of it with the named fields changed, plus the context the store records. The
rules see only the row (changes + context), so deriving from a JSON round trip of the
stored row must equal deriving from the live row (re-derivation).
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

import pytest

from app.services.ml_publications import events as events_module
from app.services.ml_publications.diff import diff, split_excluded
from app.services.ml_publications.events import ChangeRow, Event, dedupe_key, derive_events
from app.services.ml_publications.resources import RESOURCES
from app.services.ml_publications.store import _context
from tests.services.ml_publications.conftest import bulk_item, item_with_variations, sample_item

SPEC = RESOURCES["item"]
ACTIVE = "MLA874027718"  # active, sub_status [], available_quantity 2, sold 188, gold_special, store 57997
PAUSED = "MLA935110613"  # paused, sub_status ["out_of_stock"], available_quantity 0
T_OBSERVED = datetime(2026, 10, 6, 12, 5, tzinfo=timezone.utc)
FIRST_ACTIVE = datetime(2026, 10, 6, 11, 0, tzinfo=timezone.utc)


def row_for(
    old_body: dict,
    new_body: dict,
    *,
    kind: str = "change",
    first_active_before: datetime | None = None,
    change_log_id: int = 7,
) -> ChangeRow:
    """The change-log row the store would write for old -> new (reportable changes only)."""
    reportable, _ = split_excluded(diff(old_body, new_body, SPEC), SPEC.name)
    old_typed, new_typed = SPEC.mapper(old_body), SPEC.mapper(new_body)
    return ChangeRow(
        id=change_log_id,
        resource_type=SPEC.name,
        item_id=new_body["id"],
        kind=kind,
        observed_at=T_OBSERVED,
        source_last_updated=new_typed["ml_last_updated"],
        changes=[c.as_dict() for c in reportable],
        context=_context(old_typed, new_typed, first_active_before),
    )


def mutated(body: dict, **fields) -> dict:
    """Deep copy of a real capture with exactly the named top-level fields replaced."""
    out = copy.deepcopy(body)
    out.update(fields)
    return out


def by_type(events: list[Event]) -> dict[str, Event]:
    assert len({e.event_type for e in events}) == len(events), "a rule emitted twice for one row"
    return {e.event_type: e for e in events}


class TestStatusEvents:
    def test_paused_carries_the_sub_status_pair(self) -> None:
        """real active item with status -> paused and sub_status -> ["out_of_stock"]."""
        old = sample_item(ACTIVE)
        new = mutated(old, status="paused", sub_status=["out_of_stock"])

        (event,) = derive_events(row_for(old, new))

        assert event.event_type == "status_paused" and event.item_id == ACTIVE
        assert (event.old_value, event.new_value) == ("active", "paused")
        assert event.payload == {"old_sub_status": [], "new_sub_status": ["out_of_stock"]}

    def test_a_status_change_does_not_also_emit_sub_status_changed(self) -> None:
        old = sample_item(ACTIVE)
        new = mutated(old, status="paused", sub_status=["out_of_stock"])
        assert "sub_status_changed" not in by_type(derive_events(row_for(old, new)))

    def test_reactivation_is_flagged_when_the_item_was_known_active(self) -> None:
        """real paused item -> active, with first_active_at known from before."""
        old = bulk_item(PAUSED)
        new = mutated(old, status="active", sub_status=[])

        (event,) = derive_events(row_for(old, new, first_active_before=FIRST_ACTIVE))

        assert event.event_type == "status_activated"
        assert (event.old_value, event.new_value) == ("paused", "active")
        assert event.payload == {"is_reactivation": True}

    def test_first_activation_is_not_a_reactivation(self) -> None:
        """real item under_review -> active, never observed active before."""
        base = sample_item(ACTIVE)
        old = mutated(base, status="under_review", sub_status=[])
        (event,) = derive_events(row_for(old, base, first_active_before=None))

        assert event.event_type == "status_activated"
        assert event.old_value == "under_review"
        assert event.payload == {"is_reactivation": False}

    def test_closed(self) -> None:
        """real active item -> closed with a sub_status."""
        old = sample_item(ACTIVE)
        new = mutated(old, status="closed", sub_status=["expired"])
        (event,) = derive_events(row_for(old, new))
        assert event.event_type == "status_closed"
        assert (event.old_value, event.new_value) == ("active", "closed")
        assert event.payload == {"old_sub_status": [], "new_sub_status": ["expired"]}

    def test_under_review(self) -> None:
        old = sample_item(ACTIVE)
        new = mutated(old, status="under_review", sub_status=["waiting_for_patch"])
        (event,) = derive_events(row_for(old, new))
        assert event.event_type == "status_under_review"
        assert (event.old_value, event.new_value) == ("active", "under_review")

    @pytest.mark.parametrize("other", ["inactive", "payment_required", "pending", "a_status_ml_invents_tomorrow"])
    def test_any_other_status_is_status_changed_other(self, other: str) -> None:
        old = sample_item(ACTIVE)
        new = mutated(old, status=other)
        (event,) = derive_events(row_for(old, new))
        assert event.event_type == "status_changed_other"
        assert (event.old_value, event.new_value) == ("active", other)


class TestSubStatus:
    def test_only_when_the_status_is_unchanged_and_no_status_event(self) -> None:
        """real paused item, sub_status ["out_of_stock"] -> ["deactivated"]."""
        old = bulk_item(PAUSED)
        new = mutated(old, sub_status=["deactivated"])

        row = row_for(old, new)
        (event,) = derive_events(row)

        assert any(c["p"].startswith("sub_status[=") for c in row.changes), "diff reports scalar-set members"
        assert event.event_type == "sub_status_changed"
        assert (event.old_value, event.new_value) == (["out_of_stock"], ["deactivated"])
        assert event.payload == {"status": "paused"}


class TestFieldChanges:
    def test_listing_type_and_title_in_one_row_make_two_events(self) -> None:
        """real active item with listing_type_id gold_special -> gold_pro and a new title."""
        old = sample_item(ACTIVE)
        new = mutated(old, listing_type_id="gold_pro", title=old["title"] + " v2")

        events = by_type(derive_events(row_for(old, new)))

        assert set(events) == {"listing_type_changed", "title_changed"}
        assert (events["listing_type_changed"].old_value, events["listing_type_changed"].new_value) == (
            "gold_special",
            "gold_pro",
        )
        assert (events["title_changed"].old_value, events["title_changed"].new_value) == (
            old["title"],
            old["title"] + " v2",
        )

    def test_status_and_a_field_change_in_one_fetch_yield_two_events_for_one_row(self) -> None:
        old = sample_item(ACTIVE)
        new = mutated(old, status="paused", title=old["title"] + "!")
        row = row_for(old, new)
        events = derive_events(row)
        assert {e.event_type for e in events} == {"status_paused", "title_changed"}
        assert {dedupe_key(row.id, e.event_type, None, None) for e in events}.__len__() == 2


class TestStock:
    def test_depleted_only_on_the_zero_crossing(self) -> None:
        """real active item with available_quantity 2 -> 0."""
        old = sample_item(ACTIVE)
        new = mutated(old, available_quantity=0)
        (event,) = derive_events(row_for(old, new))
        assert event.event_type == "stock_depleted"
        assert (event.old_value, event.new_value) == (2, 0)

    def test_replenished_only_on_the_zero_crossing(self) -> None:
        old = bulk_item(PAUSED)  # available_quantity 0
        new = mutated(old, available_quantity=5)
        (event,) = derive_events(row_for(old, new))
        assert event.event_type == "stock_replenished"
        assert (event.old_value, event.new_value) == (0, 5)

    def test_a_delta_that_does_not_cross_zero_is_no_event(self) -> None:
        """real item, available_quantity 2 -> 1 and a sale (sold_quantity +1)."""
        old = sample_item(ACTIVE)
        new = mutated(old, available_quantity=1, sold_quantity=old["sold_quantity"] + 1)
        assert derive_events(row_for(old, new)) == []

    def test_depletion_payload_reports_the_sold_quantity_when_it_changed_in_the_same_row(self) -> None:
        old = sample_item(ACTIVE)
        new = mutated(old, available_quantity=0, sold_quantity=old["sold_quantity"] + 2)
        (event,) = derive_events(row_for(old, new))
        assert event.payload == {"sold_quantity": old["sold_quantity"] + 2}


class TestGoneAndRestored:
    def test_gone_row_yields_item_gone_with_the_last_known_status(self) -> None:
        body = sample_item(ACTIVE)
        row = row_for(body, body, kind="gone", first_active_before=FIRST_ACTIVE)
        (event,) = derive_events(row)
        assert event.event_type == "item_gone"
        assert (event.old_value, event.new_value) == (None, None)
        assert event.payload == {"last_status": "active"}

    def test_restored_row_yields_item_restored(self) -> None:
        body = sample_item(ACTIVE)
        row = row_for(body, body, kind="restored", first_active_before=FIRST_ACTIVE)
        (event,) = derive_events(row)
        assert event.event_type == "item_restored"
        assert event.payload == {"status": "active"}

    def test_restored_with_a_changed_status_also_yields_the_status_event(self) -> None:
        old = sample_item(ACTIVE)
        new = mutated(old, status="paused")
        types = {e.event_type for e in derive_events(row_for(old, new, kind="restored"))}
        assert types == {"item_restored", "status_paused"}


class TestNoEvents:
    def test_price_fields_disappearing_from_items_are_not_price_changes(self) -> None:
        """real active item with `price` and `base_price` removed (ML is retiring them)."""
        old = sample_item(ACTIVE)
        new = copy.deepcopy(old)
        del new["price"], new["base_price"]
        row = row_for(old, new)
        assert {c["p"] for c in row.changes} >= {"price", "base_price"}
        assert derive_events(row) == []

    def test_a_change_mapping_to_no_event_yields_none(self) -> None:
        """real closed item with only `warranty` changed."""
        old = item_with_variations()
        new = mutated(old, warranty="Garantia de fabrica: 12 meses")
        assert derive_events(row_for(old, new)) == []

    def test_an_empty_change_row_yields_none(self) -> None:
        body = sample_item(ACTIVE)
        assert derive_events(row_for(body, body)) == []

    def test_other_resources_have_no_rules_in_this_catalog(self) -> None:
        body = sample_item(ACTIVE)
        row = row_for(body, mutated(body, status="paused"))
        assert derive_events(ChangeRow(**{**row.__dict__, "resource_type": "prices"})) == []


class TestReDerivation:
    def test_a_stored_row_alone_derives_the_live_result(self) -> None:
        """the row after a JSON round trip (what Postgres returns) derives identically."""
        old = sample_item(ACTIVE)
        new = mutated(old, status="paused", sub_status=["out_of_stock"], available_quantity=0, title=old["title"] + "?")
        live = row_for(old, new, first_active_before=FIRST_ACTIVE)
        stored = ChangeRow(
            **{
                **live.__dict__,
                "changes": json.loads(json.dumps(live.changes)),
                "context": json.loads(json.dumps(live.context)),
            }
        )
        assert derive_events(stored) == derive_events(live)
        assert len(derive_events(live)) == 3


class TestDedupeKey:
    def test_deterministic_32_byte_digest(self) -> None:
        key = dedupe_key(7, "status_paused", None, None)
        assert isinstance(key, bytes) and len(key) == 32
        assert key == dedupe_key(7, "status_paused", None, None)

    @pytest.mark.parametrize(
        "other",
        [
            (8, "status_paused", None, None),
            (7, "status_closed", None, None),
            (7, "status_paused", "P1", None),
            (7, "status_paused", None, "sale"),
        ],
    )
    def test_every_component_is_part_of_the_identity(self, other) -> None:
        assert dedupe_key(7, "status_paused", None, None) != dedupe_key(*other)

    def test_a_flip_back_is_a_distinct_event_because_its_change_log_row_is_distinct(self) -> None:
        assert dedupe_key(7, "status_paused", None, None) != dedupe_key(9, "status_paused", None, None)

    def test_the_separator_cannot_be_forged_by_a_promotion_key(self) -> None:
        assert dedupe_key(7, "a", "b|c", None) != dedupe_key(7, "a", "b", "c")


def test_the_module_stays_pure() -> None:
    """no I/O: the rules must not import the database layer."""
    source = events_module.__file__
    text = open(source, encoding="utf-8").read()
    assert "sqlalchemy" not in text and "database" not in text
