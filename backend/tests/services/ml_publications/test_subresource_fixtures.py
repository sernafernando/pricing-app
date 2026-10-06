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
    }
    for name in SUBRESOURCE_FIXTURES.values():
        assert (FIXTURES_DIR / name).exists(), name


@pytest.mark.parametrize("resource", sorted(SUBRESOURCE_FIXTURES))
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
