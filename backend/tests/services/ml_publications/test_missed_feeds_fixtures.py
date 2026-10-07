"""The committed `/missed_feeds` captures (2026-10-06): one real response per shape, credentials excluded.

The capture's `stock-location` and `user_products` calls used topic names that do not exist; they answered
`{messages: null}` like any empty page, so they are not committed: only the shape is evidence.
"""

from __future__ import annotations

import pytest

from tests.services.ml_publications.conftest import FIXTURES_DIR, MISSED_FEEDS_FIXTURES, missed_body, missed_call

SAFE_HEADERS = {"date"}
MESSAGE_KEYS = {
    "_id",
    "resource",
    "user_id",
    "topic",
    "application_id",
    "attempts",
    "sent",
    "received",
    "actions",
    "source",
    "request",
    "response",
}


@pytest.mark.parametrize("name", sorted(MISSED_FEEDS_FIXTURES))
def test_fixture_file_exists_with_a_captured_request_path(name):
    call = missed_call(name)
    assert call["path"].startswith("/missed_feeds?app_id=")
    assert call["status"] == 200


@pytest.mark.parametrize("name", sorted(MISSED_FEEDS_FIXTURES))
def test_no_credentials_and_only_safe_headers(name):
    text = (FIXTURES_DIR / MISSED_FEEDS_FIXTURES[name]).read_text(encoding="utf-8").lower()
    assert "authorization" not in text and "bearer" not in text and "access_token" not in text
    assert set(missed_call(name)["headers"]) <= SAFE_HEADERS


def test_a_page_with_messages_carries_the_captured_message_shape():
    messages = missed_body("items")["messages"]
    assert len(messages) == 3
    for message in messages:
        assert set(message) == MESSAGE_KEYS
        assert message["topic"] == "items" and message["source"] == "missed"
        assert message["resource"].startswith("/items/MLA")
        assert isinstance(message["user_id"], str)  # the page answers the seller as a string
    assert messages[0]["resource"] == "/items/MLA3510103662"


def test_the_delivery_attempt_fields_are_present_in_the_capture_so_the_store_must_drop_them():
    message = missed_body("items")["messages"][0]
    assert message["request"]["url"] and message["response"]["http_code"] == 0


def test_an_empty_page_is_messages_null():
    assert missed_body("empty") == {"messages": None}
    assert "topic=items_prices" in missed_call("empty")["path"]


def test_a_page_past_the_last_offset_is_also_messages_null():
    assert missed_body("items_page2") == {"messages": None}
    assert "offset=5" in missed_call("items_page2")["path"]
