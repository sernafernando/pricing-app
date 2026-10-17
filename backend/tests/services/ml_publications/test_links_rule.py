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


def with_sku(body: dict, sku: str) -> dict:
    """Real payload with its SELLER_SKU value changed (one field)."""
    body["attributes"] = [{**a, "value_name": sku} if a["id"] == "SELLER_SKU" else a for a in body["attributes"]]
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

    def test_a_blank_value_counts_as_absent(self) -> None:
        assert links.sku_key("   ", "126") == ("126", CUSTOM)
        assert links.sku_key("\t", " ") == (None, None)

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

    def test_an_exact_codigo_wins_over_codigos_that_only_match_after_normalization(self) -> None:
        unit = only_unit(with_sku(bulk_item("MLA935110613"), "pc-10400"))
        suggestion = links.resolve(unit, {"pc-10400": [2], "PC-10400": [3], "pc-10400 ": [4]})
        assert (suggestion.status, suggestion.producto_item_id, suggestion.rule) == ("linked", 2, "codigo")
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


class TestNormalizedAndItemIdRules:
    """Real SKU shapes measured in production: case, spaces and separators differ from `codigo`, and many
    SKUs carry the product's own `item_id` (a short number) instead of its `codigo`."""

    def test_normalize_trims_upper_cases_and_strips_spaces_hyphens_dots_and_slashes(self) -> None:
        assert links.normalize_sku(" pc-10.400/b x ") == "PC10400BX"
        assert links.normalize_sku("\tab\n") == "AB"

    def test_upper_casing_never_expands_a_character_like_postgres_upper(self) -> None:
        # Python upper-cases "ß" to "SS"; Postgres upper() keeps "ß". The SQL prefilter must see the same form.
        assert links.normalize_sku("straße-1") == "STRAßE1"
        assert links.normalize_sku("ǆ") == "Ǆ"  # a one-character upper case is still applied

    def test_a_no_break_space_is_a_separator(self) -> None:
        # The explicit separator set (shared with the SQL prefilter) includes the no-break space.
        assert links.normalize_sku("PC\u00a010400") == "PC10400"

    def test_case_and_separators_do_not_prevent_a_codigo_match(self) -> None:
        unit = only_unit(with_sku(bulk_item("MLA935110613"), " pc 10400 "))
        suggestion = links.resolve(unit, {"PC-10400": [3]})
        assert (suggestion.status, suggestion.producto_item_id, suggestion.rule) == ("linked", 3, "codigo_normalized")
        assert suggestion.matched_sku == " pc 10400 "  # the SKU is stored as ML sent it

    def test_several_products_matching_after_normalization_is_a_conflict(self) -> None:
        unit = only_unit(with_sku(bulk_item("MLA935110613"), "pc-10400"))
        suggestion = links.resolve(unit, {"PC-10400": [3], "pc-10400 ": [4]})
        assert (suggestion.status, suggestion.producto_item_id, suggestion.candidates) == ("conflict", None, (3, 4))

    def test_a_numeric_sku_equal_to_a_product_item_id_links_when_no_codigo_matches(self) -> None:
        unit = only_unit(drop_seller_sku(bulk_item("MLA934406852")))  # seller_custom_field "126"
        suggestion = links.resolve(unit, {}, frozenset({126}))
        assert (suggestion.status, suggestion.producto_item_id, suggestion.rule) == ("linked", 126, "item_id")
        assert (suggestion.matched_sku, suggestion.sku_field, suggestion.candidates) == ("126", CUSTOM, (126,))

    def test_a_codigo_match_always_wins_over_the_item_id(self) -> None:
        unit = only_unit(drop_seller_sku(bulk_item("MLA934406852")))
        suggestion = links.resolve(unit, {"126": [7]}, frozenset({126}))
        assert (suggestion.status, suggestion.producto_item_id, suggestion.rule) == ("linked", 7, "codigo")

    def test_a_codigo_conflict_is_never_settled_by_the_item_id(self) -> None:
        unit = only_unit(drop_seller_sku(bulk_item("MLA934406852")))
        suggestion = links.resolve(unit, {"126": [7, 8]}, frozenset({126}))
        assert (suggestion.status, suggestion.producto_item_id) == ("conflict", None)

    def test_a_numeric_sku_with_no_such_product_is_unmatched(self) -> None:
        unit = only_unit(drop_seller_sku(bulk_item("MLA934406852")))
        suggestion = links.resolve(unit, {}, frozenset({127}))
        assert (suggestion.status, suggestion.matched_sku) == ("unmatched", "126")

    def test_sku_zero_or_blank_after_normalization_never_matches(self) -> None:
        for sku in ("0", " 0 ", "-", " / "):
            unit = only_unit(with_sku(bulk_item("MLA935110613"), sku))
            suggestion = links.resolve(unit, {sku: [3], "0": [4]}, frozenset({0}))
            assert (suggestion.status, suggestion.producto_item_id, suggestion.candidates) == ("unmatched", None, ())

    def test_policy_a_plain_number_equal_to_an_item_id_links_whatever_the_seller_meant(self) -> None:
        """The rule cannot tell a seller who typed our id from one whose own code happens to equal it; it links.
        Measured 2026-10-17: of 307 such units the ERP publication map agreed on 303, disagreed on 0."""
        unit = only_unit(with_sku(bulk_item("MLA935110613"), "126"))
        suggestion = links.resolve(unit, {}, frozenset({126}))
        assert (suggestion.status, suggestion.producto_item_id, suggestion.rule) == ("linked", 126, "item_id")

    def test_policy_a_leading_zero_or_ean_length_number_never_links_by_item_id(self) -> None:
        for sku in ("0126", "7798123456789"):  # EAN-like codes: never our ids, whatever the catalog holds
            unit = only_unit(with_sku(bulk_item("MLA935110613"), sku))
            suggestion = links.resolve(unit, {}, frozenset({126, 7798123456789}))
            assert (suggestion.status, suggestion.producto_item_id) == ("unmatched", None), sku

    def test_only_a_canonical_number_is_an_item_id(self) -> None:
        assert links.item_id_of("126") == 126
        assert links.item_id_of("0126") is None  # leading zero: an EAN-like code, not our id
        assert links.item_id_of("0") is None
        assert links.item_id_of("12A") is None
        assert links.item_id_of("99999999999") is None  # beyond `productos_erp.item_id` (integer)


class TestBlankSellerSku:
    def test_a_blank_seller_sku_falls_back_to_the_custom_field_and_links_by_it(self) -> None:
        body = with_sku(bulk_item("MLA934406852"), "   ")  # real payload; its seller_custom_field is "126"
        unit = only_unit(body)
        assert (unit.key, unit.sku_field) == ("126", CUSTOM)
        suggestion = links.resolve(unit, {"126": [7]})
        assert (suggestion.status, suggestion.producto_item_id, suggestion.sku_field) == ("linked", 7, CUSTOM)
        assert suggestion.matched_sku == "126"

    def test_a_variation_with_a_blank_seller_sku_uses_its_custom_field(self) -> None:
        body = item_with_variations()
        body["variations"][0]["attributes"] = [{"id": "SELLER_SKU", "value_id": None, "value_name": "  "}]
        body["variations"][0]["seller_custom_field"] = "355"
        units = {u.variation_id: u for u in units_of(body)}
        assert (units[175550253195].key, units[175550253195].sku_field) == ("355", CUSTOM)


class TestCodigosNeeded:
    def test_only_keys_that_exist_are_looked_up_once(self) -> None:
        body = item_with_variations()
        body["seller_custom_field"] = "126"
        body["variations"][0]["seller_custom_field"] = "355"
        assert links.keys_of(units_of(body)) == ["126", "355"]
        assert links.keys_of(units_of(item_with_variations())) == []
