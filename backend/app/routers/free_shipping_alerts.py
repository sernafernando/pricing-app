"""
Router para alertas de Free Shipping Error.

Lee directamente de la BD mlwebhook (ml_previews) los items que tienen
free_shipping_error=true, es decir: envío gratis activado pero precio
rebate < $33.000.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.core.database import get_mlwebhook_engine
from app.core.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/free-shipping-alerts", tags=["Free Shipping Alerts"])

# ── Schemas ──────────────────────────────────────────────────────


class FreeShippingAlertItem(BaseModel):
    """Un item con free_shipping_error=true."""

    resource: str
    mla_id: str
    title: Optional[str] = None
    price: Optional[float] = None
    currency_id: Optional[str] = None
    brand: Optional[str] = None
    item_status: Optional[str] = None
    rebate_price: Optional[float] = None
    logistic_type: Optional[str] = None
    shipping_mode: Optional[str] = None
    shipping_tags: Optional[list] = None
    mandatory_free_shipping: bool = False
    last_updated: Optional[str] = None
    ml_url: str

    model_config = ConfigDict(from_attributes=True)


class FreeShippingAlertSummary(BaseModel):
    """Resumen para el badge del topbar."""

    count: int
    items: List[FreeShippingAlertItem]

    model_config = ConfigDict(from_attributes=True)


# ── Helpers ──────────────────────────────────────────────────────

QUERY_FREE_SHIPPING_ERRORS = text("""
    SELECT
        p.resource,
        p.title,
        p.price,
        p.currency_id,
        p.brand,
        p.status AS item_status,
        (p.extra_data->>'rebate_value_struct_number')::numeric AS rebate_price,
        p.extra_data->>'logistic_type' AS logistic_type,
        p.extra_data->>'shipping_mode' AS shipping_mode,
        p.extra_data->'shipping_tags' AS shipping_tags,
        p.last_updated
    FROM ml_previews p
    WHERE p.resource LIKE '/items/MLA%'
      AND (p.extra_data->>'free_shipping_error')::boolean = true
    ORDER BY p.last_updated DESC
""")

QUERY_COUNT_ONLY = text("""
    SELECT COUNT(*) AS cnt
    FROM ml_previews p
    WHERE p.resource LIKE '/items/MLA%'
      AND (p.extra_data->>'free_shipping_error')::boolean = true
""")


def _extract_mla_id(resource: str) -> str:
    """Extrae 'MLA1234567890' de '/items/MLA1234567890'."""
    return resource.replace("/items/", "")


def _build_ml_url(mla_id: str) -> str:
    """Construye la URL de MercadoLibre para buscar la publicacion."""
    return (
        "https://www.mercadolibre.com.ar/publicaciones/listado"
        "?filters=OMNI_ACTIVE|OMNI_INACTIVE|CHANNEL_NO_PROXIMITY_AND_NO_MP_MERCHANTS"
        f"&page=1&search={mla_id}&sort=DEFAULT"
    )


def _parse_shipping_tags(raw_tags: object) -> tuple[list, bool]:
    """Parsea shipping_tags y detecta mandatory_free_shipping."""
    import json

    tags = []
    if raw_tags is not None:
        if isinstance(raw_tags, str):
            try:
                tags = json.loads(raw_tags)
            except (json.JSONDecodeError, TypeError):
                tags = []
        elif isinstance(raw_tags, list):
            tags = raw_tags
    mandatory = "mandatory_free_shipping" in tags
    return tags, mandatory


def _row_to_item(row: object) -> FreeShippingAlertItem:
    """Convierte una fila de la query en un schema."""
    resource = row.resource
    mla_id = _extract_mla_id(resource)
    tags, mandatory = _parse_shipping_tags(row.shipping_tags)

    return FreeShippingAlertItem(
        resource=resource,
        mla_id=mla_id,
        title=row.title,
        price=float(row.price) if row.price is not None else None,
        currency_id=row.currency_id,
        brand=row.brand,
        item_status=row.item_status,
        rebate_price=float(row.rebate_price) if row.rebate_price is not None else None,
        logistic_type=row.logistic_type,
        shipping_mode=row.shipping_mode,
        shipping_tags=tags,
        mandatory_free_shipping=mandatory,
        last_updated=row.last_updated.isoformat() if row.last_updated else None,
        ml_url=_build_ml_url(mla_id),
    )


# ── Permission helper ────────────────────────────────────────────


def require_free_shipping_permission():
    """Dependency: requiere permiso alertas.ver_free_shipping."""
    from sqlalchemy.orm import Session

    def _check(
        current_user: Usuario = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> Usuario:
        permisos_service = PermisosService(db)
        if not permisos_service.tiene_permiso(current_user, "alertas.ver_free_shipping"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso: alertas.ver_free_shipping",
            )
        return current_user

    return _check


# ── Endpoints ────────────────────────────────────────────────────


@router.get("/count", response_model=dict)
def obtener_count_free_shipping_errors(
    current_user: Usuario = Depends(require_free_shipping_permission()),
) -> dict:
    """
    Devuelve solo la cantidad de items con free_shipping_error.
    Endpoint liviano para el badge del TopBar.
    Requiere permiso: alertas.ver_free_shipping
    """
    try:
        engine = get_mlwebhook_engine()
        with engine.connect() as conn:
            result = conn.execute(QUERY_COUNT_ONLY)
            row = result.fetchone()
            count = row.cnt if row else 0
        return {"count": count}
    except RuntimeError as e:
        logger.error("ML_WEBHOOK_DB_URL not configured: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Base de datos mlwebhook no disponible",
        )
    except Exception as e:
        logger.error("Error querying free_shipping_errors count: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al consultar alertas de envío gratis",
        )


@router.get("", response_model=FreeShippingAlertSummary)
def obtener_free_shipping_errors(
    current_user: Usuario = Depends(require_free_shipping_permission()),
) -> FreeShippingAlertSummary:
    """
    Lista todos los items con free_shipping_error=true.
    Incluye datos de precio, rebate, shipping, y URL de ML.
    Requiere permiso: alertas.ver_free_shipping
    """
    try:
        engine = get_mlwebhook_engine()
        with engine.connect() as conn:
            result = conn.execute(QUERY_FREE_SHIPPING_ERRORS)
            rows = result.fetchall()

        items = [_row_to_item(row) for row in rows]
        return FreeShippingAlertSummary(count=len(items), items=items)
    except RuntimeError as e:
        logger.error("ML_WEBHOOK_DB_URL not configured: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Base de datos mlwebhook no disponible",
        )
    except Exception as e:
        logger.error("Error querying free_shipping_errors: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al consultar alertas de envío gratis",
        )
