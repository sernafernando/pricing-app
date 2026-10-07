"""Pure price event rules (design D16): `price_changed` kinds standard, promotion and sale.

Rows are built the way the store builds them: the real diff between a captured body and a deep
copy of it with one named change (labelled in each test), plus the `entries` context. The rules
see only the stored row, so deriving from a JSON round trip of it must give the same events.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

from app.services.ml_publications.diff import diff, split_excluded
from app.services.ml_publications.events import ChangeRow, dedupe_key, derive_events
from app.services.ml_publications.resources import RESOURCES
from app.services.ml_publications.subresource_context import entries_context
from tests.services.ml_publications.conftest import subresource_body

T_OBSERVED = datetime(2026, 10, 6, 13, 30, tzinfo=timezone.utc)
STANDARD_ONLY = "prices_MLA903301838"  # standard 18511.0, no promotion
WITH_PROMOTION = "prices_started_MLA2146576013"  # standard 2381471.0 (id 6) + promotion 1509999.0 (id 7)
TWO_CHANNELS = "prices_MLA874027718"  # marketplace standard 55882.0 (465) + mshops standard 39990.0 (414)
SALE_STARTED = "sale_price_started_MLA2146576013"  # amount 1509999.0, regular 2381471.0, campaign + promotion


def prices_row(old: dict, new: dict, *, kind: str = "change", row_id: int = 11) -> ChangeRow:
    return stored_row("prices", old, new, kind=kind, row_id=row_id)


def stored_row(resource: str, old: dict, new: dict, *, kind: str = "change", row_id: int = 11) -> ChangeRow:
    spec = RESOURCES[resource]
    reportable, _ = split_excluded(diff(old, new, spec), resource)
    context = {**entries_context(resource, old, new), "official_store_id": 57997, "brand": "Marvo"}
    return ChangeRow(
        id=row_id,
        resource_type=resource,
        item_id=new["id"] if "id" in new else "MLA2146576013",
        kind=kind,
        observed_at=T_OBSERVED,
        source_last_updated=None,
        changes=[c.as_dict() for c in reportable],
        context=context,
    )


def with_amount(body: dict, entry_id: str, amount: float) -> dict:
    out = copy.deepcopy(body)
    for entry in out["prices"]:
        if entry["id"] == entry_id:
            entry["amount"] = amount
    return out


def without_entry(body: dict, entry_id: str) -> dict:
    out = copy.deepcopy(body)
    out["prices"] = [e for e in out["prices"] if e["id"] != entry_id]
    return out


def only(events, kind):
    return [e for e in events if e.price_kind == kind]


class TestStandardPrice:
    def test_a_standard_amount_change_is_one_standard_event(self) -> None:
        """Real prices capture with the standard amount changed (18511.0 -> 26000.0)."""
        old = subresource_body("prices", STANDARD_ONLY)
        events = derive_events(prices_row(old, with_amount(old, "339", 26000.0)))

        assert len(events) == 1
        event = events[0]
        assert (event.event_type, event.price_kind) == ("price_changed", "standard")
        assert (event.old_value, event.new_value) == ("18511.0", "26000.0")
        assert event.payload == {"currency_id": "ARS", "price_id": "339"}
        assert event.item_id == "MLA903301838"

    def test_the_other_channel_standard_price_is_not_a_standard_event(self) -> None:
        """Real two-channel capture with ONLY the mshops standard price (414) changed."""
        old = subresource_body("prices", TWO_CHANNELS)
        row = prices_row(old, with_amount(old, "414", 41000.0))
        assert row.changes  # the diff sees it (it is logged in the change log)
        assert derive_events(row) == []

    def test_the_marketplace_standard_change_is_an_event_on_the_two_channel_item(self) -> None:
        old = subresource_body("prices", TWO_CHANNELS)
        events = derive_events(prices_row(old, with_amount(old, "465", 60000.0)))
        assert [(e.price_kind, e.old_value, e.new_value) for e in events] == [("standard", "55882.0", "60000.0")]

    def test_an_unchanged_amount_is_no_event_even_if_other_fields_changed(self) -> None:
        """Real capture with only the standard entry's `last_updated` changed."""
        old = subresource_body("prices", STANDARD_ONLY)
        new = copy.deepcopy(old)
        new["prices"][0]["last_updated"] = "2026-10-06T13:00:00Z"
        row = prices_row(old, new)
        assert row.changes and derive_events(row) == []


class TestPromotionPrice:
    def test_a_promotion_entry_appearing_is_a_promotion_event_with_a_null_old_value(self) -> None:
        """Real promotion capture; the OLD state is the same body with the promotion entry (7) removed."""
        new = subresource_body("prices", WITH_PROMOTION)
        events = derive_events(prices_row(without_entry(new, "7"), new))

        assert [(e.price_kind, e.old_value, e.new_value) for e in events] == [("promotion", None, "1509999.0")]
        assert events[0].payload["price_id"] == "7"

    def test_a_promotion_entry_disappearing_is_a_promotion_event_with_a_null_new_value(self) -> None:
        old = subresource_body("prices", WITH_PROMOTION)
        events = derive_events(prices_row(old, without_entry(old, "7")))
        assert [(e.price_kind, e.old_value, e.new_value) for e in events] == [("promotion", "1509999.0", None)]

    def test_a_promotion_amount_change_is_a_promotion_event(self) -> None:
        old = subresource_body("prices", WITH_PROMOTION)
        events = derive_events(prices_row(old, with_amount(old, "7", 1400000.0)))
        assert [(e.price_kind, e.old_value, e.new_value) for e in events] == [("promotion", "1509999.0", "1400000.0")]

    def test_a_promotion_entry_with_a_new_price_id_but_the_same_amount_is_no_event(self) -> None:
        """Real promotion capture with only the promotion entry's id changed (7 -> 8)."""
        old = subresource_body("prices", WITH_PROMOTION)
        new = copy.deepcopy(old)
        new["prices"][1]["id"] = "8"
        row = prices_row(old, new)
        assert row.changes and derive_events(row) == []

    def test_the_prices_capture_carries_no_promotion_metadata_so_the_event_has_none(self) -> None:
        """Captured `/prices` promotion entries have no `metadata`: the ids come from sale_price instead."""
        new = subresource_body("prices", WITH_PROMOTION)
        (event,) = derive_events(prices_row(without_entry(new, "7"), new))
        assert (event.promotion_id, event.promotion_type) == (None, None)

    def test_both_kinds_changing_together_give_one_event_each_with_their_own_values(self) -> None:
        old = subresource_body("prices", WITH_PROMOTION)
        new = with_amount(with_amount(old, "6", 2500000.0), "7", 1600000.0)
        events = derive_events(prices_row(old, new))
        assert {e.price_kind: (e.old_value, e.new_value) for e in events} == {
            "standard": ("2381471.0", "2500000.0"),
            "promotion": ("1509999.0", "1600000.0"),
        }


class TestSalePrice:
    def test_an_amount_change_is_a_sale_event_with_the_promotion_metadata(self) -> None:
        """Real sale_price capture with only `amount` changed (1509999.0 -> 1400000.0)."""
        old = subresource_body("sale_price", SALE_STARTED)
        new = copy.deepcopy(old)
        new["amount"] = 1400000.0
        events = derive_events(stored_row("sale_price", old, new))

        assert len(events) == 1
        event = events[0]
        assert (event.event_type, event.price_kind) == ("price_changed", "sale")
        assert (event.old_value, event.new_value) == ("1509999.0", "1400000.0")
        assert event.promotion_id == old["metadata"]["promotion_id"]
        assert event.promotion_type == old["metadata"]["promotion_type"]
        assert event.payload["regular_amount"] == "2381471.0"

    def test_the_promotion_ending_moves_the_sale_amount_back_to_the_regular_price(self) -> None:
        """Real promotion capture vs the real no-promotion shape: amount and metadata both change."""
        old = subresource_body("sale_price", SALE_STARTED)
        new = copy.deepcopy(old)
        new.update(amount=old["regular_amount"], regular_amount=None, metadata={})
        (event,) = derive_events(stored_row("sale_price", old, new))
        assert (event.old_value, event.new_value) == ("1509999.0", "2381471.0")
        assert event.promotion_id == old["metadata"]["promotion_id"]  # the promotion that was ended

    def test_a_change_that_leaves_the_amount_alone_is_no_event(self) -> None:
        """Real capture with only the promotion id changed."""
        old = subresource_body("sale_price", SALE_STARTED)
        new = copy.deepcopy(old)
        new["metadata"]["promotion_id"] = "OFFER-OTHER"
        row = stored_row("sale_price", old, new)
        assert row.changes and derive_events(row) == []


class TestWhatIsNotAPriceEvent:
    def test_the_price_field_vanishing_from_the_item_core_yields_no_event(self) -> None:
        row = ChangeRow(
            id=3,
            resource_type="item",
            item_id="MLA1",
            kind="change",
            observed_at=T_OBSERVED,
            source_last_updated=None,
            changes=[{"p": "price", "op": "remove", "old": 100.0}, {"p": "base_price", "op": "remove", "old": 100.0}],
            context={"status_old": "active", "status_new": "active"},
        )
        assert derive_events(row) == []

    def test_a_not_found_row_yields_no_price_event(self) -> None:
        old = subresource_body("prices", WITH_PROMOTION)
        row = prices_row(old, old, kind="gone")
        assert derive_events(row) == []

    def test_a_row_without_entries_context_yields_no_event_and_does_not_raise(self) -> None:
        old = subresource_body("prices", STANDARD_ONLY)
        row = prices_row(old, with_amount(old, "339", 26000.0))
        bare = ChangeRow(**{**row.__dict__, "context": {"official_store_id": 1}})
        assert derive_events(bare) == []

    def test_description_rows_have_no_rules_yet(self) -> None:
        old = subresource_body("description", "description_MLA874027718")
        new = copy.deepcopy(old)
        new["plain_text"] = "changed"
        row = ChangeRow(
            id=4,
            resource_type="description",
            item_id="MLA874027718",
            kind="change",
            observed_at=T_OBSERVED,
            source_last_updated=None,
            changes=[{"p": "plain_text", "op": "replace"}],
            context={},
        )
        assert derive_events(row) == []


class TestIdempotencyAndReDerivation:
    def test_deriving_from_a_json_round_trip_of_the_row_gives_the_same_events(self) -> None:
        old = subresource_body("prices", WITH_PROMOTION)
        row = prices_row(old, with_amount(with_amount(old, "6", 2500000.0), "7", 1600000.0))
        stored = ChangeRow(
            **{
                **row.__dict__,
                "changes": json.loads(json.dumps(row.changes)),
                "context": json.loads(json.dumps(row.context)),
            }
        )
        assert derive_events(stored) == derive_events(row)

    def test_flip_a_to_b_to_a_gives_two_events_with_distinct_identities(self) -> None:
        a = subresource_body("prices", STANDARD_ONLY)
        b = with_amount(a, "339", 26000.0)
        first = derive_events(prices_row(a, b, row_id=21))
        second = derive_events(prices_row(b, a, row_id=22))

        assert [(e.old_value, e.new_value) for e in first] == [("18511.0", "26000.0")]
        assert [(e.old_value, e.new_value) for e in second] == [("26000.0", "18511.0")]
        keys = {
            dedupe_key(row_id, e.event_type, e.promotion_key, e.price_kind)
            for row_id, events in ((21, first), (22, second))
            for e in events
        }
        assert len(keys) == 2

    def test_the_two_kinds_of_one_row_have_distinct_identities(self) -> None:
        old = subresource_body("prices", WITH_PROMOTION)
        events = derive_events(prices_row(old, with_amount(with_amount(old, "6", 2500000.0), "7", 1600000.0)))
        assert len({dedupe_key(11, e.event_type, e.promotion_key, e.price_kind) for e in events}) == 2
