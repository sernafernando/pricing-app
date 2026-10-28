"""Internal publication-type tokens → web/PVP pricelist ids (PARA GANAR alcance)."""

from __future__ import annotations

from app.services.pricing_columns import (
    PRICELIST_TO_CAMPO,
    PVP_PRICELIST_TO_CAMPO,
    resolve_pvp_to_web,
)

# Web pricelist_id that represents each internal tipo.
TIPO_TO_WEB_PRICELIST: dict[str, int] = {
    "clasica": 4,
    "3": 17,
    "6": 14,
    "9": 13,
    "12": 23,
}


def pricelists_for_tipos(tipos: list[str]) -> list[int]:
    """Map internal tipo tokens → web + PVP pricelist ids that share that bucket."""
    web_ids = {TIPO_TO_WEB_PRICELIST[t] for t in tipos if t in TIPO_TO_WEB_PRICELIST}
    if not web_ids:
        return []
    known = set(PRICELIST_TO_CAMPO) | set(PVP_PRICELIST_TO_CAMPO)
    return sorted(pl for pl in known if resolve_pvp_to_web(pl) in web_ids)
