"""FastAPI router for prearmado stats endpoints.

Routes (all under prefix /api added in main.py):
  POST /api/prearmados/stats/batch   — batch exact/upgrade counts
  GET  /api/prearmados/stats/armadas — paginated armado prearmados with covers

Both endpoints require the permission ``produccion.ver_prearmadas_stats``
(seeded to ADMIN in migration 20260527_add_permiso_ver_prearmadas_stats.py;
grant to VENTAS/PRODUCCION manually from the permissions panel after deploy).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permiso
from app.core.database import get_async_db
from app.models.usuario import Usuario
from app.schemas.prearmado_stats import (
    ArmadasListResponse,
    BatchStatsRequest,
    BatchStatsResponse,
    CoverItem,
    ItemStats,
    ParsedEanResponse,
    PrearmadaArmadaItem,
)
from app.services.prearmado_stats_service import compute_batch_stats, get_armadas_list

router = APIRouter(prefix="/prearmados/stats", tags=["prearmados-stats"])


@router.post(
    "/batch",
    response_model=BatchStatsResponse,
    dependencies=[Depends(require_permiso("produccion.ver_prearmadas_stats"))],
)
async def stats_batch(
    body: BatchStatsRequest,
    request: Request,
    force_refresh: bool = Query(default=False, alias="force_refresh"),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_async_db),
) -> BatchStatsResponse:
    """Return exact/upgrade prearmado counts for a batch of item_ids.

    - Items not found in tb_item → returned as {exact: 0, upgrade: 0} (never 404).
    - Non-combo item codes (no '-') → returned as {exact: 0, upgrade: 0}.
    - Results are cached in Redis with TTL = PREARMADAS_STATS_CACHE_TTL_SECONDS.
    - ``?force_refresh=1`` bypasses the read cache and resets TTL after compute.
    - Multi-tenant: queries are scoped to current_user.comp_id.
    """
    redis = getattr(request.app.state, "redis", None)
    item_ids = [item.item_id for item in body.items]

    stats_raw, cache_status = await compute_batch_stats(
        item_ids=item_ids,
        comp_id=current_user.comp_id,
        db=db,
        redis=redis,
        force_refresh=force_refresh,
    )

    stats = {k: ItemStats(**v) for k, v in stats_raw.items()}

    return BatchStatsResponse(
        stats=stats,
        generated_at=datetime.now(UTC),
        cache=cache_status,
    )


@router.get(
    "/armadas",
    response_model=ArmadasListResponse,
    dependencies=[Depends(require_permiso("produccion.ver_prearmadas_stats"))],
)
async def stats_armadas(
    request: Request,
    ean_base: Optional[str] = Query(default=None, description="Filter by EAN base prefix (e.g. 'LENOVO')"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_async_db),
) -> ArmadasListResponse:
    """Return paginated armado prearmados enriched with covers[].

    covers[] lists every combo item in tb_item (same comp_id) that this
    prearmado covers via exact match or Windows upgrade.  No Redis cache —
    sellers need fresh data and call cadence is low.

    Query params:
      ean_base  : filter by combo_item_code prefix (server-side)
      page      : 1-based page number
      page_size : items per page (max 200)

    Multi-tenant: queries are scoped to current_user.comp_id.
    """
    items_raw, total = get_armadas_list(
        comp_id=current_user.comp_id,
        db=db,
        ean_base_filter=ean_base,
        page=page,
        page_size=page_size,
    )

    items = []
    for row in items_raw:
        parsed_data = row.get("parsed") or {}
        covers = [
            CoverItem(
                item_id=c["item_id"],
                item_code=c["item_code"],
                item_desc=c.get("item_desc"),
                classification=c["classification"],
            )
            for c in row.get("covers", [])
        ]
        items.append(
            PrearmadaArmadaItem(
                prearmado_id=row["prearmado_id"],
                codigo=row["codigo"],
                combo_item_id=row["combo_item_id"],
                combo_item_code=row["combo_item_code"],
                combo_item_desc=row.get("combo_item_desc"),
                incluye_windows=row.get("incluye_windows"),
                parsed=ParsedEanResponse(**parsed_data),
                covers=covers,
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        )

    return ArmadasListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )
