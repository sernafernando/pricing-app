"""Per-location stock of `map_user_product_stock`, over the captured `/user-products/{id}/stock` bodies.

`full_quantity` is the `meli_facility` quantity; `own_quantity` adds `selling_address` and
`seller_warehouse`. The captures only hold `selling_address` and `meli_facility`; a `seller_warehouse`
entry is a real body with one `type` changed (named in the test).
"""

from __future__ import annotations

import pytest

from app.services.ml_publications.parsers.user_product_stock import map_user_product_stock
from tests.services.ml_publications.conftest import subresource_body

MOUSEPAD = "user_product_stock_MLAU266459622"  # selling_address 26, meli_facility 0
KEYBOARD = "user_product_stock_MLAU245334053"  # selling_address 2, meli_facility 0


def test_the_captured_bodies_split_into_own_and_full():
    assert map_user_product_stock(subresource_body("stock", MOUSEPAD))["own_quantity"] == 26
    assert map_user_product_stock(subresource_body("stock", MOUSEPAD))["full_quantity"] == 0
    assert map_user_product_stock(subresource_body("stock", KEYBOARD))["own_quantity"] == 2
    assert map_user_product_stock(subresource_body("stock", KEYBOARD))["full_quantity"] == 0


def test_meli_facility_quantity_is_the_full_stock_real_payload_one_field_changed():
    body = subresource_body("stock", MOUSEPAD)
    body["locations"][1]["quantity"] = 7
    typed = map_user_product_stock(body)
    assert (typed["full_quantity"], typed["own_quantity"], typed["total_quantity"]) == (7, 26, 33)


def test_seller_warehouse_adds_to_own_stock_real_payload_one_type_changed():
    body = subresource_body("stock", MOUSEPAD)
    body["locations"].append({"type": "seller_warehouse", "quantity": 5})
    typed = map_user_product_stock(body)
    assert (typed["own_quantity"], typed["full_quantity"], typed["total_quantity"]) == (31, 0, 31)


def test_an_absent_type_counts_zero_when_the_list_is_valid_real_payload_entry_removed():
    body = subresource_body("stock", MOUSEPAD)
    body["locations"] = [loc for loc in body["locations"] if loc["type"] == "selling_address"]
    typed = map_user_product_stock(body)
    assert (typed["own_quantity"], typed["full_quantity"]) == (26, 0)


def test_an_empty_locations_list_is_zero_everywhere_real_payload_all_entries_removed():
    body = subresource_body("stock", MOUSEPAD)
    body["locations"] = []
    typed = map_user_product_stock(body)
    assert (typed["own_quantity"], typed["full_quantity"], typed["total_quantity"]) == (0, 0, 0)


@pytest.mark.parametrize("locations", ["absent", None, {"type": "meli_facility", "quantity": 3}, "x"])
def test_locations_that_are_not_a_list_give_no_split_real_payload_field_changed(locations):
    body = subresource_body("stock", MOUSEPAD)
    if locations == "absent":
        del body["locations"]
    else:
        body["locations"] = locations
    typed = map_user_product_stock(body)
    assert (typed["own_quantity"], typed["full_quantity"], typed["total_quantity"]) == (None, None, None)


def test_unknown_types_and_non_integer_quantities_are_ignored_real_payload_fields_changed():
    body = subresource_body("stock", MOUSEPAD)
    body["locations"] = [
        {"type": "selling_address", "quantity": 3},
        {"type": "meli_facility", "quantity": True},
        {"type": "somewhere_new", "quantity": 9},
        {"type": "meli_facility", "quantity": "4"},
        "junk",
    ]
    typed = map_user_product_stock(body)
    assert (typed["own_quantity"], typed["full_quantity"]) == (3, 0)
