"""Response of GET /api/precios/variantes-envio: the markup of a price per active publication."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class VarianteEnvio(BaseModel):
    """One active publication (MLA) priced with its own shipping cost."""

    mla: str
    pricelist_id: Optional[int]
    listing_type: Optional[str]
    logistic_type: Optional[str]
    logistica: Optional[str]  # flex | colecta | full; None when the logistic type is unknown or unmapped
    costo_envio: Optional[float]  # list_cost (ARS, with IVA); None when mlwebhook has none for the MLA
    sin_costo_envio: bool
    sin_precio_motivo: Optional[str]  # sin_comision | sin_costo_envio; None when priced
    comision_base_pct: Optional[float]
    markup_pct: Optional[float]  # None when sin_precio_motivo is set
    ganancia: Optional[float]
    markup_pct_actual: Optional[float]  # the same publication priced with today's MAX shipping cost
    unidades_vendidas: int


class PublicacionSinPrecio(BaseModel):
    mla: str
    motivo: str  # sin_comision | sin_costo_envio


class PromedioSimple(BaseModel):
    markup_pct: float
    ganancia: float
    publicaciones: int


class PromedioPonderado(BaseModel):
    markup_pct: float
    ganancia: float
    unidades: int


class MarkupActual(BaseModel):
    """Today's value: the markup every screen shows, with MAX(list_cost) or the ERP fallback."""

    costo_envio: float
    origen: str  # max_publicaciones | erp
    pricelist_id: int
    comision_base_pct: Optional[float]
    markup_pct: Optional[float]
    ganancia: Optional[float]


class VariantesEnvioResponse(BaseModel):
    item_id: int
    codigo: Optional[str]
    descripcion: Optional[str]
    precio: float
    costo_ars: float
    tipo_cambio: Optional[float]
    umbral_envio_gratis: float
    envio_aplica: bool
    ventana_dias: int
    ponderacion: str
    variantes: list[VarianteEnvio]
    publicaciones_sin_costo_envio: list[str]
    publicaciones_sin_precio: list[PublicacionSinPrecio]
    promedio_simple: Optional[PromedioSimple]
    promedio_ponderado: Optional[PromedioPonderado]
    actual: MarkupActual
