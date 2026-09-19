"""Pydantic v2 contracts for OC-match jobs (list / detail / retry)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OcMatchRenglonResponse(BaseModel):
    """One extract/match line. Empty until Phase 3 persist."""

    id: int
    job_id: int
    indice: int
    descripcion: str | None = None
    cantidad: Decimal | None = None
    precio_unitario: Decimal | None = None
    moneda: str | None = None
    codigo_proveedor: str | None = None
    codigo_fabricante: str | None = None
    ean_extract: str | None = None
    ean_ultimos4: str | None = None
    omitir: bool = False
    motivo_omitir: str | None = None
    match_estado: str | None = None
    item_id: str | None = None
    ean: str | None = None
    confianza: str | None = None
    motivo: str | None = None

    model_config = ConfigDict(from_attributes=True)


class OcMatchJobResponse(BaseModel):
    """Job row for list and as the detail envelope base."""

    id: int
    pedido_id: int
    attachment_id: int
    status: str
    error_message: str | None = None
    acta: str | None = None
    excel_rel_path: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    retryable: bool = False

    model_config = ConfigDict(from_attributes=True)


class OcMatchJobDetalle(OcMatchJobResponse):
    """Job plus renglones (Phase 3 fills lines)."""

    renglones: list[OcMatchRenglonResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class OcMatchJobPaginated(BaseModel):
    """Paginated job list."""

    items: list[OcMatchJobResponse]
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=200)
