"""The sell-in lot viewer of a product (read only); see `app.services.sell_in.visor_lotes`."""

from datetime import date
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict

# 'reemplazado': a manual cost mode's block replaced the units it had left.
EstadoLote = Literal["vigente", "en_cola", "agotado", "desde", "reemplazado"]


class LoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    numero: int  # place in the FIFO order, from 1
    compra_item_id: int
    compra_id: int
    proveedor: Optional[str]
    facturas: List[str]
    moneda: str  # the purchase's currency; descuento_unit is always ARS
    fecha_desde: date
    cantidad: int
    consumidas: int
    restantes: int
    descuento_unit: Decimal  # ARS per unit; a manual block's is signed (negative: it raises the cost)
    estado: EstadoLote
    manual: bool = False  # a manual cost mode's block: compra_id is its mode row, compra_item_id minus that


class SiguienteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    numero: int
    descuento_unit: Decimal
    fecha_desde: date
    estado: EstadoLote


class ProximaVentaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    numero: int
    compra_item_id: int
    descuento_unit: Decimal
    restantes: int
    siguiente: Optional[SiguienteOut]


class BonoCostoOut(BaseModel):
    """The % of cost bonuses the next sale gets when no lot has units (as the Productos screens decide it)."""

    model_config = ConfigDict(from_attributes=True)

    bono_ids: List[int]
    descuento_unit: float  # ARS per unit


class LotesProductoOut(BaseModel):
    item_id: int
    lotes: List[LoteOut]
    proxima: Optional[ProximaVentaOut]  # None: no lot has units today, the cost is back to normal
    # What applies while no lot has units: no `proxima`, no `siguiente`, or a `siguiente` that counts from a future date.
    bono_costo: Optional[BonoCostoOut] = None
    # False without `productos.ver_info_compras`: each lot's `proveedor` and `facturas` are withheld, not missing.
    compra_visible: bool


class ConsumoLoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    canal: str
    venta_ref: int
    fecha_venta: date
    unidades: int
    descuento_ars: Decimal


class ConsumosLoteOut(BaseModel):
    items: List[ConsumoLoteOut]
    total: int
    page: int
    page_size: int


class ProductoCostoOut(BaseModel):
    """A row of the Sell in "Productos" list; see `app.services.sell_in.productos_costo`."""

    model_config = ConfigDict(from_attributes=True)

    item_id: int
    codigo: Optional[str]
    descripcion: Optional[str]
    marca: Optional[str]
    modo: Optional[str]  # the mode governing today; None: FIFO, the default
    unidades: int
    sell_in_unit: Optional[Decimal]  # ARS the next sale takes per unit; None: no line counts today
    ultima_compra: date


class ProductosCostoOut(BaseModel):
    productos: List[ProductoCostoOut]
