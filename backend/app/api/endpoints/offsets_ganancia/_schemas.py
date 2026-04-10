from typing import List, Optional
from datetime import date
from pydantic import BaseModel, ConfigDict


class OffsetGrupoFiltroCreate(BaseModel):
    marca: Optional[str] = None
    categoria: Optional[str] = None
    subcategoria_id: Optional[int] = None
    item_id: Optional[int] = None


class OffsetGrupoFiltroResponse(BaseModel):
    id: int
    grupo_id: int
    marca: Optional[str] = None
    categoria: Optional[str] = None
    subcategoria_id: Optional[int] = None
    item_id: Optional[int] = None
    producto_descripcion: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class OffsetGrupoCreate(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    filtros: Optional[List[OffsetGrupoFiltroCreate]] = None


class OffsetGrupoResponse(BaseModel):
    id: int
    nombre: str
    descripcion: Optional[str]
    filtros: List[OffsetGrupoFiltroResponse] = []

    model_config = ConfigDict(from_attributes=True)


class OffsetGananciaCreate(BaseModel):
    marca: Optional[str] = None
    categoria: Optional[str] = None
    subcategoria_id: Optional[int] = None
    item_id: Optional[int] = None
    item_ids: Optional[List[int]] = None  # Para múltiples productos
    tipo_offset: str = "monto_fijo"  # 'monto_fijo', 'monto_por_unidad', 'porcentaje_costo'
    monto: Optional[float] = None
    moneda: str = "ARS"  # 'ARS', 'USD'
    tipo_cambio: Optional[float] = None
    porcentaje: Optional[float] = None
    descripcion: Optional[str] = None
    fecha_desde: date
    fecha_hasta: Optional[date] = None
    # Nuevos campos para grupos y límites
    grupo_id: Optional[int] = None
    max_unidades: Optional[int] = None
    max_monto_usd: Optional[float] = None
    # Canales de aplicación
    aplica_ml: bool = True
    aplica_fuera: bool = True
    aplica_tienda_nube: bool = True


class OffsetGananciaUpdate(BaseModel):
    marca: Optional[str] = None
    categoria: Optional[str] = None
    subcategoria_id: Optional[int] = None
    item_id: Optional[int] = None
    tipo_offset: Optional[str] = None
    monto: Optional[float] = None
    moneda: Optional[str] = None
    tipo_cambio: Optional[float] = None
    porcentaje: Optional[float] = None
    descripcion: Optional[str] = None
    fecha_desde: Optional[date] = None
    fecha_hasta: Optional[date] = None
    # Nuevos campos para grupos y límites
    grupo_id: Optional[int] = None
    max_unidades: Optional[int] = None
    max_monto_usd: Optional[float] = None
    # Canales de aplicación
    aplica_ml: Optional[bool] = None
    aplica_fuera: Optional[bool] = None
    aplica_tienda_nube: Optional[bool] = None


class OffsetGananciaResponse(BaseModel):
    id: int
    marca: Optional[str]
    categoria: Optional[str]
    subcategoria_id: Optional[int]
    item_id: Optional[int]
    tipo_offset: str = "monto_fijo"
    monto: Optional[float]
    moneda: str = "ARS"
    tipo_cambio: Optional[float]
    porcentaje: Optional[float]
    descripcion: Optional[str]
    fecha_desde: date
    fecha_hasta: Optional[date]
    usuario_nombre: Optional[str] = None
    # Nuevos campos
    grupo_id: Optional[int] = None
    grupo_nombre: Optional[str] = None
    max_unidades: Optional[int] = None
    max_monto_usd: Optional[float] = None
    # Monto consumido
    monto_consumido: Optional[float] = None
    # Canales de aplicación
    aplica_ml: bool = True
    aplica_fuera: bool = True
    aplica_tienda_nube: bool = True

    model_config = ConfigDict(from_attributes=True)


class ProductoBusquedaGeneral(BaseModel):
    item_id: int
    codigo: str
    descripcion: str
    marca: Optional[str] = None
    costo_unitario: Optional[float] = None
    moneda_costo: Optional[str] = None


class OffsetGrupoConsumoResponse(BaseModel):
    id: int
    grupo_id: int
    grupo_nombre: Optional[str] = None
    id_operacion: Optional[int] = None
    venta_fuera_id: Optional[int] = None
    tipo_venta: str
    fecha_venta: str
    item_id: Optional[int] = None
    cantidad: int
    offset_id: int
    monto_offset_aplicado: float
    monto_offset_usd: Optional[float] = None
    cotizacion_dolar: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class OffsetGrupoResumenResponse(BaseModel):
    id: int
    grupo_id: int
    grupo_nombre: str
    total_unidades: int
    total_monto_ars: float
    total_monto_usd: float
    cantidad_ventas: int
    limite_alcanzado: Optional[str] = None
    fecha_limite_alcanzado: Optional[str] = None
    # Límites del grupo (de los offsets)
    max_unidades: Optional[int] = None
    max_monto_usd: Optional[float] = None
    porcentaje_consumido_unidades: Optional[float] = None
    porcentaje_consumido_monto: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)
