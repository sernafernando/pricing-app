"""
Schemas Pydantic para PPP (precio ponderado promedio / ERP weighted-average cost).
"""

from pydantic import BaseModel, Field
from datetime import date


class PppPayload(BaseModel):
    """Informational ERP weighted-average cost (PPP) and its derived markups.

    Display-only: never persisted, never filterable, never a substitute for
    `costo`. `costo` is expressed in `moneda`, which is `producto_erp.moneda_costo`
    (the product's own list-cost currency) — verified against production data
    (2026-07-29, zero mismatches across 3215 products) to match the PPP
    source row's currency BY CONSTRUCTION: both are read from the SAME row
    of the SAME main cost list (`coslis_id=1`). See
    `app.services.costo_ppp_service` module docstring for the full evidence
    and rationale — do not derive `moneda` independently from the source row
    itself; it is passed in by the caller. `costo` is NEVER converted for
    display: a historical weighted-average cost built from purchases at many
    different historical exchange rates cannot be meaningfully reconstructed
    by dividing by today's rate — it is already in the correct currency
    without conversion. `fecha` is the source row's `iclh_cd` and MUST always
    be rendered alongside every PPP figure, regardless of age.

    Every markup in `markups` IS derived from `costo` — after an internal ARS
    conversion applied ONLY for the markup formula (`limpio` is always ARS),
    never surfaced back through this schema. See
    `app.services.costo_ppp_service.PppMarkups` for that conversion.

    The `markups` keys are NOT documented here on purpose. They are defined —
    and built — by `app.services.costo_ppp_service`: see its module docstring
    for the canonical vocabulary, and use its `PPP_KEY_*` constants and
    `ppp_key_*()` helpers instead of writing key strings by hand.

    This docstring used to carry its own copy of that list and the two drifted
    apart, leaving stale keys documented on the very file a frontend developer
    opens first. A wrong key does not raise: it renders nothing. One source of
    truth only.
    """

    costo: float
    moneda: str
    fecha: date
    markups: dict[str, float] = Field(default_factory=dict)
