"""Description parser and mapper, over the captured `/items/{id}/description` responses."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.ml_publications.parsers.description import map_description, parse_description
from app.services.ml_publications.parsers.subresource import MalformedSubResource
from tests.services.ml_publications.conftest import subresource_body, subresource_call


def test_200_is_ok_and_the_body_is_kept_unchanged_as_raw():
    body = subresource_body("description", "description_MLA882393030")
    parsed = parse_description(200, body)
    assert (parsed.state, parsed.status, parsed.error_body) == ("ok", 200, None)
    assert parsed.body == body


def test_captured_404_is_not_found_and_keeps_its_body_as_the_error_body():
    call = subresource_call("description", "description_unknown")
    parsed = parse_description(call["status"], call["body"])
    assert (parsed.state, parsed.status, parsed.body) == ("not_found", 404, None)
    assert parsed.error_body == call["body"]


def test_synthetic_transport_fault_403_with_empty_body_is_an_error_not_gone():
    """Synthetic transport fault: no 403 was captured for this endpoint."""
    parsed = parse_description(403, None)
    assert (parsed.state, parsed.status, parsed.body, parsed.error_body) == ("error", 403, None, None)


@pytest.mark.parametrize("body", [{}, []])
def test_an_empty_error_body_is_recorded_as_received_synthetic_transport_fault(body):
    """Synthetic transport fault: an empty JSON object/list is a body, not an absent one."""
    assert parse_description(500, body).error_body == body


@pytest.mark.parametrize("status", [429, 500, 503])
def test_synthetic_transport_fault_other_non_2xx_are_errors(status):
    """Synthetic transport fault: throttling and server errors carry an arbitrary body."""
    parsed = parse_description(status, {"message": "x"})
    assert parsed.state == "error" and parsed.error_body == {"message": "x"}


def test_200_with_a_non_object_body_is_malformed():
    with pytest.raises(MalformedSubResource):
        parse_description(200, [])


def test_200_without_text_and_plain_text_is_malformed_real_payload_two_fields_removed():
    body = subresource_body("description", "description_MLA882393030")
    del body["text"], body["plain_text"]
    with pytest.raises(MalformedSubResource):
        parse_description(200, body)


def test_mapper_typed_columns_of_a_captured_description():
    body = subresource_body("description", "description_MLA882393030")
    typed = map_description(body)
    assert typed == {
        "plain_text_length": len(body["plain_text"]),
        "ml_last_updated": datetime(2020, 10, 5, 0, 41, 56, tzinfo=timezone.utc),
    }
    assert typed["plain_text_length"] == 463


def test_mapper_tolerates_missing_fields_real_payload_fields_removed():
    body = subresource_body("description", "description_MLA874027718")
    del body["plain_text"], body["last_updated"]
    assert map_description(body) == {"plain_text_length": None, "ml_last_updated": None}
