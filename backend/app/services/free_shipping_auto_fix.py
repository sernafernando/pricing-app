"""
Servicio de auto-fix para free_shipping.

Lee items con free_shipping_error=true de ml_previews (BD mlwebhook),
filtra los que NO tienen mandatory_free_shipping, y dispara PUT
free_shipping=false a ML. Sin cooldown: ML reactiva el envío gratis
cada ~10-15 min, así que cada corrida (cada 5 min) re-envía el fix.

Se ejecuta como background task periódica desde main.py.
"""

from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_mlwebhook_engine, SessionLocal
from app.core.logging import get_logger
from app.models.free_shipping_fix_log import FreeShippingFixLog
from app.services.ml_api_client import ml_client
from app.utils.ml_shipping import parse_shipping_tags

logger = get_logger(__name__)

# Query para obtener items con free_shipping_error (misma lógica que el router)
QUERY_ITEMS_TO_FIX = text("""
    SELECT DISTINCT ON (mla_base)
        p.resource,
        p.price,
        p.extra_data->'shipping_tags' AS shipping_tags,
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


_parse_shipping_tags = parse_shipping_tags  # alias local para brevedad


def _log_attempt(
    db: Session,
    *,
    mla_id: str,
    success: bool,
    skipped: bool = False,
    skip_reason: Optional[str] = None,
    item_price: Optional[str] = None,
    mandatory: bool = False,
    ml_status: Optional[int] = None,
    ml_body: Optional[str] = None,
) -> None:
    """Registra un intento de fix en el log."""
    entry = FreeShippingFixLog(
        mla_id=mla_id,
        success=success,
        skipped=skipped,
        skip_reason=skip_reason,
        item_price=item_price,
        mandatory_free_shipping=mandatory,
        ml_response_status=ml_status,
        ml_response_body=ml_body[:2000] if ml_body else None,
    )
    db.add(entry)
    db.commit()


async def run_free_shipping_auto_fix() -> dict:
    """
    Proceso principal de auto-fix.

    Returns:
        Dict con estadísticas: {total, fixed, skipped_mandatory, failed}
    """
    stats = {
        "total": 0,
        "fixed": 0,
        "skipped_mandatory": 0,
        "failed": 0,
    }

    # 1. Leer alertas de ml_previews
    try:
        mlwebhook_engine = get_mlwebhook_engine()
    except RuntimeError:
        logger.warning("ML_WEBHOOK_DB_URL not configured — auto-fix skipped")
        return stats

    try:
        with mlwebhook_engine.connect() as conn:
            result = conn.execute(QUERY_ITEMS_TO_FIX)
            rows = result.fetchall()
    except Exception as e:
        logger.error("Error reading ml_previews for auto-fix: %s", e, exc_info=True)
        return stats

    if not rows:
        return stats

    stats["total"] = len(rows)
    logger.info("Free shipping auto-fix: found %d items with free_shipping_error", len(rows))

    # 2. Procesar cada item — sin cooldown, ML reactiva cada ~10-15 min
    db = SessionLocal()
    try:
        for row in rows:
            mla_id = row.mla_base
            price_str = str(row.price) if row.price is not None else None
            _tags, mandatory = _parse_shipping_tags(row.shipping_tags)

            # Skip: mandatory_free_shipping — ML no deja sacarlo
            if mandatory:
                stats["skipped_mandatory"] += 1
                _log_attempt(
                    db,
                    mla_id=mla_id,
                    success=False,
                    skipped=True,
                    skip_reason="mandatory_free_shipping",
                    item_price=price_str,
                    mandatory=True,
                )
                continue

            # 3. Disparar PUT a MercadoLibre
            try:
                result_ml = await ml_client.update_item_shipping(mla_id, free_shipping=False)

                if result_ml is not None:
                    stats["fixed"] += 1
                    _log_attempt(
                        db,
                        mla_id=mla_id,
                        success=True,
                        item_price=price_str,
                        mandatory=False,
                        ml_status=200,
                    )
                    logger.info("Auto-fix OK: %s free_shipping=false", mla_id)
                else:
                    stats["failed"] += 1
                    _log_attempt(
                        db,
                        mla_id=mla_id,
                        success=False,
                        item_price=price_str,
                        mandatory=False,
                        skip_reason="ml_rejected",
                    )
                    logger.warning("Auto-fix FAILED: %s — ML rejected", mla_id)

            except Exception as e:
                stats["failed"] += 1
                _log_attempt(
                    db,
                    mla_id=mla_id,
                    success=False,
                    item_price=price_str,
                    mandatory=False,
                    skip_reason=f"exception: {str(e)[:80]}",
                )
                logger.error("Auto-fix ERROR for %s: %s", mla_id, e)

    finally:
        db.close()

    logger.info(
        "Free shipping auto-fix complete: %s",
        ", ".join(f"{k}={v}" for k, v in stats.items()),
    )
    return stats
