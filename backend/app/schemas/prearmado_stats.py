"""Pydantic schemas for prearmado stats endpoints.

Endpoints:
  POST /api/prearmados/stats/batch  → BatchStatsRequest / BatchStatsResponse
  GET  /api/prearmados/stats/armadas → ArmadasListResponse
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# POST /api/prearmados/stats/batch
# ---------------------------------------------------------------------------


class BatchStatsItem(BaseModel):
    """A single item in the batch stats request."""

    item_id: int
    ean: Optional[str] = None  # overrides item_code lookup when provided


class BatchStatsRequest(BaseModel):
    """Request body for POST /api/prearmados/stats/batch."""

    items: List[BatchStatsItem] = Field(min_length=1, max_length=100)


class ItemStats(BaseModel):
    """Exact/upgrade counts for a single item_id."""

    exact: int
    upgrade: int


class BatchStatsResponse(BaseModel):
    """Response for POST /api/prearmados/stats/batch."""

    stats: Dict[str, ItemStats]
    generated_at: datetime
    cache: Literal["hit", "miss", "partial"]


# ---------------------------------------------------------------------------
# GET /api/prearmados/stats/armadas
# ---------------------------------------------------------------------------


class ParsedEanResponse(BaseModel):
    """Parsed EAN components for a prearmado combo item."""

    ean_base: Optional[str] = None
    memoria: Optional[str] = None
    disco: Optional[str] = None
    windows: Optional[Literal["home", "pro"]] = None


class CoverItem(BaseModel):
    """A tb_item row that this prearmado covers (exact or upgrade)."""

    item_id: int
    item_code: str
    item_desc: Optional[str] = None
    classification: Literal["exact", "upgrade"]


class PrearmadaArmadaItem(BaseModel):
    """A single armado prearmado row enriched with parsed EAN and covers list."""

    model_config = ConfigDict(from_attributes=True)

    prearmado_id: int
    codigo: str
    combo_item_id: int
    combo_item_code: str
    combo_item_desc: Optional[str] = None
    incluye_windows: Optional[Literal["home", "pro"]] = None
    parsed: ParsedEanResponse
    covers: List[CoverItem]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ArmadasListResponse(BaseModel):
    """Response for GET /api/prearmados/stats/armadas."""

    total: int
    page: int
    page_size: int
    items: List[PrearmadaArmadaItem]
