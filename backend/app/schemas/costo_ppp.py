"""
Schemas Pydantic para PPP (precio ponderado promedio / ERP weighted-average cost).
"""

from pydantic import BaseModel, Field
from datetime import date


class PppPayload(BaseModel):
    """Informational ERP weighted-average cost (PPP) and its derived markups.

    Display-only: never persisted, never filterable, never a substitute for
    `costo`. `costo` is ARS already (no currency conversion applies). `fecha`
    is the source row's `it_cd` and MUST always be rendered alongside every
    PPP figure, regardless of age.

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
    fecha: date
    markups: dict[str, float] = Field(default_factory=dict)
