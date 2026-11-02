"""A product's sell-in cost modes (read only); see `app.services.sell_in.modos`."""

from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict

Modo = Literal["fifo", "ponderado", "ultimo", "manual"]


class ModoProductoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    modo: Modo
    desde: date
    # Only a `manual` row: the typed quantity and unit cost, and the product's cost frozen when it was saved.
    cantidad: Optional[int]
    costo_unit: Optional[Decimal]
    costo_base_unit: Optional[Decimal]
    origen: Literal["visor", "carga"]  # 'carga': made from the sell-in load that `compra_id` names
    compra_id: Optional[int]
    usuario_id: int
    usuario_nombre: Optional[str]
    created_at: datetime


class ModosProductoOut(BaseModel):
    item_id: int
    vigente: Optional[ModoProductoOut]  # the row governing today; None: FIFO, the default
    historial: List[ModoProductoOut]  # newest `desde` first, future rows included
