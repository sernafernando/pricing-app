"""
Pydantic v2 schemas for OC (purchase order) linking and ingreso confirmation.

Slice 1: VincularOCRequest, OCCandidataResponse, OrdenCompraDetalleResponse.
Slice 2 schemas will be added here when OC-S2.3 is implemented.
"""

from __future__ import annotations

from decimal import Decimal
from typing import List

from pydantic import BaseModel, ConfigDict, model_validator


# ──────────────────────────────────────────────────────────────────────────
# Slice 1 — OC link + read-only breakdown
# ──────────────────────────────────────────────────────────────────────────


class VincularOCRequest(BaseModel):
    """Request body for POST /pedidos/{id}/vincular-oc.

    All three fields are required. A partial set (e.g. only two of three)
    is semantically invalid — the validator enforces the invariant.
    """

    oc_comp_id: int
    oc_bra_id: int
    oc_poh_id: int

    @model_validator(mode="after")
    def _all_fields_present(self) -> "VincularOCRequest":
        # Pydantic already rejects missing required fields with 422, but this
        # validator makes the business rule explicit and testable.
        if self.oc_comp_id is None or self.oc_bra_id is None or self.oc_poh_id is None:
            raise ValueError("oc_comp_id, oc_bra_id, and oc_poh_id must all be provided")
        return self


class OCCandidataResponse(BaseModel):
    """One OC candidate returned by GET /pedidos/{id}/oc-candidatas."""

    oc_comp_id: int
    oc_bra_id: int
    oc_poh_id: int
    poh_cd: str | None = None  # ISO datetime string from the ERP
    poh_total: Decimal | None = None
    qty_total: Decimal | None = None
    lineas_pendientes: int | None = None

    model_config = ConfigDict(from_attributes=True)


class OrdenCompraLineaResponse(BaseModel):
    """One detail line for the OC breakdown (one row per pod_id)."""

    pod_id: int
    item_id: int | None = None
    item_nombre: str | None = None  # resolved via LEFT JOIN to productos_erp (Slice 2)
    stor_id: int | None = None
    deposito_nombre: str | None = None
    pod_qty: Decimal | None = None
    pod_confirmedqty: Decimal | None = None
    saldo_pendiente: Decimal | None = None
    pod_price: Decimal | None = None

    model_config = ConfigDict(from_attributes=True)


class OrdenCompraDetalleResponse(BaseModel):
    """Response for GET /pedidos/{id}/orden-compra/detalle."""

    oc_comp_id: int
    oc_bra_id: int
    oc_poh_id: int
    lines: List[OrdenCompraLineaResponse]

    model_config = ConfigDict(from_attributes=True)
