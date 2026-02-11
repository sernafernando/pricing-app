from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Dict, Any
from datetime import datetime
from app.tickets.models.ticket import PrioridadTicket


class UsuarioSimple(BaseModel):
    """Usuario simplificado para responses"""
    id: int
    nombre: str
    email: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class EstadoSimple(BaseModel):
    """Estado simplificado para responses"""
    id: int
    codigo: str
    nombre: str
    color: Optional[str] = None
    es_final: bool
    
    model_config = ConfigDict(from_attributes=True)


class SectorSimple(BaseModel):
    """Sector simplificado para responses"""
    id: int
    codigo: str
    nombre: str
    color: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class TipoTicketSimple(BaseModel):
    """Tipo de ticket simplificado para responses"""
    id: int
    codigo: str
    nombre: str
    
    model_config = ConfigDict(from_attributes=True)


class AsignacionSimple(BaseModel):
    """Asignación simplificada para responses"""
    id: int
    asignado_a: UsuarioSimple
    fecha_asignacion: datetime
    esta_activa: bool
    
    model_config = ConfigDict(from_attributes=True)


class TicketBase(BaseModel):
    """Schema base para Ticket"""
    titulo: str = Field(..., min_length=5, max_length=255, description="Título del ticket")
    descripcion: Optional[str] = Field(default=None, description="Descripción detallada")
    prioridad: PrioridadTicket = Field(default=PrioridadTicket.MEDIA, description="Prioridad del ticket")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Campos dinámicos según tipo de ticket")


class TicketCreate(TicketBase):
    """Schema para crear un Ticket"""
    sector_id: int = Field(..., description="ID del sector al que pertenece")
    tipo_ticket_id: int = Field(..., description="ID del tipo de ticket")


class TicketUpdate(BaseModel):
    """Schema para actualizar un Ticket"""
    titulo: Optional[str] = Field(default=None, min_length=5, max_length=255)
    descripcion: Optional[str] = None
    prioridad: Optional[PrioridadTicket] = None
    metadata: Optional[Dict[str, Any]] = None


class TicketResponse(TicketBase):
    """Schema de respuesta completo para Ticket"""
    id: int
    sector: SectorSimple
    tipo_ticket: TipoTicketSimple
    estado: EstadoSimple
    creador: UsuarioSimple
    asignado_a: Optional[UsuarioSimple] = None
    asignacion_actual: Optional[AsignacionSimple] = None
    esta_cerrado: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class TicketListResponse(BaseModel):
    """Schema de respuesta simplificado para listados"""
    id: int
    titulo: str
    prioridad: PrioridadTicket
    sector: SectorSimple
    tipo_ticket: TipoTicketSimple
    estado: EstadoSimple
    creador: UsuarioSimple
    asignado_a: Optional[UsuarioSimple] = None
    esta_cerrado: bool
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class ComentarioCreate(BaseModel):
    """Schema para crear un comentario"""
    contenido: str = Field(..., min_length=1, max_length=5000)
    es_interno: bool = Field(default=False, description="Si es interno (solo equipo)")


class ComentarioResponse(BaseModel):
    """Schema de respuesta para comentario"""
    id: int
    ticket_id: int
    usuario: UsuarioSimple
    contenido: str
    es_interno: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class HistorialResponse(BaseModel):
    """Schema de respuesta para historial"""
    id: int
    usuario: Optional[UsuarioSimple] = None
    accion: str
    descripcion: Optional[str] = None
    estado_anterior: Optional[EstadoSimple] = None
    estado_nuevo: Optional[EstadoSimple] = None
    cambios: Dict[str, Any]
    fecha: datetime
    
    model_config = ConfigDict(from_attributes=True)


class TransicionRequest(BaseModel):
    """Schema para solicitar una transición de estado"""
    nuevo_estado_id: int = Field(..., description="ID del nuevo estado")
    comentario: Optional[str] = Field(default=None, description="Comentario sobre la transición")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Metadata adicional a actualizar")


class AsignarTicketRequest(BaseModel):
    """Schema para asignar un ticket"""
    usuario_id: int = Field(..., description="ID del usuario a asignar")
    motivo: Optional[str] = Field(default=None, max_length=500, description="Motivo de la asignación")
