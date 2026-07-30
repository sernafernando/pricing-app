"""
Schemas Pydantic para PPP (precio ponderado promedio / ERP weighted-average cost).
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field
from datetime import date


class PppPayload(BaseModel):
    """Informational ERP weighted-average cost (PPP) and its derived markups.

    Display-only: never persisted, never filterable, never a substitute for
    `costo`. `costo` is expressed in `moneda` (`producto_erp.moneda_costo`,
    passed in by the caller — never derived independently) and NEVER
    converted for display, EXCEPT for a recovered USD-footprint row (see
    `app.services.costo_ppp_service` module docstring's "Recovering USD
    footprints" section), which IS converted to `moneda` at today's rate —
    that is the one deliberate exception to "never converted for display".
    `fecha` is the source row's `iclh_cd` and MUST always be rendered
    alongside every PPP figure, regardless of age.

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

    `estado` (2026-07-30): additive three-state discriminator alongside the
    pre-existing "`ppp` is `None`" no-data contract, which is UNCHANGED — a
    product with no qualifying `coslis_id=1` row still gets `ppp: null`, not
    a `PppPayload` at all. `estado` only distinguishes what a NON-null `ppp`
    means:
      - `"usable"` (default): `costo`/`fecha`/`markups` are populated and
        meaningful — the pre-existing behaviour.
      - `"fuera_de_rango"`: the row EXISTS but its scale is broken and not
        recoverable (see `costo_ppp_service`'s "Scale sanity guard" and
        "Recovering USD footprints" sections). `costo`/`moneda`/`fecha` are
        `None` and `markups` is empty — the frontend must render an explicit
        "out of range" marker, never a number, for this state.
    """

    estado: Literal["usable", "fuera_de_rango"] = "usable"
    costo: Optional[float] = None
    moneda: Optional[str] = None
    fecha: Optional[date] = None
    markups: dict[str, float] = Field(default_factory=dict)
