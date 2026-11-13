"""Schemas for the brands-without-stock exception list admin (`/api/marcas-visibles`)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator


class MarcaVisibleCreate(BaseModel):
    """Adds one brand to the exception list."""

    marca: str

    @field_validator("marca")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("La marca no puede estar vacía")
        return value


class MarcaVisibleExcepcionResponse(BaseModel):
    """One exception: the brand, who added it, when, and whether it has stock right now."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    marca: str
    creado_por: Optional[str] = None
    created_at: datetime
    con_stock: bool


class MarcaStockOption(BaseModel):
    """One brand of the catalog for the admin's searchable picker (every brand, hidden ones included)."""

    marca: str
    con_stock: bool
    en_excepcion: bool


class MarcasVisiblesResponse(BaseModel):
    """The admin screen in one read: the exception list and every brand of the catalog."""

    excepciones: List[MarcaVisibleExcepcionResponse]
    marcas: List[MarcaStockOption]
