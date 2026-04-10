"""
Seriales — Order messages and ML attachment proxies.

Endpoints:
  GET /orders/{order_id}/messages
  GET /ml-attachment
  GET /ml-claim-attachment
"""

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.usuario import Usuario
from app.routers.seriales_shared import (
    ML_WEBHOOK_RENDER_URL,
    _HTTPX_TIMEOUT,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# QUERIES (only used by this module)
# =============================================================================

QUERY_PACK_ID_BY_ORDER = text("""
    SELECT mlo.ml_pack_id
    FROM tb_sale_order_header soh
    INNER JOIN tb_mercadolibre_orders_header mlo
        ON soh.mlo_id = mlo.mlo_id
    WHERE soh.soh_mlid = :order_id
    LIMIT 1
""")


# =============================================================================
# SCHEMAS (only used by this module)
# =============================================================================


class OrderMessageResponse(BaseModel):
    """Mensaje de la conversación posventa (mensajería de packs)."""

    message_id: Optional[str] = None
    from_user_id: Optional[int] = None
    to_user_id: Optional[int] = None
    text: Optional[str] = None
    status: Optional[str] = None
    date_created: Optional[str] = None
    date_read: Optional[str] = None
    attachments: Optional[list] = None
    is_seller: bool = False


# Map file extensions to MIME types
_EXT_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
}


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get(
    "/orders/{order_id}/messages",
    response_model=list[OrderMessageResponse],
)
def get_order_messages(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[OrderMessageResponse]:
    """
    Devuelve los mensajes de la conversación posventa (mensajería de packs).
    Busca el pack_id asociado al order_id y fetchea de la API de ML.
    Si el order no pertenece a un pack, usa order_id como pack_id.
    """
    seller_id = settings.ML_USER_ID
    if not seller_id:
        return []

    # 1. Buscar pack_id en la DB
    row = db.execute(QUERY_PACK_ID_BY_ORDER, {"order_id": order_id}).first()
    pack_id = str(row.ml_pack_id) if row and row.ml_pack_id else order_id

    # 2. Fetch de la API de ML
    seller_id_str = str(seller_id)
    resource = f"/messages/packs/{pack_id}/sellers/{seller_id_str}?tag=post_sale&mark_as_read=false"
    try:
        with httpx.Client(timeout=_HTTPX_TIMEOUT) as client:
            r = client.get(
                ML_WEBHOOK_RENDER_URL,
                params={"resource": resource, "format": "json"},
            )
            if r.status_code != 200:
                logger.warning(
                    "[order-msgs] Failed to fetch pack %s messages: %s",
                    pack_id,
                    r.status_code,
                )
                return []

            data = r.json()

            # ML returns {paging, messages, conversation_status, ...}
            raw_messages = data.get("messages") or []
            seller_id_int = int(seller_id_str)

            result: list[OrderMessageResponse] = []
            for msg in raw_messages:
                from_uid = msg.get("from", {}).get("user_id")
                to_uid = msg.get("to", {}).get("user_id")

                # Extract text — can be string or dict with "plain"
                msg_text = msg.get("text")
                if isinstance(msg_text, dict):
                    msg_text = msg_text.get("plain", "")

                dates = msg.get("message_date") or {}

                result.append(
                    OrderMessageResponse(
                        message_id=msg.get("id"),
                        from_user_id=from_uid,
                        to_user_id=to_uid,
                        text=msg_text,
                        status=msg.get("status"),
                        date_created=dates.get("created") or dates.get("received"),
                        date_read=dates.get("read"),
                        attachments=msg.get("message_attachments"),
                        is_seller=(from_uid == seller_id_int),
                    )
                )
            return result
    except Exception:
        logger.warning(
            "[order-msgs] Exception fetching messages for order %s (pack %s)",
            order_id,
            pack_id,
            exc_info=True,
        )

    return []


@router.get("/ml-attachment")
def get_ml_attachment(
    id: str = Query(..., description="Attachment key from ML message_attachments"),
) -> Response:
    """
    Proxy para descargar adjuntos de mensajes de ML.
    Fetchea /messages/attachments/{id}?tag=post_sale&site_id=MLA
    y devuelve el binario con el content-type correcto.
    Usa query param para evitar que nginx/CDN intercepte la extensión como archivo estático.
    """
    attachment_id = id
    resource = f"/messages/attachments/{attachment_id}?tag=post_sale&site_id=MLA"
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(
                ML_WEBHOOK_RENDER_URL,
                params={"resource": resource, "format": "json"},
            )
            if r.status_code != 200:
                raise HTTPException(
                    status_code=r.status_code,
                    detail=f"ML returned {r.status_code}",
                )

            content_type = r.headers.get("content-type", "application/octet-stream")

            # If proxy returned JSON or HTML, it's an error — NOT the file
            if "json" in content_type or "text/html" in content_type:
                logger.warning(
                    "[ml-attachment] Proxy returned %s (%d bytes) for %s",
                    content_type,
                    len(r.content),
                    attachment_id,
                )
                raise HTTPException(
                    status_code=502,
                    detail="ML proxy returned error instead of file",
                )

            return Response(
                content=r.content,
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "Content-Disposition": f'inline; filename="{attachment_id.split("/")[-1]}"',
                },
            )
    except HTTPException:
        raise
    except Exception:
        logger.warning(
            "[ml-attachment] Failed to fetch attachment %s",
            attachment_id,
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail="Failed to fetch attachment")


@router.get("/ml-claim-attachment")
def get_ml_claim_attachment(
    claim_id: str = Query(..., description="ML claim ID"),
    filename: str = Query(..., description="Attachment filename from claim message"),
) -> Response:
    """
    Proxy para descargar adjuntos de mensajes de RECLAMOS de ML.
    Usa /post-purchase/v1/claims/{claim_id}/attachments/{filename}/download
    a través del proxy webhook.
    Endpoint público (sin auth) — las imágenes se cargan vía <img> tags.

    NOTE: Claim attachments use a DIFFERENT API than order message attachments.
    Order messages: /messages/attachments/{id} (404 for claim files)
    Claim messages: /post-purchase/v1/claims/{claim_id}/attachments/{filename}/download
    """
    resource = f"/post-purchase/v1/claims/{claim_id}/attachments/{filename}/download"
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(
                ML_WEBHOOK_RENDER_URL,
                params={"resource": resource, "format": "json"},
            )
            if r.status_code != 200:
                raise HTTPException(
                    status_code=r.status_code,
                    detail=f"ML returned {r.status_code}",
                )

            content_type = r.headers.get("content-type", "application/octet-stream")

            # If proxy returned JSON or HTML, it's an error — NOT the file
            if "json" in content_type or "text/html" in content_type:
                logger.warning(
                    "[ml-claim-attachment] Proxy returned %s (%d bytes) for claim %s/%s",
                    content_type,
                    len(r.content),
                    claim_id,
                    filename,
                )
                raise HTTPException(
                    status_code=502,
                    detail="ML proxy returned error instead of file",
                )

            # Sanity check: images should be at least 1KB
            if len(r.content) < 1000:
                logger.warning(
                    "[ml-claim-attachment] Suspiciously small response (%d bytes) for %s/%s",
                    len(r.content),
                    claim_id,
                    filename,
                )

            return Response(
                content=r.content,
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "Content-Disposition": f'inline; filename="{filename}"',
                },
            )
    except HTTPException:
        raise
    except Exception:
        logger.warning(
            "[ml-claim-attachment] Failed to fetch claim %s attachment %s",
            claim_id,
            filename,
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail="Failed to fetch claim attachment")
