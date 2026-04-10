from typing import List, Optional
from pydantic import BaseModel


class DesgloseMarca(BaseModel):
    """Desglose por marca dentro de una card"""

    marca: str
    monto_venta: float
    ganancia: float
    markup_promedio: float


class DesgloseOffset(BaseModel):
    """Desglose de un offset aplicado"""

    descripcion: str
    nivel: str  # marca, categoria, subcategoria, producto
    nombre_nivel: str  # ej: "LENOVO", "Notebooks", etc.
    tipo_offset: str  # monto_fijo, monto_por_unidad, porcentaje_costo
    monto: float


class CardRentabilidad(BaseModel):
    """Card de rentabilidad para mostrar en el dashboard"""

    nombre: str
    tipo: str  # marca, categoria, subcategoria, producto
    identificador: Optional[str] = None

    # Métricas
    total_ventas: int
    monto_venta: float
    monto_limpio: float
    costo_total: float
    ganancia: float
    markup_promedio: float

    # Offset Flex (métrica separada del sistema de offsets de compensación)
    offset_flex_total: float = 0.0

    # Offsets aplicados
    offset_total: float
    ganancia_con_offset: float
    markup_con_offset: float

    # Desglose de offsets aplicados
    desglose_offsets: Optional[List[DesgloseOffset]] = None

    # Desglose por marca (cuando hay múltiples marcas seleccionadas)
    desglose_marcas: Optional[List[DesgloseMarca]] = None


class RentabilidadResponse(BaseModel):
    cards: List[CardRentabilidad]
    totales: CardRentabilidad
    filtros_aplicados: dict


class ProductoBusqueda(BaseModel):
    """Producto encontrado en búsqueda"""

    item_id: int
    codigo: str
    descripcion: str
    marca: Optional[str] = None
    categoria: Optional[str] = None
