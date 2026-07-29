"""
Schemas Pydantic para PPP (precio ponderado promedio / ERP weighted-average cost).
"""

from pydantic import BaseModel, Field
from datetime import date


class PppPayload(BaseModel):
    """Informational ERP weighted-average cost (PPP) and its derived markups.

    Display-only: never persisted, never filterable, never a substitute for
    `costo`. `costo` is expressed in `moneda`, which is derived from the
    resolved PPP source row's OWN `curr_id` (see
    `app.services.costo_ppp_service._moneda_from_curr_id`) — it is
    INDEPENDENT of `producto_erp.moneda_costo` and CAN differ from it (a
    product costed in ARS can have a USD-denominated PPP row in the ERP's
    main cost list, and vice versa; nothing keeps the two in sync). `costo`
    is NEVER converted for display: a historical weighted-average cost built
    from purchases at many different historical exchange rates cannot be
    meaningfully reconstructed by dividing by today's rate. `fecha` is the
    source row's `iclh_cd` and MUST always be rendered alongside every PPP
    figure, regardless of age.

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
