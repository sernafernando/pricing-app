"""`parse_replenishment` over the real captures of 2026-10-08 (`replenishment_20261008.json`).

Classification is by HTTP status. A 206 (partial: `x-content-missing`) is a 2xx, so `ok`; none showed up in
the capture, so that case is a real 200 body parsed with status 206 (named in the test).
"""

from __future__ import annotations

import copy

import pytest

from app.services.ml_publications.parsers.replenishment import parse_replenishment
from app.services.ml_publications.parsers.subresource import MalformedSubResource
from tests.services.ml_publications.conftest import load_fixture

FIXTURE = "replenishment_20261008.json"


def capture(name: str) -> dict:
    for call in load_fixture(FIXTURE)["calls"]:
        if call["name"] == name:
            return copy.deepcopy(call)
    raise KeyError(name)


def test_the_capture_holds_the_cases_the_tasks_ask_for():
    names = {call["name"] for call in load_fixture(FIXTURE)["calls"]}
    assert {"full_1", "non_full_1", "full_1_no_caller", "non_full_1_no_caller"} <= names


def test_200_is_ok_and_the_body_is_kept_unchanged():
    call = capture("full_1")
    parsed = parse_replenishment(call["status"], call["body"])
    assert (parsed.state, parsed.status, parsed.body) == ("ok", 200, call["body"])


def test_a_user_product_outside_full_is_a_200_with_null_sections():
    """Real: MLAU370292923 answers 200 with `sales: null` (no 404 showed up in production)."""
    call = capture("non_full_1")
    parsed = parse_replenishment(call["status"], call["body"])
    assert parsed.state == "ok"
    assert parsed.body["sales"] is None


def test_206_is_ok_real_200_body_with_status_changed():
    call = capture("full_1")
    parsed = parse_replenishment(206, call["body"])
    assert (parsed.state, parsed.status) == ("ok", 206)


def test_404_is_not_found():
    parsed = parse_replenishment(404, {"message": "not found", "status": 404})
    assert (parsed.state, parsed.status, parsed.error_body) == (
        "not_found",
        404,
        {"message": "not found", "status": 404},
    )


@pytest.mark.parametrize("status", [403, 429, 500, 502])
def test_other_failures_are_errors_never_gone(status):
    parsed = parse_replenishment(status, {"message": "nope"})
    assert (parsed.state, parsed.status) == ("error", status)
    assert parsed.error_body == {"message": "nope"}


def test_an_error_without_body_is_recorded_with_none():
    assert parse_replenishment(429, None).error_body is None


def test_a_2xx_that_is_not_an_object_is_malformed():
    with pytest.raises(MalformedSubResource):
        parse_replenishment(200, [])


def test_a_2xx_without_the_sales_key_is_malformed_real_payload_key_removed():
    body = capture("full_1")["body"]
    del body["sales"]
    with pytest.raises(MalformedSubResource):
        parse_replenishment(200, body)


def test_sales_of_the_wrong_type_is_malformed_real_payload_field_changed():
    body = capture("full_1")["body"]
    body["sales"] = "none"
    with pytest.raises(MalformedSubResource):
        parse_replenishment(200, body)
