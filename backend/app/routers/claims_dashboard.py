"""
Claims Dashboard — Centralized view of ALL MercadoLibre claims.

Endpoints:
- POST /sync       — Fetch all open claims from ML search API, enrich and cache locally
- GET  /            — List claims from local cache with filters + pagination
- GET  /stats       — Summary counters for dashboard cards
- GET  /{claim_id}  — Single claim detail from cache (enriches if stale)

Uses the same cache table (rma_claims_ml) and enrichment logic as seriales.py,
so claims fetched here are also available in traza views and vice-versa.
"""

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, case, text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.rma_claim_ml import RmaClaimML
from app.models.rma_caso import RmaCaso
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService

# Reuse the ML proxy and enrichment machinery from seriales
from app.routers.seriales import (
    ML_WEBHOOK_RENDER_URL,
    _HTTPX_TIMEOUT,
    _build_claim_from_db_cache,
    _enrich_claim_via_http,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/claims-dashboard", tags=["claims-dashboard"])


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _check_permiso(db: Session, user: Usuario, permiso: str) -> None:
    if not PermisosService.tiene_permiso(db, user, permiso):
        raise HTTPException(status_code=403, detail=f"Sin permiso: {permiso}")


# ──────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────


class SyncResponse(BaseModel):
    ok: bool = True
    total_from_ml: int
    new_cached: int
    updated: int
    already_current: int
    errors: int
    mensaje: str


class ClaimListItem(BaseModel):
    """Lightweight claim for the dashboard list — no nested sub-models."""

    id: int
    claim_id: int
    resource_id: Optional[int] = None
    claim_type: Optional[str] = None
    claim_stage: Optional[str] = None
    status: Optional[str] = None
    reason_id: Optional[str] = None
    reason_category: Optional[str] = None
    reason_detail: Optional[str] = None
    detail_title: Optional[str] = None
    detail_problem: Optional[str] = None
    action_responsible: Optional[str] = None
    triage_tags: Optional[list] = None
    expected_resolutions: Optional[list] = None
    seller_actions: Optional[list] = None
    mandatory_actions: Optional[list] = None
    nearest_due_date: Optional[str] = None
    fulfilled: Optional[bool] = None
    affects_reputation: Optional[bool] = None
    has_incentive: Optional[bool] = None
    resolution_reason: Optional[str] = None
    resolution_closed_by: Optional[str] = None
    messages_total: Optional[int] = None
    ml_date_created: Optional[str] = None
    ml_last_updated: Optional[str] = None
    updated_at: Optional[str] = None
    # RMA link
    rma_caso_id: Optional[int] = None
    rma_numero_caso: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ClaimListResponse(BaseModel):
    items: list[ClaimListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class ClaimStatsResponse(BaseModel):
    total_abiertos: int = 0
    total_cerrados: int = 0
    en_disputa: int = 0
    accion_vendedor: int = 0
    con_caso_rma: int = 0
    sin_caso_rma: int = 0
    por_etapa: list[dict] = []
    por_tipo: list[dict] = []
    por_categoria: list[dict] = []


# ──────────────────────────────────────────────
# POST /sync — Fetch open claims from ML and cache
# ──────────────────────────────────────────────


@router.post("/sync", response_model=SyncResponse)
async def sync_claims(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> SyncResponse:
    """Sync all open claims from MercadoLibre search API into local cache.

    1. Calls /claims/search?status=opened with pagination to get all open claims
    2. For each claim, checks if already cached and current
    3. If not cached or stale, enriches via 7+ HTTP endpoints and saves
    4. Returns summary of what was synced

    This is a potentially slow operation (~5-30s depending on claim count).
    """
    _check_permiso(db, current_user, "rma.gestionar")

    # Step 1: Fetch all open claim IDs from ML search
    all_claim_ids: list[int] = []
    offset = 0
    limit = 100  # ML max per page

    try:
        with httpx.Client(timeout=_HTTPX_TIMEOUT * 2) as client:
            while True:
                resource = (
                    f"/post-purchase/v1/claims/search"
                    f"?status=opened&sort=last_updated:desc&offset={offset}&limit={limit}"
                )
                resp = client.get(
                    ML_WEBHOOK_RENDER_URL,
                    params={"resource": resource, "format": "json"},
                )
                if resp.status_code != 200:
                    logger.warning("ML search failed (status=%d): %s", resp.status_code, resp.text[:500])
                    break

                search_data = resp.json()
                claims_page = search_data.get("data", [])
                paging = search_data.get("paging", {})
                total = paging.get("total", 0)

                for c in claims_page:
                    cid = c.get("id")
                    if cid:
                        all_claim_ids.append(int(cid))

                offset += limit
                if offset >= total or not claims_page:
                    break

    except Exception:
        logger.exception("Error fetching open claims from ML search")
        raise HTTPException(status_code=502, detail="Error connecting to MercadoLibre API")

    if not all_claim_ids:
        return SyncResponse(
            total_from_ml=0,
            new_cached=0,
            updated=0,
            already_current=0,
            errors=0,
            mensaje="No se encontraron claims abiertos en ML",
        )

    # Step 2: Check which claims are already cached
    existing = {row.claim_id: row for row in db.query(RmaClaimML).filter(RmaClaimML.claim_id.in_(all_claim_ids)).all()}

    new_cached = 0
    updated = 0
    already_current = 0
    errors = 0

    for claim_id in all_claim_ids:
        cached = existing.get(claim_id)

        if cached and cached.status == "closed":
            # Closed claims are immutable
            already_current += 1
            continue

        # Enrich via HTTP (this also saves to cache via _save_claim_to_cache)
        try:
            result = _enrich_claim_via_http(str(claim_id))
            if result:
                if cached:
                    updated += 1
                else:
                    new_cached += 1
            else:
                errors += 1
        except Exception:
            logger.exception("Error enriching claim %d", claim_id)
            errors += 1

    return SyncResponse(
        total_from_ml=len(all_claim_ids),
        new_cached=new_cached,
        updated=updated,
        already_current=already_current,
        errors=errors,
        mensaje=(
            f"Sync completado: {len(all_claim_ids)} claims de ML, "
            f"{new_cached} nuevos, {updated} actualizados, "
            f"{already_current} ya vigentes, {errors} errores"
        ),
    )


# ──────────────────────────────────────────────
# GET / — List claims from local cache
# ──────────────────────────────────────────────


@router.get("", response_model=ClaimListResponse)
async def listar_claims(
    status: Optional[str] = Query(None, description="opened, closed"),
    stage: Optional[str] = Query(None, description="claim, dispute, recontact, stale"),
    claim_type: Optional[str] = Query(None, description="mediations, return, fulfillment"),
    reason_category: Optional[str] = Query(None, description="PDD, PNR, CS"),
    action_responsible: Optional[str] = Query(None, description="seller, buyer, mediator"),
    has_rma: Optional[bool] = Query(None, description="Only claims with/without RMA caso"),
    search: Optional[str] = Query(None, description="Search in reason_detail, detail_title"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort: str = Query("last_updated", description="Sort field"),
    sort_dir: str = Query("desc", description="asc or desc"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ClaimListResponse:
    """List claims from local cache with filters, pagination, and RMA link info."""
    _check_permiso(db, current_user, "rma.ver")

    query = db.query(RmaClaimML)

    # Filters
    if status:
        query = query.filter(RmaClaimML.status == status)
    if stage:
        query = query.filter(RmaClaimML.claim_stage == stage)
    if claim_type:
        query = query.filter(RmaClaimML.claim_type == claim_type)
    if reason_category:
        query = query.filter(RmaClaimML.reason_category == reason_category)
    if action_responsible:
        query = query.filter(RmaClaimML.action_responsible == action_responsible)
    if search:
        like_term = f"%{search}%"
        query = query.filter(
            (RmaClaimML.reason_detail.ilike(like_term))
            | (RmaClaimML.detail_title.ilike(like_term))
            | (RmaClaimML.detail_problem.ilike(like_term))
            | (func.cast(RmaClaimML.claim_id, text("text")).ilike(like_term))
            | (func.cast(RmaClaimML.resource_id, text("text")).ilike(like_term))
        )

    # Total
    total = query.count()

    # Sort
    sort_col = getattr(RmaClaimML, sort, RmaClaimML.ml_last_updated)
    if sort_dir == "asc":
        query = query.order_by(sort_col.asc().nullslast())
    else:
        query = query.order_by(sort_col.desc().nullsfirst())

    # Pagination
    total_pages = max(1, (total + page_size - 1) // page_size)
    claims = query.offset((page - 1) * page_size).limit(page_size).all()

    # Bulk fetch RMA caso links for all resource_ids in this page
    resource_ids = [c.resource_id for c in claims if c.resource_id]
    resource_id_strs = [str(rid) for rid in resource_ids]

    rma_map: dict[str, tuple[int, str]] = {}
    if resource_id_strs:
        rma_cases = (
            db.query(RmaCaso.ml_id, RmaCaso.id, RmaCaso.numero_caso)
            .filter(RmaCaso.ml_id.in_(resource_id_strs), RmaCaso.activo == True)  # noqa: E712
            .all()
        )
        for ml_id, caso_id, numero_caso in rma_cases:
            rma_map[ml_id] = (caso_id, numero_caso)

    # Build response items
    items = []
    for c in claims:
        rma_info = rma_map.get(str(c.resource_id)) if c.resource_id else None
        items.append(
            ClaimListItem(
                id=c.id,
                claim_id=c.claim_id,
                resource_id=c.resource_id,
                claim_type=c.claim_type,
                claim_stage=c.claim_stage,
                status=c.status,
                reason_id=c.reason_id,
                reason_category=c.reason_category,
                reason_detail=c.reason_detail or c.reason_name,
                detail_title=c.detail_title,
                detail_problem=c.detail_problem,
                action_responsible=c.action_responsible,
                triage_tags=c.triage_tags,
                expected_resolutions=c.expected_resolutions,
                seller_actions=c.seller_actions,
                mandatory_actions=c.mandatory_actions,
                nearest_due_date=c.nearest_due_date,
                fulfilled=c.fulfilled,
                affects_reputation=c.affects_reputation,
                has_incentive=c.has_incentive,
                resolution_reason=c.resolution_reason,
                resolution_closed_by=c.resolution_closed_by,
                messages_total=c.messages_total,
                ml_date_created=c.ml_date_created,
                ml_last_updated=c.ml_last_updated,
                updated_at=c.updated_at.isoformat() if c.updated_at else None,
                rma_caso_id=rma_info[0] if rma_info else None,
                rma_numero_caso=rma_info[1] if rma_info else None,
            )
        )

    # Filter has_rma AFTER building items (needs rma_map)
    if has_rma is True:
        items = [i for i in items if i.rma_caso_id is not None]
        total = len(items)
    elif has_rma is False:
        items = [i for i in items if i.rma_caso_id is None]
        total = len(items)

    return ClaimListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ──────────────────────────────────────────────
# GET /stats — Summary counters
# ──────────────────────────────────────────────


@router.get("/stats", response_model=ClaimStatsResponse)
async def claim_stats(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ClaimStatsResponse:
    """Aggregate stats for dashboard cards."""
    _check_permiso(db, current_user, "rma.ver")

    # Status counts
    status_counts = db.query(
        func.count(case((RmaClaimML.status == "opened", 1))).label("abiertos"),
        func.count(case((RmaClaimML.status == "closed", 1))).label("cerrados"),
        func.count(
            case(
                (
                    (RmaClaimML.status == "opened") & (RmaClaimML.claim_stage == "dispute"),
                    1,
                )
            )
        ).label("en_disputa"),
        func.count(
            case(
                (
                    (RmaClaimML.status == "opened") & (RmaClaimML.action_responsible == "seller"),
                    1,
                )
            )
        ).label("accion_vendedor"),
    ).first()

    total_abiertos = status_counts.abiertos or 0
    total_cerrados = status_counts.cerrados or 0
    en_disputa = status_counts.en_disputa or 0
    accion_vendedor = status_counts.accion_vendedor or 0

    # RMA link counts (only for open claims)
    open_resource_ids = [
        str(r[0])
        for r in db.query(RmaClaimML.resource_id)
        .filter(RmaClaimML.status == "opened", RmaClaimML.resource_id.isnot(None))
        .all()
    ]

    con_rma = 0
    if open_resource_ids:
        con_rma = (
            db.query(func.count(RmaCaso.id))
            .filter(RmaCaso.ml_id.in_(open_resource_ids), RmaCaso.activo == True)  # noqa: E712
            .scalar()
            or 0
        )
    sin_rma = total_abiertos - con_rma

    # By stage (open claims only)
    por_etapa = [
        {"valor": row[0] or "sin_etapa", "cantidad": row[1]}
        for row in db.query(RmaClaimML.claim_stage, func.count(RmaClaimML.id))
        .filter(RmaClaimML.status == "opened")
        .group_by(RmaClaimML.claim_stage)
        .all()
    ]

    # By type (open claims only)
    por_tipo = [
        {"valor": row[0] or "sin_tipo", "cantidad": row[1]}
        for row in db.query(RmaClaimML.claim_type, func.count(RmaClaimML.id))
        .filter(RmaClaimML.status == "opened")
        .group_by(RmaClaimML.claim_type)
        .all()
    ]

    # By reason category (open claims only)
    por_categoria = [
        {"valor": row[0] or "sin_categoria", "cantidad": row[1]}
        for row in db.query(RmaClaimML.reason_category, func.count(RmaClaimML.id))
        .filter(RmaClaimML.status == "opened")
        .group_by(RmaClaimML.reason_category)
        .all()
    ]

    return ClaimStatsResponse(
        total_abiertos=total_abiertos,
        total_cerrados=total_cerrados,
        en_disputa=en_disputa,
        accion_vendedor=accion_vendedor,
        con_caso_rma=con_rma,
        sin_caso_rma=sin_rma,
        por_etapa=por_etapa,
        por_tipo=por_tipo,
        por_categoria=por_categoria,
    )


# ──────────────────────────────────────────────
# GET /{claim_id} — Single claim detail
# ──────────────────────────────────────────────


@router.get("/{claim_id}")
async def obtener_claim(
    claim_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Get a single claim detail. If cached, returns from cache. Otherwise enriches."""
    _check_permiso(db, current_user, "rma.ver")

    cached = db.query(RmaClaimML).filter(RmaClaimML.claim_id == claim_id).first()

    if cached:
        claim = _build_claim_from_db_cache(cached)
    else:
        # Try to enrich from ML
        claim = _enrich_claim_via_http(str(claim_id))
        if not claim:
            raise HTTPException(status_code=404, detail=f"Claim {claim_id} no encontrado en ML")

    # Check if there's a linked RMA caso
    rma_info = None
    if claim.resource_id:
        rma_caso = (
            db.query(RmaCaso.id, RmaCaso.numero_caso)
            .filter(RmaCaso.ml_id == claim.resource_id, RmaCaso.activo == True)  # noqa: E712
            .first()
        )
        if rma_caso:
            rma_info = {"caso_id": rma_caso.id, "numero_caso": rma_caso.numero_caso}

    return {
        "claim": claim.model_dump(),
        "rma": rma_info,
    }
