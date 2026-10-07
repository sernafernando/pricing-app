"""Prices parser and mapper, over the captured `/items/{id}/prices` responses."""

from __future__ import annotations

import copy
from decimal import Decimal
from email.utils import parsedate_to_datetime

import pytest

from app.services.ml_publications.mappers import to_timestamp
from app.services.ml_publications.parsers.prices import map_prices, parse_prices
from app.services.ml_publications.parsers.subresource import MalformedSubResource
from tests.services.ml_publications.conftest import subresource_body, subresource_call


def test_captured_404_has_its_own_error_shape_and_is_not_found():
    call = subresource_call("prices", "prices_unknown")
    parsed = parse_prices(call["status"], call["body"])
    assert (parsed.state, parsed.body) == ("not_found", None)
    assert parsed.error_body == {"error": "The item MLA1 has no prices associated", "code": "not.found", "status": 404}


def test_200_is_ok_and_keeps_the_body():
    body = subresource_body("prices", "prices_started_MLA2146576013")
    parsed = parse_prices(200, body)
    assert parsed.state == "ok" and parsed.body == body


def test_standard_price_only_item():
    typed = map_prices(subresource_body("prices", "prices_MLA903301838"))
    assert typed == {"standard_amount": Decimal("18511.0"), "currency_id": "ARS", "active_promotion_amount": None}


def test_marketplace_standard_wins_over_the_mshops_price():
    body = subresource_body("prices", "prices_MLA874027718")
    assert {e["id"]: e["conditions"]["context_restrictions"] for e in body["prices"]} == {
        "465": ["channel_marketplace"],
        "414": ["channel_mshops"],
    }
    typed = map_prices(body)
    assert typed["standard_amount"] == Decimal("55882.0")  # 39990.0 is the mshops price
    assert typed["active_promotion_amount"] is None


def test_started_promotion_item_has_standard_and_active_promotion_amount():
    typed = map_prices(subresource_body("prices", "prices_started_MLA2146576013"))
    assert typed == {
        "standard_amount": Decimal("2381471.0"),
        "currency_id": "ARS",
        "active_promotion_amount": Decimal("1509999.0"),
    }


def test_promotion_item_with_a_different_price_level():
    typed = map_prices(subresource_body("prices", "prices_candidate_MLA2146646463"))
    assert (typed["standard_amount"], typed["active_promotion_amount"]) == (Decimal("1770276.0"), Decimal("1230699.0"))


def test_marketplace_scoped_standard_beats_an_unrestricted_one_real_payload_one_field_changed():
    body = subresource_body("prices", "prices_MLA874027718")
    for entry in body["prices"]:
        if entry["id"] == "414":
            entry["conditions"]["context_restrictions"] = []
    assert map_prices(body)["standard_amount"] == Decimal("55882.0")


def test_mshops_only_standard_yields_no_standard_amount_real_payload_marketplace_entry_removed():
    body = subresource_body("prices", "prices_MLA874027718")
    body["prices"] = [e for e in body["prices"] if e["id"] != "465"]
    assert map_prices(body)["standard_amount"] is None


def test_empty_prices_list_maps_to_nothing_real_payload_all_entries_removed():
    body = subresource_body("prices", "prices_MLA903301838")
    body["prices"] = []
    parse_prices(200, body)
    assert map_prices(body) == {"standard_amount": None, "currency_id": None, "active_promotion_amount": None}


def test_amounts_are_exact_decimals_not_binary_floats_real_payload_one_field_changed():
    body = subresource_body("prices", "prices_MLA903301838")
    changed = copy.deepcopy(body)
    changed["prices"][0]["amount"] = 18511.1
    assert map_prices(changed)["standard_amount"] == Decimal("18511.1")


@pytest.mark.parametrize("bad", [[], {"id": "MLA1"}, {"prices": {}}, {"prices": [1]}])
def test_200_with_an_unexpected_shape_is_malformed(bad):
    with pytest.raises(MalformedSubResource):
        parse_prices(200, bad)


@pytest.mark.parametrize("name", ["prices_started_MLA2146576013", "prices_candidate_MLA2146646463"])
def test_captured_promotion_entries_are_in_force_when_captured(name):
    """Assumption behind `active_promotion_amount` (see the module docstring): `/prices` lists only
    promotions in force. It is mapped without reading `start_time`/`end_time`; every captured one is
    inside its window at the response time."""
    call = subresource_call("prices", name)
    now = parsedate_to_datetime(call["headers"]["date"])
    promotions = [e for e in call["body"]["prices"] if e["type"] == "promotion"]
    assert promotions
    for entry in promotions:
        conditions = entry["conditions"]
        assert to_timestamp(conditions["start_time"]) <= now < to_timestamp(conditions["end_time"])
