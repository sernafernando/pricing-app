"""Path-level diff engine (design D6/D7). Inputs are real captures."""

from __future__ import annotations

import copy

from app.services.ml_publications.diff import MISSING, Change, array_keys_for, diff
from tests.services.ml_publications.conftest import bulk_item, keyed_sample, load_fixture, ITEM_WITH_VARIATIONS


def _by_path(changes):
    return {c.path: c for c in changes}


def test_identical_payload_returns_empty_list():
    item = bulk_item("MLA935110613")
    assert diff(item, copy.deepcopy(item), {}) == []


def test_single_field_replace_real_payload_one_field_changed():
    item = bulk_item("MLA935110613")
    new = copy.deepcopy(item)
    new["title"] = "Another title"
    assert diff(item, new, {}) == [Change("title", "replace", item["title"], "Another title")]


def test_status_quantity_and_sub_status_change_real_payload_three_fields_changed():
    item = bulk_item("MLA935110613")
    new = copy.deepcopy(item)
    new["status"] = "active"
    new["available_quantity"] = 10
    new["sub_status"] = []
    changes = _by_path(diff(item, new, {}))
    assert changes["status"] == Change("status", "replace", "paused", "active")
    assert changes["available_quantity"] == Change("available_quantity", "replace", 0, 10)
    # sub_status is a scalar set: the removal is reported at the member path under `sub_status`.
    assert changes["sub_status[=out_of_stock]"] == Change(
        "sub_status[=out_of_stock]", "remove", "out_of_stock", MISSING
    )
    assert set(changes) == {"status", "available_quantity", "sub_status[=out_of_stock]"}


def test_one_attribute_change_yields_only_that_attributes_subpaths_real_payload_one_field_changed():
    item = bulk_item("MLA935110613")
    new = copy.deepcopy(item)
    brand = next(a for a in new["attributes"] if a["id"] == "BRAND")
    brand["value_name"] = "Other"
    changes = diff(item, new, {})
    assert [c.path for c in changes] == ["attributes[BRAND].value_name"]
    assert changes[0].old == "Marvo" and changes[0].new == "Other"


def test_attributes_reorder_is_not_a_change_real_payload_reordered():
    item = bulk_item("MLA935110613")
    new = copy.deepcopy(item)
    new["attributes"].reverse()
    new["tags"].reverse()
    assert diff(item, new, {}) == []


def test_tag_added_reports_only_the_addition_real_payload_one_field_changed():
    item = bulk_item("MLA935110613")
    new = copy.deepcopy(item)
    new["tags"].append("brand_new_tag")
    assert diff(item, new, {}) == [Change("tags[=brand_new_tag]", "add", MISSING, "brand_new_tag")]


def test_keyed_element_added_and_removed_at_element_path_real_payload_one_element_changed():
    item = bulk_item("MLA935110613")
    removed = copy.deepcopy(item)
    gone = removed["attributes"].pop(0)
    changes = diff(item, removed, {})
    assert changes == [Change(f"attributes[{gone['id']}]", "remove", gone, MISSING)]
    added = diff(removed, item, {})
    assert added == [Change(f"attributes[{gone['id']}]", "add", MISSING, gone)]


def test_array_with_null_ids_falls_back_to_one_whole_array_replace_real_payload_one_field_changed():
    item = bulk_item("MLA935110613")
    attr = next(a for a in item["attributes"] if a["id"] == "SELLER_SKU")
    assert all(v.get("id") is None for v in attr["values"])
    new = copy.deepcopy(item)
    next(a for a in new["attributes"] if a["id"] == "SELLER_SKU")["values"][0]["name"] = "changed"
    changes = diff(item, new, {})
    assert [c.path for c in changes] == ["attributes[SELLER_SKU].values"]
    assert changes[0].op == "replace" and changes[0].old == attr["values"]


def test_absent_vs_null_encoding_real_payload_fields_removed_or_nulled():
    item = bulk_item("MLA935110613")
    removed = copy.deepcopy(item)
    del removed["warranty"]
    assert diff(item, removed, {}) == [Change("warranty", "remove", item["warranty"], MISSING)]
    back = diff(removed, item, {})
    assert back == [Change("warranty", "add", MISSING, item["warranty"])]
    assert back[0].old is MISSING
    nulled = copy.deepcopy(item)
    nulled["warranty"] = None
    to_null = diff(item, nulled, {})
    assert to_null == [Change("warranty", "replace", item["warranty"], None)]
    assert to_null[0].new is None


def test_variation_disappearance_reported_under_variations_key_real_payload_one_variation_removed():
    item = load_fixture(ITEM_WITH_VARIATIONS)
    new = copy.deepcopy(item)
    gone = new["variations"].pop(1)
    changes = diff(item, new, {})
    assert changes == [Change(f"variations[{gone['id']}]", "remove", gone, MISSING)]


def test_variation_field_change_logs_only_that_subpath_real_payload_one_field_changed():
    item = load_fixture(ITEM_WITH_VARIATIONS)
    new = copy.deepcopy(item)
    var = new["variations"][2]
    var["seller_custom_field"] = "ABC-1"
    changes = diff(item, new, {})
    assert [c.path for c in changes] == [f"variations[{var['id']}].seller_custom_field"]


def test_large_integer_ids_are_diffed_exactly_real_payload_one_field_changed():
    item = bulk_item("MLA935110613")
    new = copy.deepcopy(item)
    new["family_id"] = item["family_id"] + 1
    assert diff(item, new, {}) == [Change("family_id", "replace", 7695306917964170, 7695306917964171)]


def test_promotions_override_keys_by_id_then_type_real_payload_one_field_changed():
    promos = keyed_sample("promotions_started_MLA2146576013")
    assert any("id" not in p for p in promos)  # PRICE_DISCOUNT carries no id
    new = copy.deepcopy(promos)
    price_discount = next(p for p in new if "id" not in p)
    price_discount["status"] = "started"
    new.reverse()
    changes = diff(promos, new, array_keys_for("promotions"))
    assert [c.path for c in changes] == ["[PRICE_DISCOUNT].status"]


def test_visits_override_keys_results_by_date_real_payload_one_day_added():
    visits = keyed_sample("visits_MLA874027718")
    new = copy.deepcopy(visits)
    added = new["results"].pop()
    new["results"].reverse()
    changes = diff(visits, new, array_keys_for("visits"))
    assert [c.path for c in changes] == [f"results[{added['date']}]"]
    assert changes[0].op == "remove"


def test_key_characters_in_paths_are_escaped():
    old = {"a.b": {"c[d]": 1}}
    new = {"a.b": {"c[d]": 2}}
    assert [c.path for c in diff(old, new, {})] == [r"a\.b.c\[d\]"]


def test_type_change_is_a_replace_at_the_path():
    assert diff({"x": {"a": 1}}, {"x": [1]}, {}) == [Change("x", "replace", {"a": 1}, [1])]
