"""Campaign -> pricelist mapping for a Mercado Libre publication (pure).

Rule (Engram #2248, verified on 16 real items against `listing_prices`): the
pricelist of a publication follows from its listing type and its installments
campaign.

* `gold_special` is the classic list (4), whatever the campaign. With the
  `pcj-co-funded` tag the installments are co-funded by ML and there is no list
  of ours for it: it is flagged `cofinanciada`.
* `gold_pro` follows the campaign: 3x -> 17, 9x -> 13, 12x -> 23, and no
  campaign -> 14 (6x installments carry neither tag nor sale term).
* Any other listing type has no list of ours: `sin_lista`.

The campaign comes from the item `tags` first (first match in tag order); the
`INSTALLMENTS_CAMPAIGN` sale term is only the fallback. SQL just extracts both
inputs; the decision lives here so it is testable without a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

PRICELIST_CLASICA = 4
PRICELIST_6X = 14

# Campaign value -> pricelist of ours. `6x_campaign` is never sent by ML (6x items
# have no campaign) but a legacy mapping used the key, so it maps like "none".
_PRICELIST_BY_CAMPAIGN: dict[str, int] = {
    "3x_campaign": 17,
    "6x_campaign": PRICELIST_6X,
    "9x_campaign": 13,
    "12x_campaign": 23,
}

# Campaigns ML really sends as an item tag.
CAMPAIGN_TAGS: tuple[str, ...] = ("3x_campaign", "9x_campaign", "12x_campaign")

CO_FUNDED_TAG = "pcj-co-funded"

REASON_OK = "ok"
REASON_COFINANCIADA = "cofinanciada"
REASON_SIN_LISTA = "sin_lista"


@dataclass(frozen=True)
class PricelistResolution:
    pricelist_id: Optional[int]
    campaign: Optional[str]
    reason: str


def _campaign_from_tags(tags: Sequence[str]) -> Optional[str]:
    for tag in tags:
        if tag in CAMPAIGN_TAGS:
            return tag
    return None


def resolve_pricelist(
    listing_type_id: Optional[str],
    tags: Sequence[str],
    sale_terms_campaign: Optional[str],
) -> PricelistResolution:
    """Resolve the pricelist of one publication from its extracted inputs."""
    tags = tags or ()
    campaign = _campaign_from_tags(tags) or sale_terms_campaign

    if listing_type_id == "gold_special":
        if CO_FUNDED_TAG in tags:
            return PricelistResolution(None, campaign, REASON_COFINANCIADA)
        return PricelistResolution(PRICELIST_CLASICA, campaign, REASON_OK)

    if listing_type_id == "gold_pro":
        if campaign is None:
            return PricelistResolution(PRICELIST_6X, None, REASON_OK)
        pricelist_id = _PRICELIST_BY_CAMPAIGN.get(campaign)
        if pricelist_id is None:
            # An installments campaign we do not know must not silently price as 6x.
            return PricelistResolution(None, campaign, REASON_SIN_LISTA)
        return PricelistResolution(pricelist_id, campaign, REASON_OK)

    return PricelistResolution(None, campaign, REASON_SIN_LISTA)
