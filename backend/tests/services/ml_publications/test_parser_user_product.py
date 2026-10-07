"""User product, stock and family parsers and mappers, over the captured responses."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.ml_publications.parsers.family import map_family, parse_family
from app.services.ml_publications.parsers.subresource import MalformedSubResource
from app.services.ml_publications.parsers.user_product import map_user_product, parse_user_product
from app.services.ml_publications.parsers.user_product_stock import map_user_product_stock, parse_user_product_stock
from tests.services.ml_publications.conftest import subresource_body

UP_MARVO_KEYBOARD = "user_product_MLAU245334053"
UP_MOUSEPAD = "user_product_MLAU266459622"
FAMILY_KEYBOARD = "family_5385385211222674"
FAMILY_MOUSEPAD = "family_994279717105509"


# --- user product ---------------------------------------------------------------------------


def test_user_product_200_is_ok_and_kept_unchanged():
    body = subresource_body("user_product", UP_MOUSEPAD)
    parsed = parse_user_product(200, body)
    assert (parsed.state, parsed.status, parsed.body) == ("ok", 200, body)


def test_user_product_typed_columns_keep_the_family_id_exact():
    typed = map_user_product(subresource_body("user_product", UP_MARVO_KEYBOARD))
    assert typed["family_id"] == 5385385211222674
    assert isinstance(typed["family_id"], int)
    assert typed["domain_id"] == "MLA-PC_KEYBOARDS"
    assert typed["catalog_product_id"] == "MLA15810042"
    assert typed["ml_last_updated"] == datetime(2026, 10, 2, 19, 21, 52, 233000, tzinfo=timezone.utc)


def test_user_product_second_capture():
    typed = map_user_product(subresource_body("user_product", UP_MOUSEPAD))
    assert typed == {
        "family_id": 994279717105509,
        "name": "Mouse Pad Gamer Marvo G41 Xl 900x400x3mm Microfibra Tela Negro",
        "domain_id": "MLA-MOUSE_PADS",
        "catalog_product_id": "MLA16034201",
        "ml_last_updated": datetime(2026, 10, 3, 1, 17, 43, 172000, tzinfo=timezone.utc),
    }


def test_user_product_without_family_maps_to_none_real_payload_field_removed():
    body = subresource_body("user_product", UP_MOUSEPAD)
    del body["family_id"], body["catalog_product_id"]
    typed = map_user_product(body)
    assert typed["family_id"] is None and typed["catalog_product_id"] is None


def test_user_product_non_2xx_synthetic_transport_fault_403_empty_body():
    """Synthetic transport fault: no user-product error was captured."""
    parsed = parse_user_product(403, None)
    assert (parsed.state, parsed.body, parsed.error_body) == ("error", None, None)
    assert parse_user_product(404, {"message": "x"}).state == "not_found"


@pytest.mark.parametrize("bad", [[], {}, {"id": 5}])
def test_user_product_200_without_a_string_id_is_malformed(bad):
    with pytest.raises(MalformedSubResource):
        parse_user_product(200, bad)


# --- stock ----------------------------------------------------------------------------------


def test_stock_total_is_the_sum_of_location_quantities():
    body = subresource_body("stock", "user_product_stock_MLAU266459622")
    assert [loc["quantity"] for loc in body["locations"]] == [26, 0]
    assert map_user_product_stock(body) == {
        "total_quantity": 26,
        "ml_last_updated": datetime(2026, 10, 2, 20, 51, 26, tzinfo=timezone.utc),
    }


def test_stock_total_over_the_other_capture():
    assert map_user_product_stock(subresource_body("stock", "user_product_stock_MLAU245334053"))["total_quantity"] == 2


def test_stock_total_adds_every_location_real_payload_one_field_changed():
    body = subresource_body("stock", "user_product_stock_MLAU266459622")
    body["locations"][1]["quantity"] = 4
    assert map_user_product_stock(body)["total_quantity"] == 30


def test_stock_without_locations_has_no_total_real_payload_field_removed():
    body = subresource_body("stock", "user_product_stock_MLAU266459622")
    del body["locations"]
    assert map_user_product_stock(body)["total_quantity"] is None


def test_stock_with_an_empty_locations_list_totals_zero_real_payload_all_entries_removed():
    body = subresource_body("stock", "user_product_stock_MLAU266459622")
    body["locations"] = []
    parse_user_product_stock(200, body)
    assert map_user_product_stock(body)["total_quantity"] == 0


def test_stock_403_is_recorded_as_an_error_with_an_empty_body_synthetic_transport_fault():
    """Synthetic transport fault: no 403 was captured; the spec names this case for `/stock`."""
    parsed = parse_user_product_stock(403, None)
    assert (parsed.state, parsed.status, parsed.body, parsed.error_body) == ("error", 403, None, None)


@pytest.mark.parametrize("bad", [[], {"id": "MLAU1"}, {"id": "MLAU1", "locations": {}}, {"locations": []}])
def test_stock_200_with_an_unexpected_shape_is_malformed(bad):
    with pytest.raises(MalformedSubResource):
        parse_user_product_stock(200, bad)


# --- family ---------------------------------------------------------------------------------


def test_family_200_keeps_the_family_id_exact_as_an_integer():
    body = subresource_body("family", FAMILY_KEYBOARD)
    parsed = parse_family(200, body)
    assert parsed.state == "ok"
    assert parsed.body["family_id"] == 5385385211222674 and isinstance(parsed.body["family_id"], int)


def test_family_typed_columns():
    assert map_family(subresource_body("family", FAMILY_KEYBOARD)) == {"user_products_ids": ["MLAU245334053"]}
    assert map_family(subresource_body("family", FAMILY_MOUSEPAD)) == {"user_products_ids": ["MLAU266459622"]}


def test_family_with_several_user_products_keeps_them_all_real_payload_one_field_changed():
    body = subresource_body("family", FAMILY_KEYBOARD)
    body["user_products_ids"].append("MLAU1")
    assert map_family(body)["user_products_ids"] == ["MLAU245334053", "MLAU1"]


def test_family_404_synthetic_transport_fault():
    """Synthetic transport fault: no family 404 was captured."""
    assert parse_family(404, {"message": "x"}).state == "not_found"


@pytest.mark.parametrize(
    "bad",
    [[], {"user_products_ids": []}, {"family_id": "5385385211222674", "user_products_ids": []}, {"family_id": 1}],
)
def test_family_200_with_an_unexpected_shape_is_malformed(bad):
    with pytest.raises(MalformedSubResource):
        parse_family(200, bad)
