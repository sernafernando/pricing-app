"""
Router para ML Seller Promotions (Central de Promociones de MercadoLibre).

PR1 — READ-ONLY: lista promociones y sus items desde ml_promotions /
ml_item_promotions (tabla mlwebhook), leídas via ml_promotions_service.

PR2 — WRITE: enroll/remove de un item en una promoción vía el proxy
ml-webhook, orquestado por ml_promotions_write_service. Gated por
`promos.escribir` (independiente del gate de lectura `promos.ver`) y por
el kill-switch `PROMOS_WRITE_ENABLED` (chequeado dentro del servicio,
ANTES de cualquier llamada al proxy).
"""

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.usuario import Usuario
from app.services.ml_promotions_pricing import enriquecer_markup_por_promo
from app.services.ml_promotions_service import (
    derivar_application_status,
    fetch_item_promotions,
    fetch_promotion_items,
    fetch_promotions,
)
from app.services.ml_promotions_write_service import enroll_one_item, remove_one_item
from app.services.permisos_service import PermisosService

logger = get_logger(__name__)

router = APIRouter(prefix="/promociones", tags=["ML Seller Promotions"])


# ── Schemas ──────────────────────────────────────────────────────


class PromotionItem(BaseModel):
    """Una fila de ml_promotions."""

    promotion_id: str
    promotion_type: Optional[str] = None
    sub_type: Optional[str] = None
    status: Optional[str] = None
    name: Optional[str] = None
    start_date: Optional[Any] = None
    finish_date: Optional[Any] = None
    deadline_date: Optional[Any] = None
    payload: Dict[str, Any] = {}
    updated_at: Optional[Any] = None

    model_config = ConfigDict(from_attributes=True)


class PromotionsList(BaseModel):
    """Respuesta del listado de promociones."""

    count: int
    promotions: List[PromotionItem]

    model_config = ConfigDict(from_attributes=True)


class ItemPromotion(BaseModel):
    """Una fila de ml_item_promotions."""

    mla: str
    promotion_id: str
    promotion_type: Optional[str] = None
    sub_type: Optional[str] = None
    status: Optional[str] = None
    original_price: Optional[float] = None
    price: Optional[float] = None
    min_discounted_price: Optional[float] = None
    max_discounted_price: Optional[float] = None
    suggested_discounted_price: Optional[float] = None
    payload: Dict[str, Any] = {}
    updated_at: Optional[Any] = None
    start_date: Optional[str] = None
    finish_date: Optional[str] = None
    application_status: Optional[str] = None
    """Derived (never stored): `'active'` for the `started` promo with the
    minimum price on this item (ties -> all tied are `'active'`; null price
    -> `'active'`), `'programmed'` for other `started` promos, `None` for
    `candidate` (not applied). Only meaningful on
    `GET /promociones/item/{mla_id}`; see `derivar_application_status`."""
    nuestro_markup: Optional[float] = None
    """Seller's markup percentage on the promo's effective revenue
    (effective discounted price + ML co-funding when applicable). Computed
    server-side; None when cost/publication is unresolvable. Only populated
    on `GET /promociones/item/{mla_id}` (per-item read); absent/None on the
    per-promotion listing (`GET /promociones/{promotion_id}/items`)."""

    model_config = ConfigDict(from_attributes=True)


class PromotionItemsList(BaseModel):
    """Respuesta del listado de items de una promoción."""

    count: int
    items: List[ItemPromotion]

    model_config = ConfigDict(from_attributes=True)


class ItemPromotionsList(BaseModel):
    """Respuesta de las promociones de un item puntual."""

    mla: str
    count: int
    promotions: List[ItemPromotion]

    model_config = ConfigDict(from_attributes=True)


# ── Write schemas (PR2) ──────────────────────────────────────────


class EnrollRequest(BaseModel):
    """Body del POST de inscripción a una promoción."""

    promotion_id: str
    promotion_type: str
    deal_price: Optional[float] = None
    top_deal_price: Optional[float] = None


class EnrollResult(BaseModel):
    """Resultado de un enroll. Expresa "enviado", NO "confirmado-inscripto":
    ml_item_promotions es la fuente de verdad; un 201 puede seguir
    mostrando `candidate` en una lectura inmediata (~2s) sin que eso sea
    una falla."""

    submitted: bool
    status: Literal[
        "submitted",
        "reconciled_applied",
        "reconciled_not_applied",
        "ambiguous",
        "disabled",
        "rejected_out_of_range",
        "rejected_unsupported_type",
        "rejected_by_proxy",
        "rejected_read_unavailable",
        "rejected_promotion_not_found",
        "rejected_price_unresolved",
    ]
    price: Optional[float] = None
    status_code: Optional[int] = None
    detail: Optional[Any] = None
    reconciled_row: Optional[Dict[str, Any]] = None
    offer_id: Optional[str] = None
    """SMART-only: the authoritative new offer_id ("OFFER-MLA...-N")
    returned by ML in the 201 response. None for SELLER_CAMPAIGN/DEAL
    (which have no offer_id concept) or when not yet submitted."""

    model_config = ConfigDict(from_attributes=True)


class RemoveResult(BaseModel):
    """Resultado de un remove. Mismo contrato de estados que EnrollResult
    (sin `price`, no aplica a una remoción)."""

    submitted: bool
    status: Literal[
        "submitted",
        "reconciled_applied",
        "reconciled_not_applied",
        "ambiguous",
        "disabled",
        "rejected_unsupported_type",
        "rejected_by_proxy",
    ]
    status_code: Optional[int] = None
    detail: Optional[Any] = None
    reconciled_row: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


# ── Write outcome -> HTTP status mapping ─────────────────────────
#
# Definitive rejections (kill-switch, validation, unresolved price,
# unreachable live read, proxy 4xx) are NEVER a plain 200 — the request
# was not fulfilled. `ambiguous` (write submitted, outcome genuinely
# unknown) is 202 Accepted, not 200/500. `reconciled_*` and `submitted`
# are 200 — the write was attempted/confirmed, informational body.
_WRITE_STATUS_TO_HTTP = {
    "disabled": status.HTTP_403_FORBIDDEN,
    "rejected_out_of_range": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "rejected_unsupported_type": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "rejected_price_unresolved": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "rejected_promotion_not_found": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "rejected_read_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "rejected_by_proxy": status.HTTP_422_UNPROCESSABLE_ENTITY,
}


# ── Permission helpers ───────────────────────────────────────────


def require_promos_read():
    """Dependency: requiere permiso promos.ver."""

    def _check(
        current_user: Usuario = Depends(get_current_user),
        db=Depends(get_db),
    ) -> Usuario:
        permisos_service = PermisosService(db)
        if not permisos_service.tiene_permiso(current_user, "promos.ver"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso: promos.ver",
            )
        return current_user

    return _check


def require_promos_write():
    """Dependency: requiere permiso promos.escribir (independiente de
    promos.ver — un usuario puede leer sin poder escribir)."""

    def _check(
        current_user: Usuario = Depends(get_current_user),
        db=Depends(get_db),
    ) -> Usuario:
        permisos_service = PermisosService(db)
        if not permisos_service.tiene_permiso(current_user, "promos.escribir"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso: promos.escribir",
            )
        return current_user

    return _check


def _raise_if_write_rejected(outcome: Dict[str, Any]) -> None:
    """Maps a definitive write-service rejection status to the matching
    HTTP error (see `_WRITE_STATUS_TO_HTTP`).

    Statuses not in that map (submitted, reconciled_*, ambiguous) are NOT
    request-validation failures — the write was attempted/confirmed, and
    the caller handles their HTTP status separately (200 vs 202 Accepted
    for `ambiguous`).
    """
    http_status = _WRITE_STATUS_TO_HTTP.get(outcome["status"])
    if http_status is not None:
        raise HTTPException(status_code=http_status, detail=outcome.get("detail") or outcome["status"])


# ── Endpoints ────────────────────────────────────────────────────


@router.get("", response_model=PromotionsList)
def listar_promociones(
    current_user: Usuario = Depends(require_promos_read()),
) -> PromotionsList:
    """
    Lista las promociones del vendedor desde ml_promotions (tabla mlwebhook).
    Requiere permiso: promos.ver
    """
    try:
        promotions = fetch_promotions()
        return PromotionsList(count=len(promotions), promotions=promotions)
    except RuntimeError as e:
        logger.error("ML_WEBHOOK_DB_URL not configured: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Base de datos mlwebhook no disponible",
        )
    except Exception as e:
        logger.error("Error querying ml_promotions: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al consultar promociones",
        )


@router.get("/item/{mla_id}", response_model=ItemPromotionsList)
def obtener_promociones_item(
    mla_id: str,
    current_user: Usuario = Depends(require_promos_read()),
    db=Depends(get_db),
) -> ItemPromotionsList:
    """
    Lista las promociones aplicables a un item desde ml_item_promotions
    (fuente de verdad del estado final: candidate|started|finished), con el
    markup del vendedor ("nuestro_markup") calculado server-side sobre la
    revenue efectiva de cada promo (ver `enriquecer_markup_por_promo`).
    Requiere permiso: promos.ver
    """
    try:
        # active_only: the backfilled table is upsert-only (no stale cleanup), so
        # finished promos can linger — show only candidate|started as real options.
        promotions = fetch_item_promotions(mla_id, active_only=True)
        # A single item can be legitimately `started` (enrolled) in MULTIPLE
        # promos at once: ML applies only the lowest-price one and leaves
        # the rest programmed (scheduled). ML's API does not distinguish
        # active from programmed (both show `started`), so it must be
        # derived here.
        promotions = derivar_application_status(promotions)
        promotions = enriquecer_markup_por_promo(db, mla_id, promotions)
        return ItemPromotionsList(mla=mla_id, count=len(promotions), promotions=promotions)
    except RuntimeError as e:
        logger.error("ML_WEBHOOK_DB_URL not configured: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Base de datos mlwebhook no disponible",
        )
    except Exception as e:
        logger.error("Error querying ml_item_promotions for %s: %s", mla_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al consultar promociones del item",
        )


@router.get("/{promotion_id}/items", response_model=PromotionItemsList)
def listar_items_de_promocion(
    promotion_id: str,
    promotion_type: str = Query(..., description="Tipo de promoción (requerido)"),
    current_user: Usuario = Depends(require_promos_read()),
) -> PromotionItemsList:
    """
    Lista los items de una promoción puntual desde ml_item_promotions.
    `promotion_type` es requerido (para PRICE_DISCOUNT, promotion_id ==
    promotion_type).
    Requiere permiso: promos.ver
    """
    try:
        items = fetch_promotion_items(promotion_id, promotion_type)
        return PromotionItemsList(count=len(items), items=items)
    except RuntimeError as e:
        logger.error("ML_WEBHOOK_DB_URL not configured: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Base de datos mlwebhook no disponible",
        )
    except Exception as e:
        logger.error("Error querying ml_item_promotions for promotion %s: %s", promotion_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al consultar items de la promoción",
        )


# ── Write endpoints (PR2) ────────────────────────────────────────


@router.post("/item/{mla_id}", response_model=EnrollResult)
def inscribir_item_en_promocion(
    mla_id: str,
    body: EnrollRequest,
    response: Response,
    current_user: Usuario = Depends(require_promos_write()),
) -> EnrollResult:
    """
    Inscribe un item en una promoción (SELLER_CAMPAIGN, DEAL o SMART) vía el proxy
    ml-webhook. Gated por PROMOS_WRITE_ENABLED (kill-switch, chequeado en
    el servicio ANTES de cualquier llamada al proxy) y por el permiso
    promos.escribir.

    Devuelve un resultado de "enviado" (submitted), NO "confirmado
    inscripto": ml_item_promotions es la fuente de verdad; una lectura
    inmediata puede seguir mostrando `candidate` sin que eso sea una
    falla (ver EnrollResult).

    Requiere permiso: promos.escribir
    """
    try:
        outcome = enroll_one_item(
            mla_id,
            body.promotion_id,
            body.promotion_type,
            deal_price=body.deal_price,
            top_deal_price=body.top_deal_price,
        )
    except RuntimeError as e:
        logger.error("ML_WEBHOOK_DB_URL not configured: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Base de datos mlwebhook no disponible",
        )

    _raise_if_write_rejected(outcome)
    if outcome["status"] == "ambiguous":
        response.status_code = status.HTTP_202_ACCEPTED
    return EnrollResult(**outcome)


@router.delete("/item/{mla_id}", response_model=RemoveResult)
def remover_item_de_promocion(
    mla_id: str,
    response: Response,
    promotion_type: str = Query(..., description="Tipo de promoción (requerido)"),
    promotion_id: str = Query(..., description="ID de la promoción (requerido)"),
    current_user: Usuario = Depends(require_promos_write()),
) -> RemoveResult:
    """
    Remueve un item de una promoción (SELLER_CAMPAIGN, DEAL o SMART) vía el proxy
    ml-webhook. Mismo contrato de kill-switch/permisos que el enroll.

    Requiere permiso: promos.escribir
    """
    try:
        outcome = remove_one_item(mla_id, promotion_type, promotion_id)
    except RuntimeError as e:
        logger.error("ML_WEBHOOK_DB_URL not configured: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Base de datos mlwebhook no disponible",
        )

    _raise_if_write_rejected(outcome)
    if outcome["status"] == "ambiguous":
        response.status_code = status.HTTP_202_ACCEPTED
    return RemoveResult(**outcome)
