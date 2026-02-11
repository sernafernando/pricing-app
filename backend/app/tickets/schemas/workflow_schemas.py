from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any


class EstadoTicketBase(BaseModel):
    """Schema base para EstadoTicket"""

    codigo: str = Field(..., min_length=2, max_length=50)
    nombre: str = Field(..., min_length=2, max_length=100)
    descripcion: Optional[str] = None
    orden: int = Field(..., ge=0, description="Orden de visualización")
    color: Optional[str] = Field(default=None, max_length=20)
    es_inicial: bool = Field(default=False, description="Estado inicial al crear ticket")
    es_final: bool = Field(default=False, description="Estado terminal (cerrado)")
    acciones_on_enter: List[Dict[str, Any]] = Field(default_factory=list, description="Acciones al entrar al estado")


class EstadoTicketCreate(EstadoTicketBase):
    """Schema para crear un EstadoTicket"""

    workflow_id: int


class EstadoTicketUpdate(BaseModel):
    """Schema para actualizar un EstadoTicket"""

    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    orden: Optional[int] = None
    color: Optional[str] = None
    es_inicial: Optional[bool] = None
    es_final: Optional[bool] = None
    acciones_on_enter: Optional[List[Dict[str, Any]]] = None


class EstadoTicketResponse(EstadoTicketBase):
    """Schema de respuesta para EstadoTicket"""

    id: int
    workflow_id: int

    model_config = ConfigDict(from_attributes=True)


class TransicionEstadoBase(BaseModel):
    """Schema base para TransicionEstado"""

    nombre: Optional[str] = Field(default=None, max_length=100)
    descripcion: Optional[str] = None
    requiere_permiso: Optional[str] = Field(default=None, description="Código de permiso requerido")
    solo_asignado: bool = Field(default=False, description="Solo el asignado puede hacer esta transición")
    solo_creador: bool = Field(default=False, description="Solo el creador puede hacer esta transición")
    validaciones: List[Dict[str, Any]] = Field(default_factory=list, description="Validaciones a ejecutar")
    acciones: List[Dict[str, Any]] = Field(default_factory=list, description="Acciones a ejecutar")


class TransicionEstadoCreate(TransicionEstadoBase):
    """Schema para crear una TransicionEstado"""

    workflow_id: int
    estado_origen_id: int
    estado_destino_id: int


class TransicionEstadoUpdate(BaseModel):
    """Schema para actualizar una TransicionEstado"""

    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    requiere_permiso: Optional[str] = None
    solo_asignado: Optional[bool] = None
    solo_creador: Optional[bool] = None
    validaciones: Optional[List[Dict[str, Any]]] = None
    acciones: Optional[List[Dict[str, Any]]] = None


class TransicionEstadoResponse(TransicionEstadoBase):
    """Schema de respuesta para TransicionEstado"""

    id: int
    workflow_id: int
    estado_origen_id: int
    estado_destino_id: int
    estado_origen: Optional[EstadoTicketResponse] = None
    estado_destino: Optional[EstadoTicketResponse] = None

    model_config = ConfigDict(from_attributes=True)


class WorkflowBase(BaseModel):
    """Schema base para Workflow"""

    nombre: str = Field(..., min_length=3, max_length=100)
    descripcion: Optional[str] = None
    es_default: bool = Field(default=False, description="Workflow por defecto para el sector")
    activo: bool = Field(default=True)


class WorkflowCreate(WorkflowBase):
    """Schema para crear un Workflow"""

    sector_id: int


class WorkflowUpdate(BaseModel):
    """Schema para actualizar un Workflow"""

    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    es_default: Optional[bool] = None
    activo: Optional[bool] = None


class WorkflowResponse(WorkflowBase):
    """Schema de respuesta para Workflow"""

    id: int
    sector_id: int
    estados: List[EstadoTicketResponse] = Field(default_factory=list)
    transiciones: List[TransicionEstadoResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
