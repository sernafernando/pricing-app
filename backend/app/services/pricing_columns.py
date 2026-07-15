"""Centralized pricelist_id <-> ProductoPricing column mapping.

This module is the single source of truth for the mapping between MercadoLibre
`pricelist_id` values, the number of installments ("cuotas") they represent,
and the `ProductoPricing` column ("campo_precio") each one writes/reads.

It was extracted (SDD promo-price-propagation, slice 1) from ~6 inline
duplicate copies previously living in
`backend/app/api/endpoints/productos_listing.py`. This is a pure refactor:
values are unchanged from the inline copies they replace.
"""

from typing import Optional

# Web (non-PVP) pricelist ids -> ProductoPricing column ("campo_precio").
# 4 = clasica -> precio_lista_ml; 17/14/13/23 = 3/6/9/12 cuotas.
PRICELIST_TO_CAMPO: dict[int, str] = {
    4: "precio_lista_ml",
    17: "precio_3_cuotas",
    14: "precio_6_cuotas",
    13: "precio_9_cuotas",
    23: "precio_12_cuotas",
}

# PVP pricelist ids -> ProductoPricing column ("campo_precio").
PVP_PRICELIST_TO_CAMPO: dict[int, str] = {
    12: "precio_pvp",
    18: "precio_pvp_3_cuotas",
    19: "precio_pvp_6_cuotas",
    20: "precio_pvp_9_cuotas",
    21: "precio_pvp_12_cuotas",
}

# PVP pricelist id -> equivalent "web" (non-PVP) pricelist id, used to resolve
# commission-base lookups for PVP prices (they share the web commission rules).
PVP_TO_WEB_PRICELIST: dict[int, int] = {
    12: 4,
    18: 17,
    19: 14,
    20: 13,
    21: 23,
}

# Web (non-PVP) pricelist id -> number of installments ("cuotas").
# Clasica (4) has no entry here (it isn't a cuota).
CUOTAS_BY_PRICELIST: dict[int, int] = {17: 3, 14: 6, 13: 9, 23: 12}

# Ordered list of the classic + cuota pricelist ids, in the canonical order
# used by the listing endpoint's per-lista price lookup loop.
PRICELIST_IDS_CLASICA_Y_CUOTAS: list[int] = [4, 17, 14, 13, 23]


def campo_for_pricelist(pricelist_id: int) -> Optional[str]:
    """Return the ProductoPricing column name for a given pricelist_id.

    Covers both the "web" (clasica/cuotas) and PVP pricelist ids. Returns
    None if the pricelist_id is not recognized.
    """
    if pricelist_id in PRICELIST_TO_CAMPO:
        return PRICELIST_TO_CAMPO[pricelist_id]
    return PVP_PRICELIST_TO_CAMPO.get(pricelist_id)


def resolve_pvp_to_web(pricelist_id: int) -> int:
    """Resolve a PVP pricelist_id to its equivalent web pricelist_id.

    Non-PVP ids (or unrecognized ids) are returned unchanged.
    """
    return PVP_TO_WEB_PRICELIST.get(pricelist_id, pricelist_id)


def cuotas_for_pricelist(pricelist_id: int) -> Optional[int]:
    """Return the number of installments for a given (web) pricelist_id.

    Returns None for clasica (4) or unrecognized ids.
    """
    return CUOTAS_BY_PRICELIST.get(pricelist_id)
