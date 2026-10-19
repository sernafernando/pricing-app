"""Schemas of the sell-in purchases API (`/api/sell-in/compras`).

Only the shape is validated here (types and closed choices). The business
rules (quantities, totals, duplicated items, the manual split adding up, the FX
rate) are checked by the service and the split, so their errors come back as a
422 with one readable Spanish message instead of a list of field errors.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Moneda = Literal["ARS", "USD"]
Formula = Literal["proporcional", "por_unidad", "manual"]
CuentaDesde = Literal["compra", "ingreso"]
Estado = Literal["activa", "anulada"]
Aplica = Literal["si", "no", "todas"]

MOTIVO_MAX = 500  # `auditoria.comentario` is VARCHAR(500)
PEDIDOS_MAX = 50  # Compras operations per sell in; a real one carries a handful


class SellInLineaIn(BaseModel):
    item_id: int
    cantidad: int
    monto_manual: Optional[Decimal] = None
    # Unit cost in the purchase currency. When missing, the server takes the product's current cost.
    costo_base_unit: Optional[Decimal] = None


class SellInPreviewIn(BaseModel):
    moneda: Moneda
    monto_total: Decimal
    # ARS per USD. Required for a USD purchase, and to convert a product cost kept in the other currency.
    tipo_cambio: Optional[Decimal] = None
    formula: Formula = "proporcional"
    lineas: list[SellInLineaIn]


class SellInCompraCreate(SellInPreviewIn):
    fecha_compra: date
    fecha_ingreso: Optional[date] = None
    cuenta_desde: CuentaDesde = "compra"
    proveedor_id: Optional[int] = None
    # Legacy single operation: read as a one-element `pedido_compra_ids`.
    pedido_compra_id: Optional[int] = None
    # Compras operations (`pedidos_compra`) this sell in comes from: same supplier and currency.
    pedido_compra_ids: list[int] = Field(default_factory=list, max_length=PEDIDOS_MAX)
    descripcion: Optional[str] = None


class SellInAnularIn(BaseModel):
    motivo: Optional[str] = Field(default=None, max_length=MOTIVO_MAX)


class SellInPreviewLinea(BaseModel):
    item_id: int
    codigo: Optional[str]
    descripcion: Optional[str]
    cantidad: int
    costo_base_unit: Decimal
    monto_asignado: Decimal
    descuento_unit: Decimal
    costo_con_sell_in_unit: Decimal
    porcentaje: Optional[Decimal]


class SellInPreviewTotales(BaseModel):
    cantidad: int
    costo_base_total: Decimal
    monto_asignado_total: Decimal
    costo_con_sell_in_total: Decimal
    porcentaje: Optional[Decimal]


class SellInPreviewOut(BaseModel):
    moneda: Moneda
    formula: Formula
    monto_total: Decimal
    lineas: list[SellInPreviewLinea]
    totales: SellInPreviewTotales


class SellInCompraItemOut(SellInPreviewLinea):
    id: int
    unidades_consumidas: int
    unidades_restantes: int


class SellInCompraOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    proveedor_id: Optional[int]
    pedido_compra_id: Optional[int]
    pedido_compra_ids: list[int] = []
    fecha_compra: date
    fecha_ingreso: Optional[date]
    cuenta_desde: CuentaDesde
    moneda: Moneda
    monto_total: Decimal
    tipo_cambio: Optional[Decimal]
    formula: Formula
    estado: Estado
    descripcion: Optional[str]
    usuario_id: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    proveedor_nombre: Optional[str] = None
    # Whether the sell in applies, by `services.sell_in.compras.aplica_condicion` (the one rule).
    aplica: bool
    unidades_total: int
    unidades_consumidas: int
    unidades_restantes: int
    items: list[SellInCompraItemOut]


class SellInPrefillItem(BaseModel):
    item_id: int
    codigo: Optional[str]
    descripcion: Optional[str]
    cantidad: int


class SellInPrefillOut(BaseModel):
    """What the operations say about a new sell in; the operator may change any of it."""

    pedido_compra_ids: list[int]
    proveedor_id: int
    proveedor_nombre: Optional[str]
    moneda: Moneda
    fecha_ingreso: Optional[date]
    items: list[SellInPrefillItem]


class SellInCompraListOut(BaseModel):
    items: list[SellInCompraOut]
    total: int
    page: int
    page_size: int


class SellInConteoAplica(BaseModel):
    si: int
    no: int
    todas: int


class SellInMontoPorMoneda(BaseModel):
    ARS: Decimal
    USD: Decimal


class SellInCompraResumenOut(BaseModel):
    """Aggregates over every purchase matching the list filters.

    `conteo` ignores the `aplica` filter (all three buckets stay visible); `monto_total`
    and `unidades_total` honour every filter, `aplica` included.
    """

    conteo: SellInConteoAplica
    monto_total: SellInMontoPorMoneda
    unidades_total: int
