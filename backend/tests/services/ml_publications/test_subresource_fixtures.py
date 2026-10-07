"""The committed sub-resource captures: one real response per endpoint, credentials excluded."""

from __future__ import annotations

import json

import pytest

from tests.services.ml_publications.conftest import (
    FIXTURES_DIR,
    SUBRESOURCE_FIXTURES,
    load_fixture,
    subresource_call,
)

SAFE_HEADERS = {"date"}


def test_one_fixture_file_per_endpoint():
    assert set(SUBRESOURCE_FIXTURES) == {
        "description",
        "prices",
        "sale_price",
        "promotions",
        "user_product",
        "stock",
        "family",
        "competition",
        "performance",
        "moderation",
        "visits",
    }
    for name in SUBRESOURCE_FIXTURES.values():
        assert (FIXTURES_DIR / name).exists(), name


# Moderation has no 200 yet: not one of the sampled items had a moderation record on 2026-10-06, so its
# fixture holds only the captured no-moderation 404 (the first real record is still to be captured).
NO_200_CAPTURED = {"moderation"}


@pytest.mark.parametrize("resource", sorted(set(SUBRESOURCE_FIXTURES) - NO_200_CAPTURED))
def test_every_endpoint_has_a_real_200_response(resource):
    calls = load_fixture(SUBRESOURCE_FIXTURES[resource])["calls"]
    assert any(call["status"] == 200 for call in calls)


@pytest.mark.parametrize("resource", sorted(SUBRESOURCE_FIXTURES))
def test_no_credentials_and_only_safe_headers(resource):
    text = (FIXTURES_DIR / SUBRESOURCE_FIXTURES[resource]).read_text(encoding="utf-8").lower()
    assert "authorization" not in text and "bearer" not in text and "access_token" not in text
    for call in load_fixture(SUBRESOURCE_FIXTURES[resource])["calls"]:
        assert set(call["headers"]) <= SAFE_HEADERS


def test_unknown_item_404_bodies_differ_by_endpoint():
    description = subresource_call("description", "description_unknown")
    prices = subresource_call("prices", "prices_unknown")
    promotions = subresource_call("promotions", "promotions_unknown")
    assert description["status"] == prices["status"] == promotions["status"] == 404
    assert set(prices["body"]) == {"error", "code", "status"}
    assert prices["body"]["code"] == "not.found"
    assert set(description["body"]) == set(promotions["body"]) == {"message", "error", "status", "cause"}


def test_promotions_cover_started_candidate_and_price_discount_without_id():
    started = subresource_call("promotions", "promotions_started_MLA2146576013")["body"]
    assert {p["status"] for p in started} == {"started", "candidate"}
    assert any(p["type"] == "PRICE_DISCOUNT" and "id" not in p for p in started)


def test_family_ids_survive_as_exact_integers():
    raw = (FIXTURES_DIR / SUBRESOURCE_FIXTURES["family"]).read_text(encoding="utf-8")
    assert "5385385211222674" in raw and json.loads(raw)["calls"][0]["body"]["family_id"] == 5385385211222674


def test_competition_captures_cover_not_listed_and_winning_with_boosts():
    not_listed = subresource_call("competition", "price_to_win_MLA874027718")["body"]
    winning = subresource_call("competition", "price_to_win_MLA882393030")["body"]
    assert (not_listed["status"], not_listed["price_to_win"], not_listed["reason"]) == (
        "not_listed",
        None,
        ["item_not_opted_in"],
    )
    assert (winning["status"], winning["price_to_win"], winning["catalog_product_id"]) == (
        "winning",
        55882,
        "MLA15810042",
    )
    assert winning["boosts"] and winning["winner"]["item_id"] == winning["item_id"]
    assert "?version=v2" in subresource_call("competition", "price_to_win_MLA882393030")["path"]


def test_performance_captures_a_200_for_a_user_product_and_the_product_items_400():
    ok = subresource_call("performance", "performance_MLA874027718")
    refused = subresource_call("performance", "performance_MLA882393030")
    assert (ok["status"], ok["body"]["entity_type"], ok["body"]["entity_id"]) == (200, "USER_PRODUCT", "MLAU245334053")
    assert (ok["body"]["score"], ok["body"]["level"]) == (66, "good")
    assert refused["status"] == 400
    assert refused["body"]["message"] == "Entity not calculated: Product items are not supported"


def test_moderation_captures_are_only_the_no_moderation_404_body():
    calls = load_fixture(SUBRESOURCE_FIXTURES["moderation"])["calls"]
    captured = {(c["status"], json.dumps(c["body"])) for c in calls}
    assert calls and captured == {(404, '{"Status": 404}')}, (
        "a real moderation record was added to the fixture: re-check `map_moderation` (today any 200 object is "
        "`has_moderation = true`), the moderation events and the sub_status/tag set of `bundle.MODERATION_*`"
    )


def test_visits_captures_have_daily_results_and_an_empty_window():
    busy = subresource_call("visits", "visits_MLA882393030")["body"]
    empty = subresource_call("visits", "visits_MLA903301838")["body"]
    assert busy["results"] and all({"date", "total", "visits_detail"} <= set(r) for r in busy["results"])
    assert len({r["date"] for r in busy["results"]}) == len(busy["results"])
    assert (empty["results"], empty["total_visits"], empty["last"], empty["unit"]) == ([], 0, 30, "day")
