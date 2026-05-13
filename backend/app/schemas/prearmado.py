"""Pydantic schemas para el feature de Prearmado de Combos."""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


Estado = Literal["pendiente", "en_proceso", "armado", "consumido", "anulado"]
Origen = Literal["bom", "sufijo"]
IncluyeWindows = Literal["home", "pro"]
ValidationMotivo = Literal["SerialNotFound", "ItemMismatch"]


# --- Búsqueda de combos en el catálogo (no en cache de pedidos) ---


class ComboSearchResult(BaseModel):
    """Resultado de búsqueda en el catálogo de combos de tb_item."""

    item_id: int
    item_code: str
    item_desc: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# --- Componentes del combo (para construir el form de carga) ---


class ComponenteForPrearmado(BaseModel):
    """Componente del combo a serializar."""

    item_id: int
    item_code: str
    item_desc: Optional[str] = None
    cantidad_esperada: int = 1
    requiere_serie: bool = True
    origen: Origen = "bom"
    sufijo: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ComponentesForCombo(BaseModel):
    """Respuesta de GET /prearmado/componentes/{combo_item_id}."""

    combo_item_id: int
    combo_item_code: str
    combo_item_desc: Optional[str] = None
    incluye_windows: Optional[IncluyeWindows] = None
    componentes: List[ComponenteForPrearmado]

    model_config = ConfigDict(from_attributes=True)


# --- Validación de serial ---


class ValidateSerialRequest(BaseModel):
    """Body de POST /prearmado/validar-serial."""

    serial: str = Field(..., min_length=1, max_length=255)
    item_id_esperado: int


class ValidateSerialResponse(BaseModel):
    """Resultado de validación: existe en tb_item_serials y matchea con el item esperado."""

    valid: bool
    motivo: Optional[ValidationMotivo] = None
    is_id: Optional[int] = None
    item_id_real: Optional[int] = None
    item_code_real: Optional[str] = None
    item_desc_real: Optional[str] = None


# --- Crear y editar prearmado ---


class PrearmadoCreate(BaseModel):
    """Body de POST /prearmado."""

    combo_item_id: int
    notas: Optional[str] = None


class PrearmadoPatch(BaseModel):
    """Body de PATCH /prearmado/{id} (cambio de estado y/o notas)."""

    estado: Optional[Estado] = None
    notas: Optional[str] = None


# --- Carga de seriales ---


class SerialInput(BaseModel):
    """Un serial a cargar/upsert por componente."""

    componente_item_id: int
    componente_item_code: Optional[str] = None
    componente_item_desc: Optional[str] = None
    serial: Optional[str] = None  # null cuando requiere_serie=false
    cantidad_esperada: int = 1
    requiere_serie: bool = True
    origen: Origen = "bom"
    sufijo: Optional[str] = None
    force: bool = False  # guarda serial inválido con validado=false


class SerialesPayload(BaseModel):
    """Body de POST /prearmado/{id}/seriales."""

    items: List[SerialInput] = Field(default_factory=list)


class SerialUpdate(BaseModel):
    """Body de PATCH /prearmado/{id}/seriales/{serial_id} — reemplazar un serial."""

    serial: str = Field(..., min_length=1, max_length=255)
    force: bool = False  # guarda con validado=false si la validación falla


# --- Respuestas de prearmado ---


class SerialDetail(BaseModel):
    """Detalle de un serial cargado en un prearmado."""

    id: int
    componente_item_id: int
    componente_item_code: str
    componente_item_desc: Optional[str] = None
    serial: Optional[str] = None
    is_id: Optional[int] = None
    cantidad_esperada: int
    requiere_serie: bool
    validado: bool
    validado_at: Optional[datetime] = None
    origen: Origen
    sufijo: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PrearmadoListItem(BaseModel):
    """Item de la lista de prearmados (sin detalle de seriales)."""

    id: int
    codigo: str
    combo_item_id: int
    combo_item_code: str
    combo_item_desc: Optional[str] = None
    incluye_windows: Optional[IncluyeWindows] = None
    estado: Estado
    consumido_por_soh_id: Optional[int] = None
    consumido_at: Optional[datetime] = None
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime
    seriales_total: int = 0
    seriales_validados: int = 0
    seriales_completos: bool = False

    model_config = ConfigDict(from_attributes=True)


class PrearmadoDetail(PrearmadoListItem):
    """Detalle completo con seriales y notas."""

    notas: Optional[str] = None
    seriales: List[SerialDetail] = Field(default_factory=list)


# --- Matcher / rematch ---


class RematchResponse(BaseModel):
    """Respuesta de POST /prearmado/rematch."""

    matched: int
    total_checked: int
    errors: List[str] = Field(default_factory=list)
