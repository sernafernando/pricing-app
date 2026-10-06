"""Raw ML item body -> typed columns. Inputs are real captures."""

from __future__ import annotations

import ast
import copy
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import app.services.ml_publications.mappers as mappers_module
from app.services.ml_publications.mappers import map_item
from tests.services.ml_publications.conftest import bulk_item, sample_item


def test_mla935110613_exact_typed_values():
    typed = map_item(bulk_item("MLA935110613"))
    assert typed["item_id"] == "MLA935110613"
    assert typed["status"] == "paused"
    assert typed["sub_status"] == ["out_of_stock"]
    assert typed["listing_type_id"] == "gold_special"
    assert typed["official_store_id"] == 57997
    assert typed["catalog_listing"] is False
    assert typed["seller_custom_field"] is None
    assert typed["health"] == Decimal("0.66")
    assert len(typed["tags"]) == 6
    assert typed["brand"] == "Marvo"
    assert typed["seller_id"] == 413658225
    assert typed["currency_id"] == "ARS"
    assert typed["available_quantity"] == 0 and typed["sold_quantity"] == 79 and typed["initial_quantity"] == 79
    assert typed["price"] == Decimal("24863") and typed["base_price"] == Decimal("24863")
    assert typed["original_price"] is None
    assert typed["shipping_mode"] == "me2" and typed["logistic_type"] == "cross_docking"
    assert typed["free_shipping"] is False
    assert typed["parent_item_id"] is None and typed["inventory_id"] == "BWQF98066"
    assert typed["domain_id"] == "MLA-KEYBOARD_AND_MOUSE_KITS"
    assert typed["user_product_id"] == "MLAU282291766" and typed["catalog_product_id"] == "MLA19771902"


def test_timestamps_are_timezone_aware_datetimes():
    typed = map_item(bulk_item("MLA935110613"))
    assert typed["ml_last_updated"] == datetime(2026, 10, 2, 22, 47, 49, 854000, tzinfo=timezone.utc)
    assert typed["date_created"].tzinfo is not None
    assert typed["stop_time"] == typed["end_time"]


def test_mla934406852_catalog_item_with_custom_field_and_null_health():
    typed = map_item(bulk_item("MLA934406852"))
    assert typed["catalog_listing"] is True
    assert typed["seller_custom_field"] == "126"
    assert typed["health"] is None
    # Captured reality: this item also carries a SELLER_SKU attribute (value_id null, value in value_name).
    assert typed["seller_sku"] == "840006604815"


def test_missing_price_fields_yield_three_none_real_payload_three_fields_removed():
    raw = bulk_item("MLA935110613")
    for field in ("price", "base_price", "original_price"):
        raw.pop(field, None)
    typed = map_item(raw)
    assert (typed["price"], typed["base_price"], typed["original_price"]) == (None, None, None)


def test_family_id_is_exact():
    typed = map_item(bulk_item("MLA935110613"))
    assert typed["family_id"] == 7695306917964170


def test_seller_sku_comes_from_value_name_and_does_not_override_custom_field():
    typed = map_item(sample_item("MLA882393030"))
    assert typed["seller_sku"] == "6932391923412"
    assert typed["seller_custom_field"] == "355"
    sku_attr = next(a for a in sample_item("MLA882393030")["attributes"] if a["id"] == "SELLER_SKU")
    assert sku_attr["value_id"] is None  # ML leaves value_id null; the SKU lives in value_name


def test_item_without_seller_sku_attribute_yields_null():
    typed = map_item(sample_item("MLA862580589"))
    assert typed["seller_sku"] is None


def test_tolerates_null_and_missing_fields_real_payload_fields_removed():
    raw = bulk_item("MLA935110613")
    for field in ("shipping", "attributes", "tags", "sub_status", "last_updated", "health"):
        raw.pop(field, None)
    typed = map_item(raw)
    assert typed["brand"] is None and typed["seller_sku"] is None
    assert typed["tags"] is None and typed["sub_status"] is None
    assert typed["shipping_mode"] is None and typed["logistic_type"] is None and typed["free_shipping"] is None
    assert typed["ml_last_updated"] is None and typed["health"] is None


def test_mapper_does_not_mutate_its_input():
    raw = bulk_item("MLA935110613")
    snapshot = copy.deepcopy(raw)
    map_item(raw)
    assert raw == snapshot


def test_module_imports_no_gbp_or_erp_code():
    tree = ast.parse(Path(mappers_module.__file__).read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    forbidden = ("gbp", "producto", "erp", "publicacion", "models")
    assert not [m for m in imported if any(token in m.lower() for token in forbidden)]


# --- variations (capture 12: MLA1207279308, closed, 4 variations, no per-variation attributes) ---


def _item_with_variations() -> dict:
    from tests.services.ml_publications.conftest import ITEM_WITH_VARIATIONS, load_fixture

    return load_fixture(ITEM_WITH_VARIATIONS)


def test_captured_item_yields_four_variation_rows():
    from app.services.ml_publications.mappers import map_variations

    raw = _item_with_variations()
    rows = map_variations(raw)
    assert len(rows) == 4
    assert [r["variation_id"] for r in rows] == [v["id"] for v in raw["variations"]]
    for row, variation in zip(rows, raw["variations"]):
        assert row["item_id"] == "MLA1207279308"
        assert row["raw"] == variation
        assert row["user_product_id"] == variation["user_product_id"]
        assert row["seller_custom_field"] is None
        assert row["seller_sku"] is None  # captured variations carry no `attributes`
        assert row["available_quantity"] == variation["available_quantity"]
        assert row["sold_quantity"] == variation["sold_quantity"]


def test_variation_custom_field_is_typed_real_payload_one_field_changed():
    from app.services.ml_publications.mappers import map_variations

    raw = _item_with_variations()
    raw["variations"][1]["seller_custom_field"] = "ABC-1"
    rows = map_variations(raw)
    assert [r["seller_custom_field"] for r in rows] == [None, "ABC-1", None, None]


def test_item_with_empty_variations_yields_no_rows():
    from app.services.ml_publications.mappers import map_variations

    raw = bulk_item("MLA935110613")
    assert raw["variations"] == []
    assert map_variations(raw) == []


def test_variation_without_attributes_never_raises_and_variations_key_may_be_missing():
    from app.services.ml_publications.mappers import map_variations

    raw = _item_with_variations()
    assert all("attributes" not in v for v in raw["variations"])
    assert len(map_variations(raw)) == 4
    del raw["variations"]
    assert map_variations(raw) == []
    raw["variations"] = None
    assert map_variations(raw) == []


def test_variation_seller_sku_is_read_from_attributes_value_name_when_present_real_payload_one_field_added():
    from app.services.ml_publications.mappers import map_variations

    raw = _item_with_variations()
    raw["variations"][0]["attributes"] = [{"id": "SELLER_SKU", "value_id": None, "value_name": "SKU-9"}]
    rows = map_variations(raw)
    assert rows[0]["seller_sku"] == "SKU-9" and rows[1]["seller_sku"] is None
