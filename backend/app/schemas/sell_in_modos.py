"""A product's sell-in cost modes: the history, and the preview and confirm of a change; see
`app.services.sell_in.modos`."""

from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

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


class ModoIn(BaseModel):
    # A field this change does not take (a manual quantity or cost, the origin, the user) is refused, never dropped.
    model_config = ConfigDict(extra="forbid")

    modo: Modo  # `manual` is refused here until its own slice lands
    desde: date  # before today only with `sell_in.costo_retroactivo`


class ModoConfirmarIn(ModoIn):
    huella: str = Field(min_length=64, max_length=64)  # the preview's fingerprint


class VistaPreviaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ventas_cambian: int  # recorded sales whose sell in changes
    diferencia_ars: Decimal  # their new sell in minus the current one (negative: less sell in)
    unidades_restantes: int  # the units the next sale draws from, after the change (from `desde` when to come)
    descuento_unit: Optional[Decimal]  # their unit value; None: no unit left
    sin_asignar_antes: Decimal  # ARS the lots hold that no unit hands out (positive) or handed beyond them, today
    sin_asignar_despues: Decimal  # the same once the change governs (from `desde` when to come)
    huella: str  # send it back to confirm


class ModoPorDefectoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modo: Modo


class ModoPorDefectoOut(BaseModel):
    # The mode the panel's selector opens preselected with; it never changes costing (no row: FIFO in the engine).
    modo: Modo
