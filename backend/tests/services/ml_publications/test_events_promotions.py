"""Pure promotion event rules (design D16): `promotion_offered`, `promotion_activated`,
`promotion_finished` (reason ended / withdrawn / absent) and `promotion_price_changed`.

Rows are built the way the store builds them: the real diff between a captured promotions list and
a deep copy of it with the one change named in each test's docstring, plus the `entries` context.
The rules see only the stored row, so deriving from a JSON round trip of it must give the same events.
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
ITEM = "MLA2146576013"
STARTED = "promotions_started_MLA2146576013"  # C-MLA1669550 started 1509999, PRICE_DISCOUNT + 5 campaigns candidate
ONLY_CANDIDATES = "promotions_MLA874027718"  # PRICE_DISCOUNT, DEAL P-MLA18067012 and 6 campaigns, all candidate
STARTED_ID = "C-MLA1669550"
CANDIDATE_ID = "C-MLA1664342"


def promotions_row(old: list, new: list, *, kind: str = "change", row_id: int = 21) -> ChangeRow:
    spec = RESOURCES["promotions"]
    reportable, _ = split_excluded(diff(old, new, spec), "promotions")
    return ChangeRow(
        id=row_id,
        resource_type="promotions",
        item_id=ITEM,
        kind=kind,
        observed_at=T_OBSERVED,
        source_last_updated=None,
        changes=[c.as_dict() for c in reportable],
        context={**entries_context("promotions", old, new), "official_store_id": 57997, "brand": "Marvo"},
    )


def entry(body: list, key: str) -> dict:
    return next(e for e in body if (e.get("id") or e["type"]) == key)


def without(body: list, key: str) -> list:
    return [copy.deepcopy(e) for e in body if (e.get("id") or e["type"]) != key]


def with_fields(body: list, key: str, **fields) -> list:
    out = copy.deepcopy(body)
    entry(out, key).update(fields)
    return out


def of_type(events, event_type: str):
    return [e for e in events if e.event_type == event_type]


class TestOffered:
    def test_a_campaign_candidate_that_appears_is_one_offered_event_with_its_bounds(self) -> None:
        """Real started list vs the same list with the candidate C-MLA1664342 removed from the old side."""
        new = subresource_body("promotions", STARTED)
        old = without(new, CANDIDATE_ID)

        events = derive_events(promotions_row(old, new))

        assert [e.event_type for e in events] == ["promotion_offered"]
        event = events[0]
        assert (event.promotion_id, event.promotion_type) == (CANDIDATE_ID, "SELLER_CAMPAIGN")
        assert (event.old_value, event.new_value) == (None, "candidate")
        assert event.item_id == ITEM
        assert event.payload == {
            "suggested_discounted_price": "2190953.2",
            "min_discounted_price": "714441.25",
            "max_discounted_price": "2262397.5",
        }

    def test_price_discount_without_an_id_is_keyed_by_its_type(self) -> None:
        """Real list vs the same list without PRICE_DISCOUNT on the old side."""
        new = subresource_body("promotions", ONLY_CANDIDATES)
        old = without(new, "PRICE_DISCOUNT")

        (event,) = derive_events(promotions_row(old, new))

        assert event.event_type == "promotion_offered"
        assert (event.promotion_id, event.promotion_type) == (None, "PRICE_DISCOUNT")
        assert event.promotion_key == ":PRICE_DISCOUNT"

    def test_two_new_candidates_are_two_events_with_distinct_identities(self) -> None:
        """Real candidates-only list vs the same list without the DEAL and one campaign on the old side."""
        new = subresource_body("promotions", ONLY_CANDIDATES)
        old = without(without(new, "P-MLA18067012"), CANDIDATE_ID)

        events = derive_events(promotions_row(old, new))

        assert sorted((e.promotion_id, e.promotion_type) for e in events) == [
            (CANDIDATE_ID, "SELLER_CAMPAIGN"),
            ("P-MLA18067012", "DEAL"),
        ]
        keys = {dedupe_key(21, e.event_type, e.promotion_key, e.price_kind) for e in events}
        assert len(keys) == 2

    def test_a_candidate_whose_bounds_move_is_not_offered_again(self) -> None:
        """Real list with the suggested price of a candidate changed: same entry, still a candidate."""
        old = subresource_body("promotions", STARTED)
        new = with_fields(old, CANDIDATE_ID, suggested_discounted_price=2000000.0)

        assert derive_events(promotions_row(old, new)) == []


class TestActivated:
    def test_a_candidate_that_becomes_started_is_one_activated_event_with_its_price(self) -> None:
        """Real candidates-only list with the campaign C-MLA1664342 started at a price (status and price changed)."""
        old = subresource_body("promotions", ONLY_CANDIDATES)
        new = with_fields(old, CANDIDATE_ID, status="started", price=1900000)

        events = derive_events(promotions_row(old, new))

        assert [e.event_type for e in events] == ["promotion_activated"]
        event = events[0]
        assert (event.promotion_id, event.promotion_type) == (CANDIDATE_ID, "SELLER_CAMPAIGN")
        assert (event.old_value, event.new_value) == ("candidate", "1900000")
        assert event.payload == {"original_price": "55882"}

    def test_the_transition_logs_one_row_with_only_the_paths_of_that_entry(self) -> None:
        old = subresource_body("promotions", ONLY_CANDIDATES)
        new = with_fields(old, CANDIDATE_ID, status="started", price=1900000)

        row = promotions_row(old, new)

        assert sorted(c["p"] for c in row.changes) == [f"[{CANDIDATE_ID}].price", f"[{CANDIDATE_ID}].status"]

    def test_price_discount_activation_is_keyed_by_type(self) -> None:
        """Real candidates-only list with PRICE_DISCOUNT started at a price."""
        old = subresource_body("promotions", ONLY_CANDIDATES)
        new = with_fields(old, "PRICE_DISCOUNT", status="started", price=50000)

        (event,) = derive_events(promotions_row(old, new))

        assert event.event_type == "promotion_activated"
        assert (event.promotion_id, event.promotion_type) == (None, "PRICE_DISCOUNT")
        assert event.new_value == "50000"

    def test_an_entry_that_appears_already_started_is_activated_from_nothing(self) -> None:
        """Real started list vs the same list without the started campaign on the old side."""
        new = subresource_body("promotions", STARTED)
        old = without(new, STARTED_ID)

        events = derive_events(promotions_row(old, new))

        assert [(e.event_type, e.old_value, e.new_value) for e in events] == [
            ("promotion_activated", None, "1509999"),
        ]

    def test_a_pending_entry_that_starts_is_activated(self) -> None:
        """Real list with a campaign pending, then started (status changed)."""
        base = subresource_body("promotions", ONLY_CANDIDATES)
        old = with_fields(base, CANDIDATE_ID, status="pending", price=1900000)
        new = with_fields(old, CANDIDATE_ID, status="started")

        (event,) = derive_events(promotions_row(old, new))

        assert (event.event_type, event.old_value, event.new_value) == ("promotion_activated", "pending", "1900000")

    def test_a_candidate_that_becomes_pending_is_not_an_event(self) -> None:
        old = subresource_body("promotions", ONLY_CANDIDATES)
        new = with_fields(old, CANDIDATE_ID, status="pending")

        assert derive_events(promotions_row(old, new)) == []


class TestFinished:
    def test_a_started_promotion_that_becomes_finished_ended(self) -> None:
        """Real started list with the started campaign marked finished (status changed)."""
        old = subresource_body("promotions", STARTED)
        new = with_fields(old, STARTED_ID, status="finished")

        (event,) = derive_events(promotions_row(old, new))

        assert event.event_type == "promotion_finished"
        assert (event.old_value, event.new_value) == ("started", "finished")
        assert event.payload == {"reason": "ended"}
        assert (event.promotion_id, event.promotion_type) == (STARTED_ID, "SELLER_CAMPAIGN")

    def test_a_candidate_that_becomes_finished_was_withdrawn(self) -> None:
        """Real list with a candidate marked finished (status changed)."""
        old = subresource_body("promotions", STARTED)
        new = with_fields(old, CANDIDATE_ID, status="finished")

        (event,) = derive_events(promotions_row(old, new))

        assert event.event_type == "promotion_finished"
        assert (event.old_value, event.new_value) == ("candidate", "finished")
        assert event.payload == {"reason": "withdrawn"}

    def test_a_pending_promotion_that_becomes_finished_ended(self) -> None:
        base = subresource_body("promotions", ONLY_CANDIDATES)
        old = with_fields(base, CANDIDATE_ID, status="pending")
        new = with_fields(old, CANDIDATE_ID, status="finished")

        (event,) = derive_events(promotions_row(old, new))

        assert event.payload == {"reason": "ended"}

    def test_an_entry_that_disappears_from_the_list_is_absent(self) -> None:
        """Real started list vs the same list without the started campaign on the new side."""
        old = subresource_body("promotions", STARTED)
        new = without(old, STARTED_ID)

        (event,) = derive_events(promotions_row(old, new))

        assert event.event_type == "promotion_finished"
        assert (event.old_value, event.new_value) == ("started", None)
        assert event.payload == {"reason": "absent"}

    def test_a_candidate_that_is_no_longer_offered_is_absent_too(self) -> None:
        old = subresource_body("promotions", STARTED)
        new = without(old, CANDIDATE_ID)

        (event,) = derive_events(promotions_row(old, new))

        assert (event.old_value, event.new_value, event.payload) == ("candidate", None, {"reason": "absent"})

    def test_every_entry_removed_from_the_real_list_is_one_finished_event_each(self) -> None:
        """Real payload, all entries removed (no empty list was captured)."""
        old = subresource_body("promotions", STARTED)

        events = derive_events(promotions_row(old, []))

        assert len(old) == 7
        assert len(of_type(events, "promotion_finished")) == 7
        assert {e.payload["reason"] for e in events} == {"absent"}
        assert len({e.promotion_key for e in events}) == 7


class TestPriceChanged:
    def test_a_started_promotion_whose_price_changes_is_price_changed_not_activated(self) -> None:
        """Real started list with the started campaign price changed (1509999 -> 1400000)."""
        old = subresource_body("promotions", STARTED)
        new = with_fields(old, STARTED_ID, price=1400000)

        events = derive_events(promotions_row(old, new))

        assert [e.event_type for e in events] == ["promotion_price_changed"]
        event = events[0]
        assert (event.old_value, event.new_value) == ("1509999", "1400000")
        assert (event.promotion_id, event.promotion_type) == (STARTED_ID, "SELLER_CAMPAIGN")

    def test_a_started_promotion_with_the_same_price_and_another_name_is_no_event(self) -> None:
        old = subresource_body("promotions", STARTED)
        new = with_fields(old, STARTED_ID, name="PREMIUM OCTUBRE 2")

        assert derive_events(promotions_row(old, new)) == []

    def test_one_change_can_yield_several_events(self) -> None:
        """Real started list: price of the started campaign changed, a candidate removed, one added."""
        old = subresource_body("promotions", STARTED)
        new = without(with_fields(old, STARTED_ID, price=1400000), CANDIDATE_ID)
        new.append({**copy.deepcopy(entry(old, CANDIDATE_ID)), "id": "C-MLA1999999"})

        events = derive_events(promotions_row(old, new))

        assert sorted(e.event_type for e in events) == [
            "promotion_finished",
            "promotion_offered",
            "promotion_price_changed",
        ]


class TestEntriesContext:
    def test_two_entries_without_an_id_and_with_the_same_type_are_both_kept(self) -> None:
        """Real candidates-only list with PRICE_DISCOUNT repeated (ML sends one; the context must not lose a twin)."""
        body = subresource_body("promotions", ONLY_CANDIDATES)
        twin = copy.deepcopy(entry(body, "PRICE_DISCOUNT"))
        twin["status"] = "started"
        twin["price"] = 50000
        body.append(twin)

        entries = entries_context("promotions", body, body)["entries"]["new"]

        assert len(entries) == len(body) == 9
        statuses = sorted(e["status"] for k, e in entries.items() if e["type"] == "PRICE_DISCOUNT")
        assert statuses == ["candidate", "started"]

    def test_twins_keep_their_keys_when_ml_reorders_the_list(self) -> None:
        """Same real list with a PRICE_DISCOUNT twin, read in two orders: no key swap, so no false event."""
        body = subresource_body("promotions", ONLY_CANDIDATES)
        twin = copy.deepcopy(entry(body, "PRICE_DISCOUNT"))
        twin.update(status="started", price=50000)
        body.append(twin)
        reordered = list(reversed(body))

        assert (
            entries_context("promotions", body, body)["entries"]["new"]
            == (entries_context("promotions", reordered, reordered)["entries"]["new"])
        )
        assert derive_events(promotions_row(body, reordered)) == []

    def test_an_entry_that_appears_already_pending_is_not_an_event_until_it_starts(self) -> None:
        """Pinned rule (design D16): `promotion_offered` is for candidates only; pending is silent."""
        new = subresource_body("promotions", ONLY_CANDIDATES)
        pending = with_fields(new, CANDIDATE_ID, status="pending", price=1900000)
        old = without(pending, CANDIDATE_ID)

        assert derive_events(promotions_row(old, pending)) == []

        started = with_fields(pending, CANDIDATE_ID, status="started")
        (event,) = derive_events(promotions_row(pending, started))
        assert (event.event_type, event.old_value, event.new_value) == ("promotion_activated", "pending", "1900000")


class TestRowShapes:
    def test_the_rules_need_only_the_stored_row(self) -> None:
        """Re-derivation: a JSON round trip of the stored row yields the same events."""
        old = subresource_body("promotions", STARTED)
        new = without(with_fields(old, STARTED_ID, price=1400000), CANDIDATE_ID)
        row = promotions_row(old, new)
        stored = json.loads(json.dumps({"changes": list(row.changes), "context": dict(row.context)}))

        rederived = ChangeRow(
            id=row.id,
            resource_type="promotions",
            item_id=ITEM,
            kind="change",
            observed_at=T_OBSERVED,
            source_last_updated=None,
            changes=stored["changes"],
            context=stored["context"],
        )

        assert derive_events(rederived) == derive_events(row)
        assert len(derive_events(row)) == 2

    def test_a_restored_row_derives_like_a_change(self) -> None:
        """A promotions resource that was gone and answers again, with a campaign newly started."""
        old = subresource_body("promotions", ONLY_CANDIDATES)
        new = with_fields(old, CANDIDATE_ID, status="started", price=1900000)

        (event,) = derive_events(promotions_row(old, new, kind="restored"))

        assert event.event_type == "promotion_activated"

    def test_a_gone_row_yields_no_promotion_events(self) -> None:
        old = subresource_body("promotions", STARTED)
        row = ChangeRow(
            id=22,
            resource_type="promotions",
            item_id=ITEM,
            kind="gone",
            observed_at=T_OBSERVED,
            source_last_updated=None,
            changes=[],
            context={"official_store_id": 57997, "brand": "Marvo"},
        )

        assert len(old) == 7  # the stored state is not consulted
        assert derive_events(row) == []

    def test_a_row_without_entries_context_yields_nothing(self) -> None:
        row = ChangeRow(
            id=23,
            resource_type="promotions",
            item_id=ITEM,
            kind="change",
            observed_at=T_OBSERVED,
            source_last_updated=None,
            changes=[{"p": "[C-X].status", "op": "replace", "old": "candidate", "new": "started"}],
            context={},
        )

        assert derive_events(row) == []
