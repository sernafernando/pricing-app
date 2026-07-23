"""
Derive-to-admin lane service — ML Bot Phase B (sdd/ml-bot-admin-pending, PR1).

`derive_from_message()` is called (best-effort, never raises) from
`drafting_service._draft_one` after a settled anchor is classified as
`invoice_cuit_change`. It creates ONE `ml_bot_admin_pending_requests` row per
`(pack_id, request_type)` while a row is still open (`new`/`in_progress`) —
a later, DIFFERENT extracted CUIT UPDATES that open row and APPENDS the prior
value to `superseded_values` instead of silently overwriting it (design
decision #4).

Session discipline (mirrors `drafting_service`): every DB read/write is its
own short `get_background_db()` block; the AFIP enrichment call happens
strictly OUTSIDE any DB session, bounded by `asyncio.wait_for`, and is
written back in a second short session block. AFIP failure/timeout/missing
config NEVER blocks row creation — `afip_status` degrades to `unavailable`.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from app.core.database import get_background_db
from app.models.ml_bot_admin_pending_request import MlBotAdminPendingRequest
from app.models.mercadolibre_user_data import MercadoLibreUserData
from app.services.afip_service import AfipService, AfipServiceError, validar_cuit

logger = logging.getLogger(__name__)

_OPEN_STATUSES = ("new", "in_progress")
_AFIP_TIMEOUT_SECONDS = 8.0


def _clean_cuit(cuit: Optional[str]) -> Optional[str]:
    if not cuit:
        return None
    return re.sub(r"[^0-9]", "", cuit)


def _cuit_core_matches_dni(extracted_cuit: Optional[str], stored_dni: Optional[str]) -> bool:
    """Soft cross-check only (never auto-fixed, design "PII / Threat"): a
    CUIT's middle 8 digits are the person's DNI (e.g. 20-14768351-1 <->
    14768351). Missing either side -> no mismatch signal (can't compare)."""
    core = _clean_cuit(extracted_cuit)
    dni = _clean_cuit(stored_dni)
    if not core or not dni or len(core) != 11:
        return True
    return core[2:10].lstrip("0") == dni.lstrip("0")


async def get_persona(cuit: str) -> Tuple[Dict[str, Any], str]:
    """Thin seam so tests can patch AFIP access without touching
    `AfipService` construction (which raises when unconfigured)."""
    service = AfipService()
    return await service.get_persona(cuit)


async def _enrich_afip(cuit: Optional[str]) -> Tuple[str, Dict[str, Any]]:
    """Best-effort AFIP enrichment, OUTSIDE any DB session. Never raises —
    returns (`afip_status`, extra_fields). `afip_status` in
    {"enriched","not_found","unavailable","skipped"}."""
    clean = _clean_cuit(cuit)
    if not clean or not validar_cuit(clean):
        return "skipped", {}

    try:
        persona, wsid = await asyncio.wait_for(get_persona(clean), timeout=_AFIP_TIMEOUT_SECONDS)
    except AfipServiceError as exc:
        logger.warning("admin_pending_service: AFIP lookup failed for a pending request: %s", exc.message)
        return "unavailable", {}
    except asyncio.TimeoutError:
        logger.warning("admin_pending_service: AFIP lookup timed out for a pending request")
        return "unavailable", {}
    except Exception as exc:  # noqa: BLE001 — AFIP enrichment must never crash the derive hook.
        logger.error("admin_pending_service: unexpected AFIP enrichment error: %s", exc, exc_info=True)
        return "unavailable", {}

    razon_social = persona.get("razonSocial") or persona.get("apellido")
    condicion_iva = AfipService.extraer_condicion_iva(persona) if "impuesto" in persona else None
    domicilio = AfipService.extraer_domicilio_fiscal(persona).get("direccion")

    if razon_social is None and condicion_iva is None and domicilio is None:
        return "not_found", {}

    return "enriched", {
        "afip_razon_social": razon_social,
        "afip_condicion_iva": condicion_iva,
        "afip_domicilio": domicilio,
    }


def _load_prefill(buyer_id: Optional[int]) -> Dict[str, Any]:
    """Best-effort pre-fill from `tb_mercadolibre_users_data` — mirrors
    `routers.ml_bot._enrich_message_nicknames`'s join by `buyer_id ->
    mluser_id`. Missing row -> empty dict, never a crash."""
    if buyer_id is None:
        return {}
    with get_background_db() as db:
        user = db.query(MercadoLibreUserData).filter(MercadoLibreUserData.mluser_id == buyer_id).first()
        if user is None:
            return {}
        return {
            "prefill_nickname": user.nickname,
            "prefill_identification_type": user.identification_type,
            "prefill_identification_number": user.identification_number,
            "prefill_billing_doc_type": user.billing_doc_type,
            "prefill_billing_doc_number": user.billing_doc_number,
            "prefill_billing_first_name": user.billing_first_name,
            "prefill_billing_last_name": user.billing_last_name,
        }


def _find_open_row(pack_id: Optional[str], request_type: str) -> Optional[int]:
    if not pack_id:
        return None
    with get_background_db() as db:
        row = (
            db.query(MlBotAdminPendingRequest)
            .filter(
                MlBotAdminPendingRequest.pack_id == pack_id,
                MlBotAdminPendingRequest.request_type == request_type,
                MlBotAdminPendingRequest.status.in_(_OPEN_STATUSES),
            )
            .order_by(MlBotAdminPendingRequest.created_at.desc())
            .first()
        )
        return row.id if row is not None else None


async def derive_from_message(
    *,
    message_id: Optional[int],
    pack_id: Optional[str],
    buyer_id: Optional[int],
    raw_text: str,
    extracted_cuit: Optional[str],
    extracted_name: Optional[str],
    request_type: str = "invoice_cuit_change",
) -> int:
    """Create (or update) ONE open row for `(pack_id, request_type)`. Never
    raises — the caller (`drafting_service`) wraps this in its own best-
    effort try/except, but this function is defensive on its own merits too
    (AFIP enrichment failure is always absorbed internally)."""
    prefill = _load_prefill(buyer_id)
    cuit_valid = validar_cuit(_clean_cuit(extracted_cuit) or "") if extracted_cuit else None
    doc_mismatch = not _cuit_core_matches_dni(
        extracted_cuit, prefill.get("prefill_identification_number") or prefill.get("prefill_billing_doc_number")
    )

    afip_status, afip_fields = await _enrich_afip(extracted_cuit)

    existing_id = _find_open_row(pack_id, request_type)

    with get_background_db() as db:
        if existing_id is not None:
            row = db.query(MlBotAdminPendingRequest).filter(MlBotAdminPendingRequest.id == existing_id).first()
            if row is None:
                row = MlBotAdminPendingRequest(pack_id=pack_id, buyer_id=buyer_id, request_type=request_type)
                db.add(row)
            elif row.extracted_cuit and extracted_cuit and row.extracted_cuit != extracted_cuit:
                superseded = list(row.superseded_values or [])
                superseded.append(
                    {
                        "cuit": row.extracted_cuit,
                        "name": row.extracted_name,
                        "at": datetime.now(timezone.utc).isoformat(),
                        "source": row.source,
                    }
                )
                row.superseded_values = superseded
        else:
            row = MlBotAdminPendingRequest(pack_id=pack_id, buyer_id=buyer_id, request_type=request_type)
            db.add(row)

        row.message_id = message_id
        row.raw_text = raw_text
        row.extracted_cuit = extracted_cuit
        row.extracted_name = extracted_name
        row.cuit_valid = cuit_valid
        row.doc_mismatch = doc_mismatch
        row.afip_status = afip_status
        row.afip_checked_at = datetime.now(timezone.utc) if afip_status != "skipped" else row.afip_checked_at
        for key, value in afip_fields.items():
            setattr(row, key, value)
        for key, value in prefill.items():
            setattr(row, key, value)

        db.flush()
        return row.id
