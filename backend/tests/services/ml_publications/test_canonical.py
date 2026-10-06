"""Canonical form and hash (design D6). Inputs are the real MLA935110613 capture."""

from __future__ import annotations

import copy
import json

from app.services.ml_publications.canonical import canonical, canonical_hash
from tests.services.ml_publications.conftest import bulk_item


def _reversed_keys(value):
    if isinstance(value, dict):
        return {k: _reversed_keys(value[k]) for k in reversed(list(value))}
    if isinstance(value, list):
        return [_reversed_keys(v) for v in value]
    return value


def test_hash_ignores_key_order_real_payload_reordered():
    item = bulk_item("MLA935110613")
    assert canonical_hash(item, {}) == canonical_hash(_reversed_keys(item), {})


def test_hash_ignores_attributes_order_real_payload_reordered():
    item = bulk_item("MLA935110613")
    shuffled = copy.deepcopy(item)
    shuffled["attributes"].reverse()
    assert shuffled["attributes"] != item["attributes"]
    assert canonical_hash(item, {}) == canonical_hash(shuffled, {})


def test_hash_ignores_tags_order_real_payload_reordered():
    item = bulk_item("MLA935110613")
    shuffled = copy.deepcopy(item)
    shuffled["tags"].reverse()
    assert shuffled["tags"] != item["tags"]
    assert canonical_hash(item, {}) == canonical_hash(shuffled, {})


def test_hash_differs_when_one_attribute_value_changes_real_payload_one_field_changed():
    item = bulk_item("MLA935110613")
    changed = copy.deepcopy(item)
    brand = next(a for a in changed["attributes"] if a["id"] == "BRAND")
    brand["value_name"] = "Other"
    assert canonical_hash(item, {}) != canonical_hash(changed, {})


def test_hash_differs_when_a_tag_is_added_real_payload_one_field_changed():
    item = bulk_item("MLA935110613")
    changed = copy.deepcopy(item)
    changed["tags"].append("brand_new_tag")
    assert canonical_hash(item, {}) != canonical_hash(changed, {})


def test_large_family_id_survives_canonicalization_exactly():
    item = bulk_item("MLA935110613")
    form = canonical(item, {})
    assert form["family_id"] == 7695306917964170
    assert "7695306917964170" in json.dumps(form)


def test_hash_is_32_byte_digest_and_deterministic():
    item = bulk_item("MLA935110613")
    digest = canonical_hash(item, {})
    assert isinstance(digest, bytes) and len(digest) == 32
    assert digest == canonical_hash(copy.deepcopy(item), {})


def test_keyed_array_override_uses_natural_key_with_fallback():
    # Registry-style override: promotions are keyed by `id`, falling back to `type`.
    spec = {"": ("id", "type")}
    a = [{"id": "C-1", "status": "started"}, {"type": "PRICE_DISCOUNT", "status": "started"}]
    b = list(reversed(a))
    assert canonical_hash(a, spec) == canonical_hash(b, spec)


def test_array_without_usable_keys_keeps_order():
    a = {"values": [{"id": None, "name": "x"}, {"id": None, "name": "y"}]}
    b = {"values": [{"id": None, "name": "y"}, {"id": None, "name": "x"}]}
    assert canonical_hash(a, {}) != canonical_hash(b, {})
