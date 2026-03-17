"""
Schemas Pydantic para Document Templates
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Any, Optional, List
from datetime import datetime

from app.models.document_template import CONTEXTOS_VALIDOS


class DocumentTemplateBase(BaseModel):
    """Base schema para DocumentTemplate"""

    nombre: str = Field(..., min_length=1, max_length=200)
    descripcion: Optional[str] = None
    contexto: str = Field(..., max_length=50)
    template_json: dict[str, Any] = Field(..., description="pdfme Template JSON: debe contener 'basePdf' y 'schemas'")

    @field_validator("contexto")
    @classmethod
    def validar_contexto(cls, v: str) -> str:
        if v not in CONTEXTOS_VALIDOS:
            raise ValueError(f"Contexto inválido: '{v}'. Debe ser uno de: {CONTEXTOS_VALIDOS}")
        return v

    @field_validator("template_json")
    @classmethod
    def validar_template_json(cls, v: dict[str, Any]) -> dict[str, Any]:
        if "basePdf" not in v:
            raise ValueError("template_json debe contener la clave 'basePdf'")
        if "schemas" not in v:
            raise ValueError("template_json debe contener la clave 'schemas'")
        return v


class DocumentTemplateCreate(DocumentTemplateBase):
    """Schema para crear DocumentTemplate"""

    pass


class DocumentTemplateUpdate(BaseModel):
    """Schema para actualizar DocumentTemplate (todos campos opcionales)"""

    nombre: Optional[str] = Field(None, min_length=1, max_length=200)
    descripcion: Optional[str] = None
    contexto: Optional[str] = Field(None, max_length=50)
    template_json: Optional[dict[str, Any]] = None
    activo: Optional[bool] = None

    @field_validator("contexto")
    @classmethod
    def validar_contexto(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in CONTEXTOS_VALIDOS:
            raise ValueError(f"Contexto inválido: '{v}'. Debe ser uno de: {CONTEXTOS_VALIDOS}")
        return v

    @field_validator("template_json")
    @classmethod
    def validar_template_json(cls, v: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if v is not None:
            if "basePdf" not in v:
                raise ValueError("template_json debe contener la clave 'basePdf'")
            if "schemas" not in v:
                raise ValueError("template_json debe contener la clave 'schemas'")
        return v


class DocumentTemplateCreadorResponse(BaseModel):
    """Schema para el usuario creador/actualizador"""

    id: int
    nombre: str

    model_config = ConfigDict(from_attributes=True)


class DocumentTemplateResponse(BaseModel):
    """Schema para respuesta de DocumentTemplate"""

    id: int
    nombre: str
    descripcion: Optional[str] = None
    contexto: str
    template_json: dict[str, Any]
    activo: bool
    creado_por_id: int
    actualizado_por_id: Optional[int] = None
    creado_por: Optional[DocumentTemplateCreadorResponse] = None
    actualizado_por: Optional[DocumentTemplateCreadorResponse] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DocumentTemplateListResponse(BaseModel):
    """Schema simplificado para listados (sin template_json completo)"""

    id: int
    nombre: str
    descripcion: Optional[str] = None
    contexto: str
    activo: bool
    creado_por: Optional[DocumentTemplateCreadorResponse] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# --- Variables por contexto ---


class VariableInfo(BaseModel):
    """Información de una variable disponible para un contexto"""

    nombre: str = Field(..., description="Nombre de la variable (key para pdfme)")
    tipo: str = Field(..., description="Tipo de dato: text, number, date, boolean, image")
    descripcion: str = Field(..., description="Descripción legible para el usuario")
    ejemplo: Optional[str] = Field(None, description="Valor de ejemplo")


class ContextVariablesResponse(BaseModel):
    """Variables disponibles para un contexto"""

    contexto: str
    variables: List[VariableInfo]
