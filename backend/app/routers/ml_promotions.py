"""
Router para ML Seller Promotions (Central de Promociones de MercadoLibre).

PR1 — READ-ONLY: lista promociones y sus items desde ml_promotions /
ml_item_promotions (tabla mlwebhook), leídas via ml_promotions_service.

Escritura (enroll/remove vía proxy ml-webhook, gated por
PROMOS_WRITE_ENABLED) se agrega en PR2.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.usuario import Usuario
from app.services.ml_promotions_service import (
    fetch_item_promotions,
    fetch_promotion_items,
    fetch_promotions,
)
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


# ── Permission helper ────────────────────────────────────────────


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
) -> ItemPromotionsList:
    """
    Lista las promociones aplicables a un item desde ml_item_promotions
    (fuente de verdad del estado final: candidate|started|finished).
    Requiere permiso: promos.ver
    """
    try:
        promotions = fetch_item_promotions(mla_id)
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
        logger.error(
            "Error querying ml_item_promotions for promotion %s: %s", promotion_id, e, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al consultar items de la promoción",
        )
