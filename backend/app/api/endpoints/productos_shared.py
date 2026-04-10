"""
Shared Pydantic models for the productos module.

All schemas used across productos sub-modules live here.
"""

from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)


class ProductoResponse(BaseModel):
    item_id: int
    codigo: str
    descripcion: str
    marca: Optional[str]
    categoria: Optional[str]
    subcategoria_id: Optional[int]
    moneda_costo: Optional[str]
    costo: float
    costo_ars: Optional[float]
    iva: float
    stock: int
    precio_lista_ml: Optional[float]
    markup: Optional[float]
    usuario_modifico: Optional[str]
    fecha_modificacion: Optional[datetime]
    tiene_precio: bool
    necesita_revision: bool
    participa_rebate: Optional[bool] = False
    porcentaje_rebate: Optional[float] = 3.8
    precio_rebate: Optional[float] = None
    markup_rebate: Optional[float] = None
    participa_web_transferencia: Optional[bool] = False
    porcentaje_markup_web: Optional[float] = 6.0
    precio_web_transferencia: Optional[float] = None
    markup_web_real: Optional[float] = None
    preservar_porcentaje_web: Optional[bool] = False
    mejor_oferta_precio: Optional[float] = None
    mejor_oferta_monto_rebate: Optional[float] = None
    mejor_oferta_pvp_seller: Optional[float] = None
    mejor_oferta_markup: Optional[float] = None
    mejor_oferta_porcentaje_rebate: Optional[float] = None
    mejor_oferta_fecha_hasta: Optional[date] = None
    out_of_cards: Optional[bool] = False
    color_marcado: Optional[str] = None
    precio_3_cuotas: Optional[float] = None
    precio_6_cuotas: Optional[float] = None
    precio_9_cuotas: Optional[float] = None
    precio_12_cuotas: Optional[float] = None
    markup_3_cuotas: Optional[float] = None
    markup_6_cuotas: Optional[float] = None
    markup_9_cuotas: Optional[float] = None
    markup_12_cuotas: Optional[float] = None

    # Precios PVP
    precio_pvp: Optional[float] = None
    precio_pvp_3_cuotas: Optional[float] = None
    precio_pvp_6_cuotas: Optional[float] = None
    precio_pvp_9_cuotas: Optional[float] = None
    precio_pvp_12_cuotas: Optional[float] = None
    markup_pvp: Optional[float] = None
    markup_pvp_3_cuotas: Optional[float] = None
    markup_pvp_6_cuotas: Optional[float] = None
    markup_pvp_9_cuotas: Optional[float] = None
    markup_pvp_12_cuotas: Optional[float] = None

    # Configuración individual
    recalcular_cuotas_auto: Optional[bool] = None
    markup_adicional_cuotas_custom: Optional[float] = None
    markup_adicional_cuotas_pvp_custom: Optional[float] = None

    # Estado de catálogo ML
    catalog_status: Optional[str] = None
    has_catalog: Optional[bool] = None
    catalog_price_to_win: Optional[float] = None
    catalog_winner_price: Optional[float] = None

    # Precios Tienda Nube
    tn_price: Optional[float] = None  # Precio normal
    tn_promotional_price: Optional[float] = None  # Precio promocional
    tn_has_promotion: Optional[bool] = None  # Si tiene promoción activa

    model_config = ConfigDict(from_attributes=True)


class ProductoListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    productos: List[ProductoResponse]


class PrecioUpdate(BaseModel):
    precio_lista_final: Optional[float] = None
    precio_contado_final: Optional[float] = None
    comentario: Optional[str] = None


class RebateUpdate(BaseModel):
    participa_rebate: bool
    porcentaje_rebate: float = Field(ge=0, le=100)


class ProductoTiendaResponse(BaseModel):
    item_id: int
    codigo: str
    descripcion: str
    marca: Optional[str]
    categoria: Optional[str]
    subcategoria_id: Optional[int]
    moneda_costo: Optional[str]
    costo: float
    costo_ars: Optional[float]
    iva: float
    stock: int
    precio_lista_ml: Optional[float]
    markup: Optional[float]
    usuario_modifico: Optional[str]
    fecha_modificacion: Optional[datetime]
    tiene_precio: bool
    necesita_revision: bool
    participa_rebate: Optional[bool] = False
    porcentaje_rebate: Optional[float] = 3.8
    precio_rebate: Optional[float] = None
    markup_rebate: Optional[float] = None
    precio_gremio_sin_iva: Optional[float] = None
    precio_gremio_con_iva: Optional[float] = None
    markup_gremio: Optional[float] = None
    tiene_override_gremio: Optional[bool] = False  # Indica si tiene precio manual
    participa_web_transferencia: Optional[bool] = False
    porcentaje_markup_web: Optional[float] = 6.0
    precio_web_transferencia: Optional[float] = None
    markup_web_real: Optional[float] = None
    preservar_porcentaje_web: Optional[bool] = False
    mejor_oferta_precio: Optional[float] = None
    mejor_oferta_monto_rebate: Optional[float] = None
    mejor_oferta_pvp_seller: Optional[float] = None
    mejor_oferta_markup: Optional[float] = None
    mejor_oferta_porcentaje_rebate: Optional[float] = None
    mejor_oferta_fecha_hasta: Optional[date] = None
    out_of_cards: Optional[bool] = False
    color_marcado: Optional[str] = None
    color_marcado_tienda: Optional[str] = None
    precio_3_cuotas: Optional[float] = None
    precio_6_cuotas: Optional[float] = None
    precio_9_cuotas: Optional[float] = None
    precio_12_cuotas: Optional[float] = None
    markup_3_cuotas: Optional[float] = None
    markup_6_cuotas: Optional[float] = None
    markup_9_cuotas: Optional[float] = None
    markup_12_cuotas: Optional[float] = None
    recalcular_cuotas_auto: Optional[bool] = None
    markup_adicional_cuotas_custom: Optional[float] = None
    markup_adicional_cuotas_pvp_custom: Optional[float] = None
    catalog_status: Optional[str] = None
    has_catalog: Optional[bool] = None
    catalog_price_to_win: Optional[float] = None
    catalog_winner_price: Optional[float] = None
    tn_price: Optional[float] = None
    tn_promotional_price: Optional[float] = None
    tn_has_promotion: Optional[bool] = None

    model_config = ConfigDict(from_attributes=True)


class ProductoTiendaListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    productos: List[ProductoTiendaResponse]


class ExportRebateRequest(BaseModel):
    fecha_desde: Optional[str] = None
    fecha_hasta: Optional[str] = None
    filtros: Optional[dict] = None
    estado_mla: Optional[str] = None
    formato: Optional[str] = "nuevo"  # nuevo, tradicional
    tipo_cuotas: Optional[str] = "clasica"  # clasica, 3, 6, 9, 12
    porcentaje_rebate_override: Optional[float] = None  # Override global para cuotas (ej: 1.5)
    offset_pvp_lleno: Optional[float] = None  # Offset % sobre precio cuotas para PVP LLENO (ej: 5.0)


class CalculoWebMasivoRequest(BaseModel):
    porcentaje_con_precio: float
    porcentaje_sin_precio: float
    filtros: dict = None


class CalculoPVPMasivoRequest(BaseModel):
    markup_pvp_clasica: float
    adicional_cuotas: float
    filtros: dict = None


class RecalcularCuotasMasivoRequest(BaseModel):
    lista_tipo: str = "web"  # "web" o "pvp"
    filtros: dict = None


class ConfigCuotasRequest(BaseModel):
    recalcular_cuotas_auto: Optional[bool] = None
    markup_adicional_cuotas_custom: Optional[float] = None
    markup_adicional_cuotas_pvp_custom: Optional[float] = None


class ColorLoteRequest(BaseModel):
    item_ids: List[int]
    color: Optional[str] = None
