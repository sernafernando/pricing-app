"""`markup_service.product_markup`: a product reads only the publication's units linked to it (#1870)."""

from __future__ import annotations

from dataclasses import replace

from app.services.ml_publications.view.markup import REASON_OK, UnitMarkup, summarize
from app.services.ml_publications.view.markup_service import ItemMarkup, product_markup


def unit(value: float) -> UnitMarkup:
    return UnitMarkup(value, REASON_OK, None, None, None, None, None)


def item(*units: tuple[float, int]) -> ItemMarkup:
    markup = summarize([unit(value) for value, _ in units])
    return ItemMarkup(markup, None, tuple(range(len(units))), tuple(product for _, product in units))


def test_a_product_reads_only_its_own_units() -> None:
    both = item((20.0, 70), (-19.0, 71))
    assert (product_markup(both, 70).worst, product_markup(both, 70).any_negative) == (20.0, False)
    assert (product_markup(both, 71).worst, product_markup(both, 71).any_negative) == (-19.0, True)


def test_every_unit_of_the_product_is_the_publication_s_own_markup_untouched() -> None:
    whole = item((5.0, 70), (7.0, 70))
    adjusted = replace(whole, markup=replace(whole.markup, worst=-1.0))  # e.g. Ads applied to the summary
    assert product_markup(adjusted, 70) is adjusted.markup


def test_a_product_with_no_unit_of_its_own_has_no_value_never_the_sibling_s() -> None:
    # an item-level link to 78 whose only variation is 79
    other = item((-30.0, 79))
    got = product_markup(other, 78)
    assert (got.worst, got.any_negative) == (None, False)
