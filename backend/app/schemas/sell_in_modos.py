"""A product's sell-in cost modes: the history, and the preview and confirm of a change; see
`app.services.sell_in.modos`."""

from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

    modo: Modo
    desde: date  # before today only with `sell_in.costo_retroactivo`
    # Only and always for `manual` (D6): the typed quantity and unit cost in ARS (the design's "Cantidad" and "Costo
    # unitario"). The server freezes the product's own cost; each unit then carries that cost minus this one.
    cantidad: Optional[int] = Field(default=None, gt=0, le=2**31 - 1)  # the column's integer
    costo_unit: Optional[Decimal] = Field(default=None, gt=0, max_digits=18, decimal_places=6)

    @model_validator(mode="after")
    def _manual(self) -> "ModoIn":
        con_valores = self.cantidad is not None or self.costo_unit is not None
        if self.modo == "manual" and (self.cantidad is None or self.costo_unit is None):
            raise ValueError("A manual cost mode needs cantidad and costo_unit")
        if self.modo != "manual" and con_valores:
            raise ValueError("Only a manual cost mode takes cantidad and costo_unit")
        return self


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
    costo_base_unit: Optional[Decimal] = None  # `manual`: the product's cost in ARS frozen on the row (D6)


# Not `manual`: a preselected manual mode would still need its quantity and cost typed per product.
ModoPorDefecto = Literal["fifo", "ponderado", "ultimo"]


class ModoPorDefectoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modo: ModoPorDefecto


class ModoPorDefectoOut(BaseModel):
    # The mode the panel's selector opens preselected with; it never changes costing (no row: FIFO in the engine).
    modo: ModoPorDefecto
