"""Seller promotions parser and mapper, over the captured `/seller-promotions/items/{id}?app_version=v2`."""

from __future__ import annotations

import copy

import pytest

from app.services.ml_publications.canonical import canonical_hash
from app.services.ml_publications.diff import array_keys_for, diff
from app.services.ml_publications.parsers.seller_promotions import map_seller_promotions, parse_seller_promotions
from app.services.ml_publications.parsers.subresource import MalformedSubResource
from tests.services.ml_publications.conftest import subresource_body, subresource_call

STARTED = "promotions_started_MLA2146576013"  # 1 started + 6 candidates, PRICE_DISCOUNT candidate without id
CANDIDATES_ONLY = "promotions_MLA874027718"  # 8 candidates, no started


def test_200_list_is_ok_and_kept_unchanged():
    body = subresource_body("promotions", STARTED)
    parsed = parse_seller_promotions(200, body)
    assert (parsed.state, parsed.status, parsed.error_body) == ("ok", 200, None)
    assert parsed.body == body


def test_captured_404_is_not_found():
    call = subresource_call("promotions", "promotions_unknown")
    parsed = parse_seller_promotions(call["status"], call["body"])
    assert (parsed.state, parsed.body, parsed.error_body) == ("not_found", None, call["body"])


def test_empty_list_is_a_valid_state_real_payload_all_entries_removed():
    body = subresource_body("promotions", STARTED)
    body.clear()
    assert parse_seller_promotions(200, body).state == "ok"
    assert map_seller_promotions(body) == {"candidate_count": 0, "started_count": 0, "started_promotion_keys": []}


@pytest.mark.parametrize("bad", [{}, "x", [1], [{"type": "DEAL"}], [{"status": "started"}]])
def test_200_with_an_unexpected_shape_is_malformed(bad):
    with pytest.raises(MalformedSubResource):
        parse_seller_promotions(200, bad)


def test_started_item_counts_and_keys():
    typed = map_seller_promotions(subresource_body("promotions", STARTED))
    assert typed == {"candidate_count": 6, "started_count": 1, "started_promotion_keys": ["C-MLA1669550"]}


def test_candidates_only_item():
    typed = map_seller_promotions(subresource_body("promotions", CANDIDATES_ONLY))
    assert typed == {"candidate_count": 8, "started_count": 0, "started_promotion_keys": []}


def test_a_started_price_discount_is_keyed_by_type_real_payload_one_field_changed():
    body = subresource_body("promotions", STARTED)
    next(p for p in body if "id" not in p)["status"] = "started"
    typed = map_seller_promotions(body)
    assert typed["started_promotion_keys"] == ["C-MLA1669550", "PRICE_DISCOUNT"]
    assert (typed["started_count"], typed["candidate_count"]) == (2, 5)


def test_other_statuses_are_neither_candidate_nor_started_real_payload_one_field_changed():
    body = subresource_body("promotions", STARTED)
    body[0]["status"] = "finished"
    typed = map_seller_promotions(body)
    assert (typed["started_count"], typed["candidate_count"], typed["started_promotion_keys"]) == (0, 6, [])


def test_diff_reports_only_the_changed_entry_keyed_by_id_or_type():
    keys = array_keys_for("promotions")
    old = subresource_body("promotions", STARTED)
    new = copy.deepcopy(old)
    next(p for p in new if p.get("id") == "C-MLA1664342")["status"] = "started"
    next(p for p in new if "id" not in p)["suggested_discounted_price"] = 1.0
    new.reverse()
    changes = diff(old, new, keys)
    assert sorted(c.path for c in changes) == ["[C-MLA1664342].status", "[PRICE_DISCOUNT].suggested_discounted_price"]
    assert "" not in {c.path for c in changes}  # never the whole-list fallback


def test_diff_reports_a_removed_promotion_at_its_element_path_real_payload_one_entry_removed():
    keys = array_keys_for("promotions")
    old = subresource_body("promotions", STARTED)
    new = [p for p in old if p.get("id") != "C-MLA1692774"]
    assert [(c.path, c.op) for c in diff(old, new, keys)] == [("[C-MLA1692774]", "remove")]


def test_reordering_promotions_is_not_a_change():
    keys = array_keys_for("promotions")
    old = subresource_body("promotions", STARTED)
    new = list(reversed(old))
    assert canonical_hash(old, keys) == canonical_hash(new, keys)
    assert diff(old, new, keys) == []
