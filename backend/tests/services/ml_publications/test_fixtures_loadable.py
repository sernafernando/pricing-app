"""The committed ML captures exist, cover every bulk shape and carry no credentials."""

from __future__ import annotations

from tests.services.ml_publications.conftest import (
    BULK_CAPTURE,
    FIXTURES_DIR,
    ITEM_SAMPLES,
    ITEM_WITH_VARIATIONS,
    bulk_call,
    load_fixture,
)


def test_bulk_full_shape_has_two_found_items_and_one_404_without_body():
    payload = bulk_call("bulk_full")
    assert [e.get("status_code") for e in payload] == [200, 200, 404]
    assert "body" not in payload[2]


def test_bulk_attributes_shape_has_only_bodies_and_empty_not_found():
    payload = bulk_call("bulk_attributes")
    assert "status_code" not in payload[0] and "id" not in payload[0]
    assert payload[0]["body"]["id"] == "MLA935110613"
    assert payload[2] == {}


def test_legacy_shape_is_code_body_and_not_in_request_order():
    payload = bulk_call("legacy_multiget")
    assert all("code" in e and "body" in e for e in payload)
    assert [e["body"]["id"] for e in payload][0] != "MLA935110613"


def test_samples_and_variations_fixtures_are_present():
    ids = {e["id"] for e in load_fixture(ITEM_SAMPLES)["elements"]}
    assert {"MLA874027718", "MLA882393030", "MLA862580589"} <= ids
    item = load_fixture(ITEM_WITH_VARIATIONS)
    assert item["id"] == "MLA1207279308" and len(item["variations"]) == 4


def test_no_credentials_in_any_fixture_file():
    forbidden = ("authorization", "bearer ", "access_token", "refresh_token", "client_secret")
    for path in FIXTURES_DIR.glob("*.json"):
        text = path.read_text(encoding="utf-8").lower()
        for needle in forbidden:
            assert needle not in text, f"{needle!r} found in {path.name}"
    assert (FIXTURES_DIR / BULK_CAPTURE).exists()
