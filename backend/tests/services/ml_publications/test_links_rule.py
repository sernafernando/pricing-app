"""Pure automatic SKU rule of the product links (design D20, spec Domain 6).

Items are real captures; a transition is a deep copy of a real payload with exactly one field
changed (said in the test). `codigo` indexes are plain test data: they stand for our own
`productos_erp` table, not for an ML payload.
"""

from __future__ import annotations

from app.services.ml_publications import links
from app.services.ml_publications.mappers import map_item, map_variations
from tests.services.ml_publications.conftest import bulk_item, item_with_variations, sample_item

SKU_ATTR = "seller_sku_attr"
CUSTOM = "seller_custom_field"


def units_of(body: dict) -> list[links.LinkUnit]:
    return links.units_for_item(map_item(body), map_variations(body))


def only_unit(body: dict) -> links.LinkUnit:
    (unit,) = units_of(body)
    return unit


def drop_seller_sku(body: dict) -> dict:
    """Real payload minus its SELLER_SKU attribute (one field changed)."""
    body["attributes"] = [a for a in body["attributes"] if a["id"] != "SELLER_SKU"]
    return body


class TestSkuKey:
    def test_seller_sku_wins_over_seller_custom_field(self) -> None:
        assert links.sku_key("6932391923412", "355") == ("6932391923412", SKU_ATTR)

    def test_falls_back_to_seller_custom_field(self) -> None:
        assert links.sku_key(None, "126") == ("126", CUSTOM)

    def test_empty_string_counts_as_absent(self) -> None:
        assert links.sku_key("", "126") == ("126", CUSTOM)
        assert links.sku_key("", "") == (None, None)
        assert links.sku_key(None, None) == (None, None)

    def test_a_value_that_is_not_text_is_absent(self) -> None:
        assert links.sku_key(None, 126) == (None, None)

    def test_the_value_is_kept_exactly_as_ml_sent_it(self) -> None:
        assert links.sku_key(" pc-10400 ", None) == (" pc-10400 ", SKU_ATTR)


class TestUnits:
    def test_item_without_variations_has_one_item_level_unit(self) -> None:
        unit = only_unit(bulk_item("MLA935110613"))
        assert (unit.item_id, unit.variation_id) == ("MLA935110613", 0)
        assert (unit.key, unit.sku_field) == ("6932391923481", SKU_ATTR)

    def test_the_captured_seller_sku_wins_over_the_custom_field(self) -> None:
        unit = only_unit(sample_item("MLA882393030"))
        assert (unit.key, unit.sku_field) == ("6932391923412", SKU_ATTR)

    def test_item_with_variations_has_one_unit_per_variation_and_no_item_level_unit(self) -> None:
        units = units_of(item_with_variations())
        assert [u.variation_id for u in units] == [175550253195, 175550253196, 175550253197, 175550253198]
        assert all(u.item_id == "MLA1207279308" for u in units)

    def test_variations_without_a_key_inherit_the_item_key(self) -> None:
        body = item_with_variations()
        body["seller_custom_field"] = "126"  # real payload, one field changed
        units = units_of(body)
        assert {(u.key, u.sku_field) for u in units} == {("126", CUSTOM)}

    def test_a_variation_with_its_own_custom_field_uses_it(self) -> None:
        body = item_with_variations()
        body["seller_custom_field"] = "126"  # real payload, two fields changed (item and one variation)
        body["variations"][0]["seller_custom_field"] = "355"
        units = {u.variation_id: u for u in units_of(body)}
        assert (units[175550253195].key, units[175550253195].sku_field) == ("355", CUSTOM)
        assert units[175550253196].key == "126"

    def test_a_variation_with_its_own_seller_sku_attribute_uses_it(self) -> None:
        body = item_with_variations()
        body["seller_custom_field"] = "126"
        body["variations"][1]["attributes"] = [{"id": "SELLER_SKU", "value_id": None, "value_name": "840006604815"}]
        units = {u.variation_id: u for u in units_of(body)}
        assert (units[175550253196].key, units[175550253196].sku_field) == ("840006604815", SKU_ATTR)

    def test_no_key_at_all_still_yields_units_without_a_key(self) -> None:
        units = units_of(item_with_variations())  # the capture has no SKU anywhere
        assert [u.key for u in units] == [None] * 4

    def test_a_variation_without_an_id_is_skipped_and_ids_are_not_repeated(self) -> None:
        body = item_with_variations()
        body["variations"][0]["id"] = None
        body["variations"][1]["id"] = body["variations"][2]["id"]
        assert [u.variation_id for u in units_of(body)] == [175550253197, 175550253198]


class TestResolve:
    def test_exactly_one_product_links_by_seller_sku(self) -> None:
        unit = only_unit(sample_item("MLA882393030"))
        suggestion = links.resolve(unit, {"6932391923412": [41], "355": [99]})
        assert suggestion == links.Suggestion("linked", 41, "6932391923412", SKU_ATTR, (41,))

    def test_fallback_to_the_custom_field_links_when_there_is_no_seller_sku(self) -> None:
        unit = only_unit(drop_seller_sku(bulk_item("MLA934406852")))  # real payload minus SELLER_SKU
        suggestion = links.resolve(unit, {"126": [7]})
        assert (suggestion.status, suggestion.producto_item_id, suggestion.sku_field) == ("linked", 7, CUSTOM)
        assert suggestion.matched_sku == "126"

    def test_exact_match_only(self) -> None:
        body = bulk_item("MLA935110613")
        body["attributes"] = [
            {**a, "value_name": "pc-10400"} if a["id"] == "SELLER_SKU" else a for a in body["attributes"]
        ]  # real payload, one value changed
        suggestion = links.resolve(only_unit(body), {"PC-10400": [3], "pc-10400 ": [4]})
        assert suggestion.status == "unmatched"
        assert suggestion.producto_item_id is None
        assert suggestion.matched_sku == "pc-10400"

    def test_unmatched_with_a_key_keeps_the_key_that_was_not_found(self) -> None:
        suggestion = links.resolve(only_unit(sample_item("MLA882393030")), {})
        assert (suggestion.status, suggestion.matched_sku, suggestion.sku_field) == (
            "unmatched",
            "6932391923412",
            SKU_ATTR,
        )

    def test_no_key_is_unmatched_with_no_matched_sku(self) -> None:
        unit = links.resolve(units_of(item_with_variations())[0], {"126": [7]})
        assert (unit.status, unit.matched_sku, unit.sku_field, unit.producto_item_id) == ("unmatched", None, None, None)

    def test_two_products_sharing_the_codigo_is_a_conflict_that_picks_none(self) -> None:
        unit = only_unit(drop_seller_sku(bulk_item("MLA934406852")))
        suggestion = links.resolve(unit, {"126": [9, 5]})
        assert suggestion.status == "conflict"
        assert suggestion.producto_item_id is None
        assert suggestion.candidates == (5, 9)

    def test_two_publications_with_one_sku_link_to_the_same_product(self) -> None:
        index = {"6932391923412": [41]}
        first = links.resolve(only_unit(sample_item("MLA874027718")), index)
        second = links.resolve(only_unit(sample_item("MLA882393030")), index)
        assert (first.status, first.producto_item_id) == ("linked", 41)
        assert (second.status, second.producto_item_id) == ("linked", 41)

    def test_the_same_product_listed_twice_is_not_a_conflict(self) -> None:
        suggestion = links.resolve(only_unit(sample_item("MLA882393030")), {"6932391923412": [41, 41]})
        assert (suggestion.status, suggestion.producto_item_id) == ("linked", 41)


class TestCodigosNeeded:
    def test_only_keys_that_exist_are_looked_up_once(self) -> None:
        body = item_with_variations()
        body["seller_custom_field"] = "126"
        body["variations"][0]["seller_custom_field"] = "355"
        assert links.keys_of(units_of(body)) == ["126", "355"]
        assert links.keys_of(units_of(item_with_variations())) == []
