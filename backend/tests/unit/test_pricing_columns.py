"""Characterization tests for app.services.pricing_columns.

These pin the pricelist_id -> column / cuotas / pvp-to-web mapping that
previously existed as ~6 inline duplicate copies inside
backend/app/api/endpoints/productos_listing.py (see lines 653-660,
890-893, 967-970, 1225-1229, 1357, 1839-1840, 2087-2091, 2327-2330 as of
the pre-refactor commit). Values here MUST match those inline copies
exactly -- this is a pure refactor with zero behavior change.
"""

from app.services import pricing_columns as pc


def test_campo_for_pricelist_clasica_y_cuotas():
    assert pc.campo_for_pricelist(4) == "precio_lista_ml"
    assert pc.campo_for_pricelist(17) == "precio_3_cuotas"
    assert pc.campo_for_pricelist(14) == "precio_6_cuotas"
    assert pc.campo_for_pricelist(13) == "precio_9_cuotas"
    assert pc.campo_for_pricelist(23) == "precio_12_cuotas"


def test_campo_for_pricelist_pvp():
    assert pc.campo_for_pricelist(12) == "precio_pvp"
    assert pc.campo_for_pricelist(18) == "precio_pvp_3_cuotas"
    assert pc.campo_for_pricelist(19) == "precio_pvp_6_cuotas"
    assert pc.campo_for_pricelist(20) == "precio_pvp_9_cuotas"
    assert pc.campo_for_pricelist(21) == "precio_pvp_12_cuotas"


def test_campo_for_pricelist_unknown_returns_none():
    assert pc.campo_for_pricelist(999) is None


def test_pvp_to_web_mapping():
    assert pc.resolve_pvp_to_web(12) == 4
    assert pc.resolve_pvp_to_web(18) == 17
    assert pc.resolve_pvp_to_web(19) == 14
    assert pc.resolve_pvp_to_web(20) == 13
    assert pc.resolve_pvp_to_web(21) == 23


def test_pvp_to_web_passthrough_for_non_pvp_ids():
    # Inline copies used dict.get(pricelist_id, pricelist_id): unknown/non-PVP
    # ids resolve to themselves.
    assert pc.resolve_pvp_to_web(4) == 4
    assert pc.resolve_pvp_to_web(17) == 17
    assert pc.resolve_pvp_to_web(999) == 999


def test_cuotas_for_pricelist():
    assert pc.cuotas_for_pricelist(17) == 3
    assert pc.cuotas_for_pricelist(14) == 6
    assert pc.cuotas_for_pricelist(13) == 9
    assert pc.cuotas_for_pricelist(23) == 12


def test_cuotas_for_pricelist_clasica_and_unknown_are_none():
    assert pc.cuotas_for_pricelist(4) is None
    assert pc.cuotas_for_pricelist(999) is None


def test_pricelist_ids_clasica_y_cuotas_order():
    # Order matters: this is the exact loop order at productos_listing.py L1357.
    assert pc.PRICELIST_IDS_CLASICA_Y_CUOTAS == [4, 17, 14, 13, 23]
