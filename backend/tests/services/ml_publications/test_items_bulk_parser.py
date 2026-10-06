"""`/items/bulk` parser. Inputs come from the real 2026-10-06 capture."""

from __future__ import annotations

import copy

import pytest

from app.services.ml_publications.parsers.items_bulk import BulkElement, MalformedBulkResponse, parse_items_bulk
from tests.services.ml_publications.conftest import bulk_call

REQUESTED = ["MLA935110613", "MLA934406852", "MLA1"]


def test_full_mixed_batch_yields_200_200_404_without_exception():
    result = parse_items_bulk(REQUESTED, bulk_call("bulk_full"), filtered=False)
    assert [(e.requested_id, e.status, e.partial) for e in result] == [
        ("MLA935110613", 200, False),
        ("MLA934406852", 200, False),
        ("MLA1", 404, False),
    ]
    assert result[0].body["id"] == "MLA935110613" and result[1].body["id"] == "MLA934406852"
    assert result[2].body is None


def test_filtered_shape_matches_by_body_id_and_marks_not_found_partial():
    result = parse_items_bulk(REQUESTED, bulk_call("bulk_attributes"), filtered=True)
    assert [(e.requested_id, e.status, e.partial) for e in result] == [
        ("MLA935110613", 200, True),
        ("MLA934406852", 200, True),
        ("MLA1", 404, True),
    ]
    assert result[0].body == {"id": "MLA935110613", "available_quantity": 0, "status": "paused"}


def test_filtered_shape_matches_by_body_id_even_when_response_order_differs_real_payload_reordered():
    payload = bulk_call("bulk_attributes")
    payload[0], payload[1] = payload[1], payload[0]
    result = parse_items_bulk(REQUESTED, payload, filtered=True)
    assert [e.requested_id for e in result] == REQUESTED
    assert result[0].body["id"] == "MLA935110613"


def test_filtered_empty_element_colliding_with_an_id_match_raises_malformed_real_payload_one_element_moved():
    payload = bulk_call("bulk_attributes")
    payload[0], payload[2] = payload[2], payload[0]  # `{}` sits at index 0, but MLA935110613 is matched by id
    with pytest.raises(MalformedBulkResponse):
        parse_items_bulk(REQUESTED, payload, filtered=True)


def test_count_mismatch_raises_malformed_real_payload_one_element_removed():
    payload = bulk_call("bulk_full")[:2]
    with pytest.raises(MalformedBulkResponse):
        parse_items_bulk(REQUESTED, payload, filtered=False)


def test_unrequested_id_raises_malformed_real_payload_one_id_changed():
    payload = bulk_call("bulk_full")
    payload[1]["id"] = "MLA999999999"
    payload[1]["body"]["id"] = "MLA999999999"
    with pytest.raises(MalformedBulkResponse):
        parse_items_bulk(REQUESTED, payload, filtered=False)


def test_duplicate_id_raises_malformed_real_payload_one_element_duplicated():
    payload = bulk_call("bulk_full")
    payload[1] = copy.deepcopy(payload[0])
    with pytest.raises(MalformedBulkResponse):
        parse_items_bulk(REQUESTED, payload, filtered=False)


def test_found_element_without_body_raises_malformed_real_payload_body_removed():
    payload = bulk_call("bulk_full")
    del payload[0]["body"]
    with pytest.raises(MalformedBulkResponse):
        parse_items_bulk(REQUESTED, payload, filtered=False)


def test_non_list_payload_raises_malformed():
    with pytest.raises(MalformedBulkResponse):
        parse_items_bulk(REQUESTED, {"message": "boom"}, filtered=False)


@pytest.mark.parametrize("status", [403, 429, 500, 503])
def test_other_element_status_is_a_failure_not_gone_synthetic_transport_fault(status):
    """Synthetic transport fault: the capture holds no 403/429/5xx element, so the status is injected."""
    payload = bulk_call("bulk_full")
    payload[1] = {"id": "MLA934406852", "status_code": status, "error": {"message": "injected"}}
    result = parse_items_bulk(REQUESTED, payload, filtered=False)
    assert result[1] == BulkElement(requested_id="MLA934406852", status=status, body=None, partial=False)


def test_legacy_shape_parses_by_body_id_although_order_differs():
    payload = bulk_call("legacy_multiget")
    assert payload[0]["body"]["id"] != REQUESTED[0]  # captured order differs from the request order
    result = parse_items_bulk(REQUESTED, payload, filtered=False)
    assert [(e.requested_id, e.status) for e in result] == [
        ("MLA935110613", 200),
        ("MLA934406852", 200),
        ("MLA1", 404),
    ]
    assert result[0].body["id"] == "MLA935110613"


def test_single_item_bulk_response():
    result = parse_items_bulk(["MLA935110613"], bulk_call("bulk_single"), filtered=False)
    assert [(e.requested_id, e.status) for e in result] == [("MLA935110613", 200)]
