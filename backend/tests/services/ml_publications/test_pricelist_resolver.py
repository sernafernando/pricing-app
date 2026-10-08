"""Campaign -> pricelist mapping (pure), checked against the 16 captured items.

Rule source: Engram #2248, verified on real `listing_prices` data. The campaign
is read from the item `tags` first and falls back to the `INSTALLMENTS_CAMPAIGN`
sale term. Every table row below is a captured fact, not an invented one.
"""

from __future__ import annotations

import pytest

from app.services.ml_publications.pricelist_resolver import PricelistResolution, resolve_pricelist
from tests.services.ml_publications.conftest import load_fixture

LISTING_PRICES_CASES = "listing_prices_cases.json"


def test_listing_prices_fixture_has_the_sixteen_captured_cases():
    cases = load_fixture(LISTING_PRICES_CASES)["cases"]
    assert len(cases) == 16
    assert all("ours" in c and "tags" in c and "listing_type_id" in c for c in cases)


def _sale_term_campaign(case: dict):
    for term in case["sale_terms"]:
        if term["id"] == "INSTALLMENTS_CAMPAIGN":
            return term["value_name"]
    return None


def test_all_sixteen_captured_items_resolve_to_the_list_we_priced_them_with():
    for case in load_fixture(LISTING_PRICES_CASES)["cases"]:
        got = resolve_pricelist(case["listing_type_id"], case["tags"], _sale_term_campaign(case))
        assert got.pricelist_id == case["ours"]["pricelist_id"], case["item_id"]
        assert got.reason == "ok"


def test_sale_terms_alone_resolve_the_same_sixteen():
    # Same items with the tags stripped: the sale term is the fallback source.
    for case in load_fixture(LISTING_PRICES_CASES)["cases"]:
        got = resolve_pricelist(case["listing_type_id"], [], _sale_term_campaign(case))
        assert got.pricelist_id == case["ours"]["pricelist_id"], case["item_id"]


@pytest.mark.parametrize(
    "tags,sale_term,expected_list,expected_campaign",
    [
        (["content_editable", "9x_campaign"], None, 13, "9x_campaign"),  # S21.1 tag 9x
        ([], "12x_campaign", 23, "12x_campaign"),  # S21.2 sale term 12x
        (["content_editable"], None, 14, None),  # S21.3 no campaign = 6x
        (["3x_campaign"], None, 17, "3x_campaign"),
    ],
)
def test_gold_pro_campaign_to_list(tags, sale_term, expected_list, expected_campaign):
    got = resolve_pricelist("gold_pro", tags, sale_term)
    assert got == PricelistResolution(pricelist_id=expected_list, campaign=expected_campaign, reason="ok")


def test_gold_special_is_the_classic_list_4():  # S21.4
    got = resolve_pricelist("gold_special", ["content_editable"], None)
    assert got.pricelist_id == 4 and got.reason == "ok"


def test_gold_special_with_a_campaign_tag_stays_on_list_4():
    assert resolve_pricelist("gold_special", ["12x_campaign"], None).pricelist_id == 4


def test_pcj_co_funded_gold_special_has_no_list_of_ours():  # S21.5
    got = resolve_pricelist("gold_special", ["pcj-co-funded"], None)
    assert got.pricelist_id is None and got.reason == "cofinanciada"


def test_unknown_listing_type_is_sin_lista():  # S21.6
    for listing_type in ("gold_premium", "free", "bronze", None):
        got = resolve_pricelist(listing_type, [], None)
        assert got.pricelist_id is None and got.reason == "sin_lista"


def test_a_6x_campaign_value_maps_like_no_campaign():
    # ML never sends it (6x items carry no campaign), but a legacy mapping did.
    got = resolve_pricelist("gold_pro", [], "6x_campaign")
    assert got.pricelist_id == 14 and got.reason == "ok"


def test_tag_beats_sale_term():
    got = resolve_pricelist("gold_pro", ["9x_campaign"], "12x_campaign")
    assert got.pricelist_id == 13 and got.campaign == "9x_campaign"


def test_first_campaign_tag_wins_when_several_are_present():
    assert resolve_pricelist("gold_pro", ["12x_campaign", "3x_campaign"], None).pricelist_id == 23


def test_unrecognised_sale_term_campaign_is_sin_lista_not_a_silent_6x():
    got = resolve_pricelist("gold_pro", [], "15x_campaign")
    assert got.pricelist_id is None and got.reason == "sin_lista"
