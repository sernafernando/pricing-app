"""Schemas for the official-store names admin (`/api/tiendas-oficiales`)."""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

_CLAVE_RE = re.compile(r"^[a-z0-9_]+$")


def _normalize_nombre(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("El nombre no puede estar vacío")
    return value


def _normalize_clave(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip().lower()
    if not value:
        return None
    if not _CLAVE_RE.match(value):
        raise ValueError("La clave solo admite letras, números y guion bajo")
    return value


class TiendaOficialCreate(BaseModel):
    store_id: int = Field(gt=0, description="official_store_id de MercadoLibre")
    nombre: str = Field(max_length=100)
    clave: Optional[str] = Field(default=None, max_length=50)
    orden: int = 0
    activa: bool = True

    _nombre = field_validator("nombre")(_normalize_nombre)
    _clave = field_validator("clave")(_normalize_clave)


class TiendaOficialUpdate(BaseModel):
    """Partial update: only the fields sent change (`clave: null` clears it)."""

    nombre: Optional[str] = Field(default=None, max_length=100)
    clave: Optional[str] = Field(default=None, max_length=50)
    orden: Optional[int] = None
    activa: Optional[bool] = None

    @field_validator("nombre")
    @classmethod
    def _nombre(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _normalize_nombre(value)

    _clave = field_validator("clave")(_normalize_clave)


class TiendaOficialResponse(BaseModel):
    store_id: int
    nombre: str
    clave: Optional[str] = None
    orden: int
    activa: bool

    model_config = ConfigDict(from_attributes=True)
