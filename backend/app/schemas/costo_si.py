"""The costo SI column shown next to the list cost (sell-in-costo-si T3 PR 2). Built by
`app.services.costo_si.columna.CostoSiMarkups`; read by `app.services.costo_si.lote`."""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class CostoSiPayload(BaseModel):
    """A product's current costo SI, display only (no other number uses it yet).

    `costo` is in `moneda`, the product's cost currency (owner L18), never converted for display. `fuente` is
    'costo_si', or 'lista' when the product has no costo SI and its list cost stands in (Q1). `desde` is the date of
    the costo SI step in force (None for a list cost or a combo). `costo_ars` is that cost in pesos at `tipo_cambio`
    (USD only), None without a rate: never the USD number as pesos.

    `markups` uses the SAME keys as the product's main markups (`PPP_KEY_*`, `ppp_key_*()` in
    `app.services.costo_ppp_service`), each computed from the same `limpio` on `costo_ars`; empty without pesos.

    The field that carries it is always named `costo_si`, so the MCP strips it without `productos.ver_costos` (C12).
    """

    costo: float
    moneda: str
    fuente: str
    desde: Optional[date] = None
    tipo_cambio: Optional[float] = None
    costo_ars: Optional[float] = None
    markups: dict[str, float] = Field(default_factory=dict)
