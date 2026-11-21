"""The costo SI column shown next to the list cost (sell-in-costo-si T3 PR 2). Built by
`app.services.costo_si.columna.payload`; read by `app.services.costo_si.lote`."""

from datetime import date
from typing import Optional

from pydantic import BaseModel


class CostoSiPayload(BaseModel):
    """A product's current costo SI, display only (no other number uses it yet).

    `costo` is in `moneda`, the product's cost currency (owner L18), never converted for display. `fuente` is
    'costo_si', or 'lista' when the product has no costo SI and its list cost stands in (Q1). `desde` is the date of
    the costo SI step in force (None for a list cost or a combo). `costo_ars` is that cost in pesos at `tipo_cambio`
    (USD only, dated `tipo_cambio_fecha`), None without a rate: never the USD number as pesos.

    No markups of its own: the product's main markups are already over this cost in pesos (S13), one source.

    The field that carries it is always named `costo_si`, so the MCP strips it without `productos.ver_costos` (C12).
    """

    costo: float
    moneda: str
    fuente: str
    desde: Optional[date] = None
    tipo_cambio: Optional[float] = None
    tipo_cambio_fecha: Optional[date] = None  # that rate's own date; None without a rate
    costo_ars: Optional[float] = None
