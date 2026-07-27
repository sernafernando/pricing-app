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

    Key vocabulary for `markups` (consumed as-is by the frontend, see PR2/PR3):
        mejor_oferta          — best-offer markup (raw decimal ratio)
        rebate                — rebate markup (percent)
        pvp                   — PVP clásica markup (percent)
        calculado_3_cuotas    — cuotas clásica markup, 3 installments (percent)
        calculado_6_cuotas    — cuotas clásica markup, 6 installments (percent)
        calculado_9_cuotas    — cuotas clásica markup, 9 installments (percent)
        calculado_12_cuotas   — cuotas clásica markup, 12 installments (percent)
        calculado_pvp_pvp_3_cuotas / _6_cuotas / _9_cuotas / _12_cuotas
                               — cuotas PVP markup per installment (percent)
        calculado_variant_pvp / _pvp_3_cuotas / _6_cuotas / _9_cuotas / _12_cuotas
                               — listing-endpoint PVP-variant markup per
                                 installment (percent)
        cuota_ml_3 / _6 / _9 / _12
                               — Tienda endpoint cuotas markup per
                                 installment (percent)
    """

    costo: float
    fecha: date
    markups: dict[str, float] = Field(default_factory=dict)
