"""Pure event rules of the quality resources (design D16): `catalog_competition_won/lost` and
`moderation_applied/resolved`.

Rows are built the way the store builds them: the real diff between two captured bodies (or a deep copy
with the one change named in the test's docstring) plus the `entries` context. The rules see only the
stored row, so deriving from a JSON round trip of it must give the same events. No losing competition
sample and no positive moderation record were ever captured, so those transitions are real payloads with
one labelled field changed.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

import pytest

from app.services.ml_publications.diff import diff, split_excluded
from app.services.ml_publications.events import ChangeRow, dedupe_key, derive_events
from app.services.ml_publications.resources import RESOURCES
from app.services.ml_publications.subresource_context import entries_context
from tests.services.ml_publications.conftest import subresource_body

T_OBSERVED = datetime(2026, 10, 6, 13, 30, tzinfo=timezone.utc)
ITEM = "MLA882393030"
WINNING = "price_to_win_MLA882393030"
NOT_LISTED = "price_to_win_MLA874027718"
NO_MODERATION = "moderation_MLA874027718"


def row_of(resource: str, old, new, *, kind: str = "change", row_id: int = 31) -> ChangeRow:
    spec = RESOURCES[resource]
    reportable, _ = split_excluded(diff(old, new, spec), resource)
    return ChangeRow(
        id=row_id,
        resource_type=resource,
        item_id=ITEM,
        kind=kind,
        observed_at=T_OBSERVED,
        source_last_updated=None,
        changes=[c.as_dict() for c in reportable],
        context={**entries_context(resource, old, new), "official_store_id": 57997, "brand": "Marvo"},
    )


def winning() -> dict:
    return subresource_body("competition", WINNING)


def with_status(body: dict, status: str) -> dict:
    out = copy.deepcopy(body)
    out["status"] = status
    return out


def moderated(body: dict) -> dict:
    """The captured no-moderation body with its only field changed: stands for a record (none was captured)."""
    out = copy.deepcopy(body)
    out["Status"] = 200
    return out


class TestCatalogCompetition:
    def test_not_listed_to_winning_is_one_won_event_with_the_prices(self) -> None:
        """Real not_listed body (MLA874027718) as the old side, real winning body (MLA882393030) as the new."""
        old, new = subresource_body("competition", NOT_LISTED), winning()

        events = derive_events(row_of("competition", old, new))

        assert [e.event_type for e in events] == ["catalog_competition_won"]
        event = events[0]
        assert (event.old_value, event.new_value, event.item_id) == ("not_listed", "winning", ITEM)
        assert event.payload == {"price_to_win": "55882", "current_price": "55882", "currency_id": "ARS"}
        assert (event.promotion_id, event.price_kind) == (None, None)

    def test_winning_to_another_status_is_one_lost_event(self) -> None:
        """Real winning body vs the same body with `status` changed to `competing`."""
        new = with_status(winning(), "competing")

        events = derive_events(row_of("competition", winning(), new))

        assert [e.event_type for e in events] == ["catalog_competition_lost"]
        assert (events[0].old_value, events[0].new_value) == ("winning", "competing")

    @pytest.mark.parametrize("old_status", ["competing", "sharing_first_place", "listed"])
    def test_any_non_winning_status_becoming_winning_is_won(self, old_status) -> None:
        """Real winning body vs the same body with `status` changed on the old side."""
        events = derive_events(row_of("competition", with_status(winning(), old_status), winning()))
        assert [e.event_type for e in events] == ["catalog_competition_won"]

    def test_moving_between_two_non_winning_statuses_is_no_event(self) -> None:
        """Real not_listed body vs the same body with `status` changed to `competing`."""
        old = subresource_body("competition", NOT_LISTED)
        assert derive_events(row_of("competition", old, with_status(old, "competing"))) == []

    def test_a_change_that_keeps_the_status_is_no_event(self) -> None:
        """Real winning body vs the same body with one boost's status changed."""
        new = winning()
        new["boosts"][0]["status"] = "boosted"
        row = row_of("competition", winning(), new)
        assert row.changes and derive_events(row) == []

    def test_a_gone_row_and_an_unchanged_restored_row_raise_no_competition_event(self) -> None:
        old = winning()
        assert derive_events(row_of("competition", old, old, kind="gone")) == []
        assert derive_events(row_of("competition", old, old, kind="restored")) == []

    def test_events_derive_from_the_stored_row_alone(self) -> None:
        row = row_of("competition", subresource_body("competition", NOT_LISTED), winning())
        stored = ChangeRow(**{**row.__dict__, "changes": json.loads(json.dumps(list(row.changes)))})
        assert derive_events(stored) == derive_events(row)

    def test_won_and_lost_of_one_row_cannot_share_an_identity(self) -> None:
        assert dedupe_key(31, "catalog_competition_won", None, None) != dedupe_key(
            31, "catalog_competition_lost", None, None
        )


class TestModeration:
    def test_a_record_appearing_after_no_moderation_is_one_applied_event(self) -> None:
        old = subresource_body("moderation", NO_MODERATION)

        events = derive_events(row_of("moderation", old, moderated(old)))

        assert [e.event_type for e in events] == ["moderation_applied"]
        assert (events[0].old_value, events[0].new_value) == ("no_moderation", "moderation")
        assert events[0].item_id == ITEM

    def test_back_to_the_no_moderation_404_is_one_resolved_event(self) -> None:
        old = subresource_body("moderation", NO_MODERATION)

        events = derive_events(row_of("moderation", moderated(old), old))

        assert [e.event_type for e in events] == ["moderation_resolved"]
        assert (events[0].old_value, events[0].new_value) == ("moderation", "no_moderation")

    def test_a_record_that_only_changes_inside_stays_without_event(self) -> None:
        """No record shape was captured: a change between two records says nothing yet (documented gap)."""
        first = moderated(subresource_body("moderation", NO_MODERATION))
        second = copy.deepcopy(first)
        second["Status"] = 201
        row = row_of("moderation", first, second)
        assert row.changes and derive_events(row) == []

    def test_a_gone_row_raises_no_moderation_event(self) -> None:
        old = subresource_body("moderation", NO_MODERATION)
        assert derive_events(row_of("moderation", old, old, kind="gone")) == []

    def test_a_restored_row_compares_the_last_known_state_with_the_current_one(self) -> None:
        """Gone (a gateway 404), then answered again with a record: the presence changed while unseen."""
        old = subresource_body("moderation", NO_MODERATION)
        events = derive_events(row_of("moderation", old, moderated(old), kind="restored"))
        assert [e.event_type for e in events] == ["moderation_applied"]
