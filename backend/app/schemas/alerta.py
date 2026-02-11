"""
Schemas Pydantic para Alertas
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class AlertaBase(BaseModel):
    """Base schema para Alerta"""

    titulo: str = Field(..., max_length=200)
    mensaje: str
    variant: str = Field(default="info", pattern="^(info|warning|success|error)$")
    action_label: Optional[str] = Field(None, max_length=100)
    action_url: Optional[str] = Field(None, max_length=500)
    dismissible: bool = True
    persistent: bool = False
    roles_destinatarios: List[str] = Field(default_factory=list)
    activo: bool = False
    fecha_desde: datetime
    fecha_hasta: Optional[datetime] = None
    prioridad: int = 0
    duracion_segundos: int = Field(default=5, ge=0, le=60)


class AlertaCreate(AlertaBase):
    """Schema para crear Alerta"""

    usuarios_destinatarios_ids: Optional[List[int]] = Field(default_factory=list)


class AlertaUpdate(BaseModel):
    """Schema para actualizar Alerta (todos campos opcionales)"""

    titulo: Optional[str] = Field(None, max_length=200)
    mensaje: Optional[str] = None
    variant: Optional[str] = Field(None, pattern="^(info|warning|success|error)$")
    action_label: Optional[str] = Field(None, max_length=100)
    action_url: Optional[str] = Field(None, max_length=500)
    dismissible: Optional[bool] = None
    persistent: Optional[bool] = None
    roles_destinatarios: Optional[List[str]] = None
    usuarios_destinatarios_ids: Optional[List[int]] = None
    activo: Optional[bool] = None
    fecha_desde: Optional[datetime] = None
    fecha_hasta: Optional[datetime] = None
    prioridad: Optional[int] = None
    duracion_segundos: Optional[int] = Field(None, ge=0, le=60)


class AlertaUsuarioDestinatarioResponse(BaseModel):
    """Schema para usuario destinatario"""

    id: int
    nombre: str
    email: Optional[str] = None

    class Config:
        from_attributes = True


class AlertaResponse(AlertaBase):
    """Schema para respuesta de Alerta (incluye todos los campos de AlertaBase + metadata)"""

    id: int
    created_by_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    usuarios_destinatarios: List[AlertaUsuarioDestinatarioResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True


class AlertaActivaResponse(BaseModel):
    """Schema simplificado para alertas activas (frontend)"""

    id: int
    mensaje: str
    variant: str
    action_label: Optional[str] = None
    action_url: Optional[str] = None
    dismissible: bool
    persistent: bool
    prioridad: int
    duracion_segundos: int

    class Config:
        from_attributes = True


class ConfiguracionAlertaResponse(BaseModel):
    """Schema para configuración de alertas"""

    id: int
    max_alertas_visibles: int
    updated_by_id: Optional[int] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ConfiguracionAlertaUpdate(BaseModel):
    """Schema para actualizar configuración"""

    max_alertas_visibles: int = Field(..., ge=1, le=10)
