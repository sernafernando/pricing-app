"""The committed scan captures: one real response per scanned shape, credentials excluded."""

from __future__ import annotations

import pytest

from tests.services.ml_publications.conftest import FIXTURES_DIR, SCAN_FIXTURES, scan_body, scan_call

SAFE_HEADERS = {"date"}


@pytest.mark.parametrize("name", sorted(SCAN_FIXTURES))
def test_fixture_file_exists_with_a_captured_request_path(name):
    call = scan_call(name)
    assert call["path"].startswith("/users/413658225/items/search?")
    assert call["status"] in (200, 400)


@pytest.mark.parametrize("name", sorted(SCAN_FIXTURES))
def test_no_credentials_and_only_safe_headers(name):
    text = (FIXTURES_DIR / SCAN_FIXTURES[name]).read_text(encoding="utf-8").lower()
    assert "authorization" not in text and "bearer" not in text and "access_token" not in text
    assert set(scan_call(name)["headers"]) <= SAFE_HEADERS


def test_status_pages_carry_results_total_and_a_scroll_id():
    totals = {
        "active_page1": 7789,
        "paused_page1": 16185,
        "closed_page1": 39,
        "pending_page1": 650,
    }
    for name, total in totals.items():
        body = scan_body(name)
        assert body["paging"]["total"] == total
        assert body["scroll_id"] and body["results"], name
        assert all(item_id.startswith("MLA") for item_id in body["results"])


def test_second_page_continues_the_first_scroll_with_different_ids():
    first, second = scan_body("active_page1"), scan_body("active_page2")
    assert "scroll_id=" + first["scroll_id"] in scan_call("active_page2")["path"]
    assert second["scroll_id"] != first["scroll_id"]
    assert not set(first["results"]) & set(second["results"])


@pytest.mark.parametrize("name", ["under_review_empty", "inactive_empty"])
def test_empty_status_answers_an_empty_scroll_id_and_zero_total(name):
    body = scan_body(name)
    assert body["scroll_id"] == "" and body["results"] == [] and body["paging"]["total"] == 0


def test_invalid_scroll_is_http_400_with_the_documented_error_code():
    call = scan_call("invalid_scroll")
    assert call["status"] == 400
    assert call["body"]["error"] == "invalid.scroll.id"
