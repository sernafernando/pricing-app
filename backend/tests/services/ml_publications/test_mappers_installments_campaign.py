"""`installments_campaign`: the `INSTALLMENTS_CAMPAIGN` sale term as a typed column, from real captures.

The markup of a publication needs this value (the fallback of the campaign tag). It used to be extracted per
request from the whole `raw` body; it is now filled at ingest by the item mapper and read as a plain column. The
cases below are the 16 captured items of `listing_prices_cases.json` (each records the campaign ML reported) and
every full item body captured in `items_bulk_samples_20261006.json`.
"""

from __future__ import annotations

import copy

import pytest

from app.services.ml_publications import verification
from app.services.ml_publications.mappers import map_item
from tests.services.ml_publications.conftest import ITEM_SAMPLES, load_fixture

CASES = load_fixture("listing_prices_cases.json")["cases"]


def _term_values(body: dict) -> list:
    return [
        term.get("value_name") for term in body.get("sale_terms") or [] if term.get("id") == "INSTALLMENTS_CAMPAIGN"
    ]


@pytest.mark.parametrize("case", CASES, ids=[case["item_id"] for case in CASES])
def test_each_captured_item_maps_the_campaign_it_was_captured_with(case) -> None:
    typed = map_item({"id": case["item_id"], "sale_terms": case["sale_terms"], "tags": case["tags"]})
    assert typed["installments_campaign"] == case["installments_campaign"]


def test_the_sixteen_cases_cover_both_a_campaign_and_none() -> None:
    values = {case["installments_campaign"] for case in CASES}
    assert None in values and {"3x_campaign", "9x_campaign", "12x_campaign"} <= values


def test_every_captured_full_body_maps_its_first_installments_term_or_none() -> None:
    elements = [e for e in load_fixture(ITEM_SAMPLES)["elements"] if isinstance(e.get("body"), dict)]
    assert elements
    for element in elements:
        found = _term_values(element["body"])
        expected = found[0] if found else None
        assert map_item(copy.deepcopy(element["body"]))["installments_campaign"] == expected, element["id"]


def test_a_body_without_sale_terms_has_no_campaign() -> None:
    assert map_item({})["installments_campaign"] is None
    assert map_item({"sale_terms": None})["installments_campaign"] is None
    assert map_item({"sale_terms": []})["installments_campaign"] is None


def test_the_first_term_that_carries_a_value_wins_like_the_json_path_did() -> None:
    # Derived from a captured term: the same term twice with different values, and one without `value_name`.
    captured = next(t for case in CASES for t in case["sale_terms"] if t["id"] == "INSTALLMENTS_CAMPAIGN")
    bare = {key: value for key, value in captured.items() if key != "value_name"}
    first, second = {**captured, "value_name": "3x_campaign"}, {**captured, "value_name": "12x_campaign"}
    assert map_item({"sale_terms": [bare, first, second]})["installments_campaign"] == "3x_campaign"
    assert map_item({"sale_terms": [second, first]})["installments_campaign"] == "12x_campaign"


def test_a_null_value_name_is_no_campaign() -> None:
    captured = next(t for case in CASES for t in case["sale_terms"] if t["id"] == "INSTALLMENTS_CAMPAIGN")
    assert map_item({"sale_terms": [{**captured, "value_name": None}]})["installments_campaign"] is None


def test_the_divergence_check_compares_the_new_column_too() -> None:
    assert "installments_campaign" in verification.TYPED_COLUMNS


def test_a_single_term_object_instead_of_a_list_is_read_like_the_lax_json_path_did() -> None:
    # `$.sale_terms[*]` in lax mode treats an object as a one-element array. Derived from a captured term; ML
    # sends a list, but the backfill (SQL) and the ingest (this mapper) must agree on any stored body.
    captured = next(t for case in CASES for t in case["sale_terms"] if t["id"] == "INSTALLMENTS_CAMPAIGN")
    assert map_item({"sale_terms": captured})["installments_campaign"] == captured["value_name"]
    assert map_item({"sale_terms": {"id": "WARRANTY_TYPE", "value_name": "x"}})["installments_campaign"] is None
