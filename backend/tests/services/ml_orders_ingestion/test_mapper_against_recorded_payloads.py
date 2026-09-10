"""The mapper, run against payloads RECORDED FROM ML, not written by hand.

Why this file exists: `map_order` is fed by two different ML endpoints,
and a hand-written fixture is a guess about their shape. A wrong guess
passes the whole suite while production fails silently. That is not
hypothetical -- the activity receiver's fixture invented
`date_last_updated` (what `/orders/search` returns) for `/orders/<id>`,
which returns `last_updated`. Every order the drain resolved failed to
map, nothing was ingested for a week, and every test was green.

The fixtures under `tests/fixtures/ml_payloads/` are verbatim captures.
Do not hand-edit them; re-capture them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.ml_orders_ingestion.mapper import MappingError, map_order

PAYLOAD_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "ml_payloads"


def _load(name: str) -> dict:
    return json.loads((PAYLOAD_DIR / name).read_text())["payload"]


def _recorded_payloads():
    return sorted(p.name for p in PAYLOAD_DIR.glob("*.json"))


class TestEveryRecordedPayloadMaps:
    def test_there_is_at_least_one_recording_per_endpoint(self):
        """A guard against this suite quietly becoming a no-op if the
        fixtures are moved or renamed."""
        assert set(_recorded_payloads()) >= {"orders_single.json", "orders_search_result.json"}

    @pytest.mark.parametrize("name", _recorded_payloads())
    def test_it_maps(self, name: str):
        mapped = map_order(_load(name))

        assert not isinstance(mapped, MappingError), f"{name} failed to map: {getattr(mapped, 'reason', mapped)}"
        assert mapped.order_id is not None
        assert mapped.seller_id is not None
        assert mapped.ml_last_updated is not None


class TestTheTwoSpellingsAreNotInterchangeable:
    """`/orders/search` results carry BOTH keys, and they do NOT agree --
    in the recorded capture `date_last_updated` is 2026-09-08 while
    `last_updated` is 2026-06-09, three months earlier. So this is not a
    rename to be papered over with `or` in either direction: reading the
    wrong one would silently backdate every order the sweep ingests and
    make live sales look stale.
    """

    def test_the_search_result_really_does_carry_both(self):
        payload = _load("orders_search_result.json")

        assert payload.get("date_last_updated") is not None
        assert payload.get("last_updated") is not None
        assert payload["date_last_updated"] != payload["last_updated"]

    def test_the_search_spelling_wins_when_both_are_present(self):
        """The order's own last-updated fact is `date_last_updated`. If the
        preference is ever flipped, this fails instead of production
        quietly reporting months-old timestamps."""
        payload = _load("orders_search_result.json")

        mapped = map_order(payload)

        assert mapped.ml_last_updated.isoformat() != payload["last_updated"]
        assert mapped.ml_last_updated.date().isoformat() == payload["date_last_updated"][:10]

    def test_the_single_order_endpoint_has_only_the_one_spelling(self):
        """The whole reason the receiver broke: this endpoint does not
        carry `date_last_updated` at all."""
        payload = _load("orders_single.json")

        assert payload.get("date_last_updated") is None
        assert payload.get("last_updated") is not None
