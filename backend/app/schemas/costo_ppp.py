"""
Schemas Pydantic para PPP (precio ponderado promedio / ERP weighted-average cost).
"""

from pydantic import BaseModel, Field
from datetime import date


class PppPayload(BaseModel):
    """Informational ERP weighted-average cost (PPP) and its derived markups.

    Display-only: never persisted, never filterable, never a substitute for
    `costo`. `costo` is ARS already (no currency conversion applies) and is
    what every markup in `markups` is derived from — nothing recomputes
    markups from `costo_display`. `fecha` is the source row's `it_cd` and
    MUST always be rendered alongside every PPP figure, regardless of age.

    `costo_display`/`costo_display_moneda` are a DISPLAY-ONLY mirror of
    `costo` in the SAME currency as the product's list cost
    (`producto_erp.moneda_costo`), so the two figures shown together on
    screen are directly comparable without the frontend needing the exchange
    rate. When the product's list cost is ARS, or the exchange rate could not
    be resolved, `costo_display == costo` and `costo_display_moneda == "ARS"`
    — never a `"USD"` label on a figure that was not actually converted.

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
    costo_display: float
    costo_display_moneda: str
    fecha: date
    markups: dict[str, float] = Field(default_factory=dict)
