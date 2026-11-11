"""Schemas of the Publicaciones ML product view's shipping-cost choice (S7b,
`/ml-publications/view/products/{item_id}/envio`)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

ModoEnvio = Literal["max", "mla", "promedio", "ponderado"]


class PublicacionEnvioOut(BaseModel):
    mla: str
    costo: Optional[float] = Field(None, description="Its own ML list_cost (ARS, with IVA); null without one")
    unidades: int = Field(description="Units sold in the period (Métricas ML's base)")
    mas_vendida: bool = Field(description="The most sold of the period (every one tied at the top)")
    tipo: Optional[str] = Field(None, description="ML listing_type_id (gold_special, gold_pro); null if not stored")
    logistica: Optional[str] = Field(None, description="ML shipping logistic_type (drop_off, cross_docking, ...)")


class EleccionEnvioOut(BaseModel):
    modo: ModoEnvio
    mla: Optional[str] = None
    costo: float = Field(description="What the product resolves to now (a ponderado with the last 30 days)")
    warning: Optional[str] = Field(None, description="A chosen publication fell back to the MAX")
    usuario_id: Optional[int] = None
    usuario_nombre: Optional[str] = Field(None, description="Who made the stored choice (`usuarios.nombre`)")
    updated_at: Optional[datetime] = None


class OpcionesEnvioResponse(BaseModel):
    item_id: int
    date_from: date
    date_to: date
    publicaciones: list[PublicacionEnvioOut]
    promedio: Optional[float] = None
    ponderado: Optional[float] = Field(None, description="Null without sales in the period")
    max: Optional[float] = None
    eleccion: EleccionEnvioOut


class EleccionEnvioIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modo: ModoEnvio
    mla: Optional[str] = Field(None, max_length=32)

    @model_validator(mode="after")
    def _mla_only_with_modo_mla(self) -> "EleccionEnvioIn":
        if (self.modo == "mla") != (self.mla is not None):
            raise ValueError("mla goes with modo = mla, and only with it")
        return self


class EleccionEnvioGuardada(BaseModel):
    item_id: int
    modo: ModoEnvio
    mla: Optional[str] = None
    usuario_id: int
    updated_at: datetime
