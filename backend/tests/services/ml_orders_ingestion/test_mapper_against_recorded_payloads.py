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

That directory holds ORDER PAYLOADS ONLY, because every file in it is
handed to `map_order` below. Recordings of anything else (a list of charge
names, say) live elsewhere -- putting one here makes this test try to map
it, which passes locally if you only run the suite you were editing and
fails in CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.ml_orders_ingestion.mapper import MappingError, map_order

PAYLOAD_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "ml_payloads"


def _load(name: str) -> dict:
    return json.loads((PAYLOAD_DIR / name).read_text(encoding="utf-8"))["payload"]


def _recorded_payloads():
    return sorted(p.name for p in PAYLOAD_DIR.glob("*.json"))


class TestTheDirectoryHoldsOrderPayloadsAndNothingElse:
    """The module docstring says this directory is order payloads only.
    Saying it is not enforcing it -- a recording of something else
    (a list of charge names, say) dropped in here gets handed to
    `map_order` by the test below, which is exactly how CI went red on a
    change that was green locally. So the invariant is asserted, not
    described."""

    def test_the_directory_is_not_empty(self):
        """A parametrized test over an empty glob generates NO cases and
        the suite goes green having checked nothing. If the recordings
        move or the pattern stops matching, that has to be a failure, not
        a silent skip."""
        assert _recorded_payloads(), f"no recordings found under {PAYLOAD_DIR}"

    @pytest.mark.parametrize("name", _recorded_payloads())
    def test_each_file_is_shaped_like_an_ml_order(self, name: str):
        # `encoding` is explicit because these payloads carry accented
        # product titles: on a machine whose default encoding is not UTF-8
        # this would raise a decode error that reads like a corrupt file.
        doc = json.loads((PAYLOAD_DIR / name).read_text(encoding="utf-8"))

        # Checked BEFORE indexing: a file whose top level is a list or a
        # string would otherwise raise TypeError from the subscript below,
        # and the failure would name Python's error rather than the actual
        # problem, which is that the file does not belong here.
        assert isinstance(doc, dict), f"{name} is a {type(doc).__name__} at top level, not an order recording"
        assert "payload" in doc, f"{name} has no `payload` key -- is it an order recording?"
        payload = doc["payload"]
        assert isinstance(payload, dict), f"{name} carries a {type(payload).__name__}, not an order object"
        for required in ("id", "seller"):
            assert required in payload, (
                f"{name} has no `{required}` -- ML order payloads always do. "
                f"Recordings of anything else belong outside {PAYLOAD_DIR.name}/."
            )


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
