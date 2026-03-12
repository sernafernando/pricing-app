"""
Router para alertas de Free Shipping Error.

Lee directamente de la BD mlwebhook (ml_previews) los items que tienen
free_shipping_error=true, es decir: envío gratis activado pero precio
rebate < $33.000.

Incluye estado del auto-fix (último intento de PUT free_shipping=false)
y endpoint POST para disparo manual.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from app.core.database import get_mlwebhook_engine
from app.core.deps import get_current_user
from app.core.database import get_db, SessionLocal
from app.models.usuario import Usuario
from app.models.free_shipping_fix_log import FreeShippingFixLog
from app.services.permisos_service import PermisosService
from app.services.ml_api_client import ml_client
from app.utils.ml_shipping import parse_shipping_tags
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/free-shipping-alerts", tags=["Free Shipping Alerts"])

# ── Schemas ──────────────────────────────────────────────────────


class AutoFixStatus(BaseModel):
    """Estado del último intento de auto-fix para un item."""

    attempted: bool = False
    success: Optional[bool] = None
    skipped: bool = False
    skip_reason: Optional[str] = None
    attempted_at: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


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
    auto_fix: AutoFixStatus = AutoFixStatus()

    model_config = ConfigDict(from_attributes=True)


class FreeShippingAlertSummary(BaseModel):
    """Resumen para el badge del topbar."""

    count: int
    items: List[FreeShippingAlertItem]

    model_config = ConfigDict(from_attributes=True)


# ── Helpers ──────────────────────────────────────────────────────

QUERY_FREE_SHIPPING_ERRORS = text("""
    SELECT DISTINCT ON (mla_base)
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
        p.last_updated,
        CASE
            WHEN p.resource LIKE '%/price_to_win%'
            THEN SUBSTRING(p.resource FROM '/items/(.+)/price_to_win')
            ELSE REPLACE(p.resource, '/items/', '')
        END AS mla_base
    FROM ml_previews p
    WHERE p.resource LIKE '/items/MLA%'
      AND (p.extra_data->>'free_shipping_error')::boolean = true
    ORDER BY mla_base,
             CASE WHEN p.resource NOT LIKE '%/price_to_win%' THEN 0 ELSE 1 END,
             p.last_updated DESC
""")

QUERY_COUNT_ONLY = text("""
    SELECT COUNT(*) AS cnt
    FROM (
        SELECT DISTINCT ON (
            CASE
                WHEN p.resource LIKE '%/price_to_win%'
                THEN SUBSTRING(p.resource FROM '/items/(.+)/price_to_win')
                ELSE REPLACE(p.resource, '/items/', '')
            END
        )
            p.resource
        FROM ml_previews p
        WHERE p.resource LIKE '/items/MLA%'
          AND (p.extra_data->>'free_shipping_error')::boolean = true
        ORDER BY
            CASE
                WHEN p.resource LIKE '%/price_to_win%'
                THEN SUBSTRING(p.resource FROM '/items/(.+)/price_to_win')
                ELSE REPLACE(p.resource, '/items/', '')
            END,
            CASE WHEN p.resource NOT LIKE '%/price_to_win%' THEN 0 ELSE 1 END
    ) deduped
""")


def _extract_mla_id(resource: str) -> str:
    """Extrae 'MLA1234567890' de '/items/MLA1234567890' o '/items/MLA1234567890/price_to_win'."""
    mla_id = resource.replace("/items/", "")
    # Limpiar sufijo /price_to_win si existe (bug de duplicados en ml_previews)
    ptw_idx = mla_id.find("/price_to_win")
    if ptw_idx != -1:
        mla_id = mla_id[:ptw_idx]
    return mla_id


def _build_ml_url(mla_id: str) -> str:
    """Construye la URL de MercadoLibre para buscar la publicacion."""
    return (
        "https://www.mercadolibre.com.ar/publicaciones/listado"
        "?filters=OMNI_ACTIVE|OMNI_INACTIVE|CHANNEL_NO_PROXIMITY_AND_NO_MP_MERCHANTS"
        f"&page=1&search={mla_id}&sort=DEFAULT"
    )


_parse_shipping_tags = parse_shipping_tags  # alias local para brevedad


def _get_auto_fix_statuses(mla_ids: list[str]) -> dict[str, AutoFixStatus]:
    """Obtiene el último estado de auto-fix para una lista de MLA IDs."""
    if not mla_ids:
        return {}

    db = SessionLocal()
    try:
        from sqlalchemy import desc  # noqa: E402 — lazy import to avoid circular

        results = (
            db.query(FreeShippingFixLog)
            .filter(FreeShippingFixLog.mla_id.in_(mla_ids))
            .order_by(FreeShippingFixLog.mla_id, desc(FreeShippingFixLog.created_at))
            .all()
        )

        # Tomar solo el más reciente por mla_id
        statuses: dict[str, AutoFixStatus] = {}
        for log_entry in results:
            if log_entry.mla_id not in statuses:
                statuses[log_entry.mla_id] = AutoFixStatus(
                    attempted=True,
                    success=log_entry.success,
                    skipped=log_entry.skipped,
                    skip_reason=log_entry.skip_reason,
                    attempted_at=log_entry.created_at.isoformat() if log_entry.created_at else None,
                )
        return statuses
    finally:
        db.close()


def _row_to_item(row: object, auto_fix_status: Optional[AutoFixStatus] = None) -> FreeShippingAlertItem:
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
        auto_fix=auto_fix_status or AutoFixStatus(),
    )


# ── Permission helper ────────────────────────────────────────────


def require_free_shipping_permission():
    """Dependency: requiere permiso alertas.ver_free_shipping."""

    def _check(
        current_user: Usuario = Depends(get_current_user),
        db=Depends(get_db),
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
    Incluye datos de precio, rebate, shipping, URL de ML, y estado del auto-fix.
    Requiere permiso: alertas.ver_free_shipping
    """
    try:
        engine = get_mlwebhook_engine()
        with engine.connect() as conn:
            result = conn.execute(QUERY_FREE_SHIPPING_ERRORS)
            rows = result.fetchall()

        # Extraer MLA IDs para buscar auto-fix statuses
        mla_ids = [_extract_mla_id(row.resource) for row in rows]
        fix_statuses = _get_auto_fix_statuses(mla_ids)

        items = [_row_to_item(row, fix_statuses.get(_extract_mla_id(row.resource))) for row in rows]
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


class ManualFixResponse(BaseModel):
    """Respuesta del disparo manual de fix."""

    mla_id: str
    success: bool
    message: str

    model_config = ConfigDict(from_attributes=True)


MLA_PATTERN = re.compile(r"^MLA\d{5,15}$")


@router.post("/{mla_id}/disable-free-shipping", response_model=ManualFixResponse)
async def manual_disable_free_shipping(
    mla_id: str,
    db=Depends(get_db),
    current_user: Usuario = Depends(require_free_shipping_permission()),
) -> ManualFixResponse:
    """
    Disparo manual: PUT free_shipping=false a ML para un item específico.

    Salta la validación de mandatory_free_shipping (el usuario sabe lo que
    hace). Si ML lo rechaza, se loguea igual.
    Requiere permiso: alertas.ver_free_shipping
    """
    # Validar formato MLA
    if not MLA_PATTERN.match(mla_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Formato de MLA inválido: {mla_id}",
        )

    logger.info(
        "Manual free_shipping fix triggered for %s by user %s",
        mla_id,
        current_user.username,
    )

    try:
        result_ml = await ml_client.update_item_shipping(mla_id, free_shipping=False)

        success = result_ml is not None
        message = "Envío gratis desactivado correctamente" if success else "ML rechazó el cambio"

        # Loguear el intento
        entry = FreeShippingFixLog(
            mla_id=mla_id,
            success=success,
            skipped=False,
            skip_reason=None if success else "manual_ml_rejected",
            item_price=None,
            mandatory_free_shipping=False,
            ml_response_status=200 if success else None,
            ml_response_body=None,
        )
        db.add(entry)
        db.commit()

        if not success:
            logger.warning("Manual fix FAILED for %s — ML rejected", mla_id)

        return ManualFixResponse(mla_id=mla_id, success=success, message=message)

    except Exception as e:
        logger.error("Manual fix ERROR for %s: %s", mla_id, e, exc_info=True)

        # Loguear el fallo
        entry = FreeShippingFixLog(
            mla_id=mla_id,
            success=False,
            skipped=False,
            skip_reason=f"manual_exception: {str(e)[:80]}",
            mandatory_free_shipping=False,
        )
        db.add(entry)
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al desactivar envío gratis",
        )
