"""
Seriales — Claims ML (lookup, enrichment, cache).

Endpoint: GET /claims/{claim_id}/messages
Public functions: _fetch_claims_by_order_ids (used by traza and traza_ml)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_background_db, get_db, get_mlwebhook_engine
from app.api.deps import get_current_user
from app.models.rma_claim_ml import RmaClaimML
from app.models.rma_claim_ml_message import RmaClaimMLMessage
from app.models.usuario import Usuario
from app.routers.seriales_shared import (
    ClaimChange,
    ClaimExpectedResolution,
    ClaimML,
    ClaimReturn,
    ClaimReturnShipment,
    ML_WEBHOOK_RENDER_URL,
    _HTTPX_TIMEOUT,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# Fallback stale threshold: only used when ml_previews DB is unavailable.
# Normally, staleness is determined by comparing ml_previews.last_updated
# against rma_claims_ml.updated_at (webhook-driven invalidation).
_CACHE_STALE_HOURS_FALLBACK = 24


# =============================================================================
# SCHEMAS (only used by this module)
# =============================================================================


class ClaimMessageResponse(BaseModel):
    """Mensaje individual de un reclamo ML."""

    id: int
    claim_id: int
    sender_role: Optional[str] = None
    receiver_role: Optional[str] = None
    message: Optional[str] = None
    status: Optional[str] = None
    stage: Optional[str] = None
    attachments: Optional[list] = None
    date_read: Optional[str] = None
    ml_date_created: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# CLAIM BUILDERS
# =============================================================================


def _build_claim_from_db_cache(row: RmaClaimML) -> ClaimML:
    """Build ClaimML from a locally cached RmaClaimML record."""
    # Rebuild sub-models from JSONB
    expected_res_detail = None
    if row.expected_resolutions_detail:
        expected_res_detail = [
            ClaimExpectedResolution(
                player_role=r.get("player_role"),
                expected_resolution=r.get("expected_resolution"),
                status=r.get("status"),
                details=r.get("details"),
                date_created=r.get("date_created"),
                last_updated=r.get("last_updated"),
            )
            for r in row.expected_resolutions_detail
        ]

    claim_return = None
    if row.return_data:
        rd = row.return_data
        shipments = [
            ClaimReturnShipment(
                shipment_id=s.get("shipment_id"),
                status=s.get("status"),
                tracking_number=s.get("tracking_number"),
                destination_name=s.get("destination_name"),
                shipment_type=s.get("shipment_type"),
            )
            for s in (rd.get("shipments") or [])
        ]
        claim_return = ClaimReturn(
            return_id=rd.get("return_id"),
            status=rd.get("status"),
            subtype=rd.get("subtype"),
            status_money=rd.get("status_money"),
            refund_at=rd.get("refund_at"),
            shipments=shipments,
            date_created=rd.get("date_created"),
            date_closed=rd.get("date_closed"),
        )

    claim_change = None
    if row.change_data:
        cd = row.change_data
        claim_change = ClaimChange(
            change_type=cd.get("change_type"),
            status=cd.get("status"),
            status_detail=cd.get("status_detail"),
            new_order_ids=cd.get("new_order_ids"),
            date_created=cd.get("date_created"),
            last_updated=cd.get("last_updated"),
        )

    return ClaimML(
        claim_id=str(row.claim_id),
        claim_type=row.claim_type,
        claim_stage=row.claim_stage,
        status=row.status,
        reason_id=row.reason_id,
        reason_category=row.reason_category,
        reason_detail=row.reason_detail or row.reason_name,
        triage_tags=row.triage_tags,
        expected_resolutions=row.expected_resolutions,
        fulfilled=row.fulfilled,
        quantity_type=row.quantity_type,
        claimed_quantity=row.claimed_quantity,
        seller_actions=row.seller_actions,
        mandatory_actions=row.mandatory_actions,
        nearest_due_date=row.nearest_due_date,
        action_responsible=row.action_responsible,
        detail_title=row.detail_title,
        detail_description=row.detail_description,
        detail_problem=row.detail_problem,
        resolution_reason=row.resolution_reason,
        resolution_closed_by=row.resolution_closed_by,
        resolution_coverage=row.resolution_coverage,
        related_entities=row.related_entities,
        expected_resolutions_detail=expected_res_detail,
        claim_return=claim_return,
        claim_change=claim_change,
        messages_total=row.messages_total,
        affects_reputation=row.affects_reputation,
        has_incentive=row.has_incentive,
        date_created=row.ml_date_created,
        last_updated=row.ml_last_updated,
        resource_id=str(row.resource_id) if row.resource_id else None,
    )


def _is_cache_stale_by_time(row: RmaClaimML) -> bool:
    """
    Fallback staleness check (time-based). Only used when ml_previews
    DB is unavailable. Normally we compare against ml_previews.last_updated.
    """
    if row.status == "closed":
        return False
    if not row.updated_at:
        return True
    now = datetime.now(timezone.utc)
    updated = row.updated_at.replace(tzinfo=timezone.utc) if row.updated_at.tzinfo is None else row.updated_at
    return (now - updated).total_seconds() > _CACHE_STALE_HOURS_FALLBACK * 3600


def _build_claim_from_enriched_extra(
    ed: dict, status_override: Optional[str] = None, title_fallback: Optional[str] = None
) -> ClaimML:
    """Build ClaimML from extra_data that was enriched by the webhook service."""
    return ClaimML(
        claim_id=str(ed.get("claim_id", "")),
        claim_type=ed.get("claim_type"),
        claim_stage=ed.get("claim_stage"),
        status=status_override or ed.get("status"),
        reason_id=ed.get("reason_id"),
        reason_category=ed.get("reason_category"),
        reason_detail=ed.get("reason_detail") or title_fallback,
        triage_tags=ed.get("triage_tags"),
        expected_resolutions=ed.get("expected_resolutions"),
        fulfilled=ed.get("fulfilled"),
        quantity_type=ed.get("quantity_type"),
        claimed_quantity=ed.get("claimed_quantity"),
        seller_actions=ed.get("seller_actions"),
        mandatory_actions=ed.get("mandatory_actions"),
        nearest_due_date=ed.get("nearest_due_date"),
        action_responsible=ed.get("action_responsible"),
        detail_title=ed.get("detail_title"),
        detail_problem=ed.get("detail_problem"),
        resolution_reason=ed.get("resolution_reason"),
        resolution_closed_by=ed.get("resolution_closed_by"),
        resolution_coverage=ed.get("resolution_coverage"),
        date_created=ed.get("date_created"),
        last_updated=ed.get("last_updated"),
        resource_id=str(ed.get("resource_id", "")),
    )


def _build_claim_from_ml_api(
    claim_data: dict,
    detail_data: Optional[dict] = None,
    reason_data: Optional[dict] = None,
    expected_res_data: Optional[list] = None,
    return_data: Optional[dict] = None,
    change_data: Optional[dict] = None,
    messages_data: Optional[dict] = None,
    affects_rep_data: Optional[dict] = None,
) -> ClaimML:
    """
    Build ClaimML from raw ML API data (up to 7+ endpoints combined).
    - claim_data: from /claims/{id}
    - detail_data: from /claims/{id}/detail
    - reason_data: from /claims/reasons/{reason_id}
    - expected_res_data: from /claims/{id}/expected-resolutions
    - return_data: from /v2/claims/{id}/returns
    - change_data: from /v1/claims/{id}/changes
    - messages_data: from /claims/{id}/messages
    - affects_rep_data: from /claims/{id}/affects-reputation
    """
    # Extract players info
    seller_actions: list[str] = []
    mandatory_actions: list[str] = []
    nearest_due_date: Optional[str] = None
    for player in claim_data.get("players") or []:
        if player.get("role") == "respondent":
            for action in player.get("available_actions") or []:
                action_name = action.get("action")
                if action_name:
                    seller_actions.append(action_name)
                if action.get("mandatory"):
                    if action_name:
                        mandatory_actions.append(action_name)
                    if action.get("due_date") and not nearest_due_date:
                        nearest_due_date = action["due_date"]

    # Resolution
    resolution = claim_data.get("resolution") or {}

    # Reason details (from /reasons/{id} endpoint)
    reason_settings = (reason_data or {}).get("settings") or {}
    triage_tags = reason_settings.get("rules_engine_triage")
    expected_resolutions = reason_settings.get("expected_resolutions")
    reason_detail = (reason_data or {}).get("detail")
    reason_name = (reason_data or {}).get("name")

    # Detail (from /claims/{id}/detail endpoint)
    det = detail_data or {}

    # Related entities — ML returns either ["return", "change"] or
    # [{"entity_type": "return", "entity_id": 123}] depending on the endpoint
    related_entities: Optional[list[str]] = None
    raw_related = claim_data.get("related_entities") or []
    if raw_related:
        parsed: list[str] = []
        for e in raw_related:
            if isinstance(e, str):
                parsed.append(e)
            elif isinstance(e, dict) and e.get("entity_type"):
                parsed.append(e["entity_type"])
        related_entities = parsed or None

    # Expected resolutions detail (from /expected-resolutions endpoint)
    exp_res_detail: Optional[list[ClaimExpectedResolution]] = None
    if expected_res_data:
        exp_res_detail = [
            ClaimExpectedResolution(
                player_role=r.get("player_role"),
                expected_resolution=r.get("expected_resolution"),
                status=r.get("status"),
                details=r.get("details"),
                date_created=r.get("date_created"),
                last_updated=r.get("last_updated"),
            )
            for r in expected_res_data
        ]

    # Return (from /v2/claims/{id}/returns endpoint)
    claim_return: Optional[ClaimReturn] = None
    if return_data and return_data.get("id"):
        shipments = [
            ClaimReturnShipment(
                shipment_id=s.get("id"),
                status=s.get("status"),
                tracking_number=s.get("tracking_number"),
                destination_name=s.get("destination", {}).get("name")
                if isinstance(s.get("destination"), dict)
                else s.get("destination_name"),
                shipment_type=s.get("type"),
            )
            for s in (return_data.get("shipments") or [])
        ]
        claim_return = ClaimReturn(
            return_id=return_data.get("id"),
            status=return_data.get("status"),
            subtype=return_data.get("subtype"),
            status_money=return_data.get("status_money"),
            refund_at=return_data.get("refund_at"),
            shipments=shipments,
            date_created=return_data.get("date_created"),
            date_closed=return_data.get("date_closed"),
        )

    # Change (from /v1/claims/{id}/changes endpoint)
    claim_change: Optional[ClaimChange] = None
    if change_data and (change_data.get("change_type") or change_data.get("status")):
        new_order_ids = None
        if change_data.get("new_items"):
            new_order_ids = [item.get("order_id") for item in change_data["new_items"] if item.get("order_id")]
        claim_change = ClaimChange(
            change_type=change_data.get("change_type"),
            status=change_data.get("status"),
            status_detail=change_data.get("status_detail"),
            new_order_ids=new_order_ids,
            date_created=change_data.get("date_created"),
            last_updated=change_data.get("last_updated"),
        )

    # Messages count (from /messages endpoint)
    # NOTE: ML may return a list directly OR a dict with {paging, data}.
    messages_total: Optional[int] = None
    if messages_data is not None:
        if isinstance(messages_data, list):
            messages_total = len(messages_data)
        else:
            paging = messages_data.get("paging") or {}
            messages_total = paging.get("total")
            if messages_total is None:
                messages_total = len(messages_data.get("data") or [])

    # Affects reputation (from /affects-reputation endpoint)
    # NOTE: ML may return bool (True/False) OR string ("affected"/"not_affected").
    affects_reputation: Optional[bool] = None
    has_incentive: Optional[bool] = None
    if affects_rep_data is not None:
        raw_ar = affects_rep_data.get("affects_reputation")
        if isinstance(raw_ar, bool):
            affects_reputation = raw_ar
        elif isinstance(raw_ar, str):
            affects_reputation = raw_ar.lower() in ("affected", "true")
        raw_hi = affects_rep_data.get("has_incentive")
        if isinstance(raw_hi, bool):
            has_incentive = raw_hi
        elif isinstance(raw_hi, str):
            has_incentive = raw_hi.lower() in ("true", "yes")
        # else: remains None

    return ClaimML(
        claim_id=str(claim_data.get("id", "")),
        claim_type=claim_data.get("type"),
        claim_stage=claim_data.get("stage"),
        status=claim_data.get("status"),
        reason_id=claim_data.get("reason_id"),
        reason_category=None,  # populated by enriched webhook path (ed.get("reason_category"))
        reason_detail=reason_detail or det.get("problem") or reason_name,
        triage_tags=triage_tags,
        expected_resolutions=expected_resolutions,
        fulfilled=claim_data.get("fulfilled"),
        quantity_type=claim_data.get("quantity_type"),
        claimed_quantity=claim_data.get("claimed_quantity"),
        seller_actions=seller_actions or None,
        mandatory_actions=mandatory_actions or None,
        nearest_due_date=nearest_due_date or det.get("due_date"),
        action_responsible=det.get("action_responsible"),
        detail_title=det.get("title"),
        detail_description=det.get("description"),
        detail_problem=det.get("problem"),
        resolution_reason=resolution.get("reason"),
        resolution_closed_by=resolution.get("closed_by"),
        resolution_coverage=resolution.get("applied_coverage"),
        related_entities=related_entities,
        expected_resolutions_detail=exp_res_detail,
        claim_return=claim_return,
        claim_change=claim_change,
        messages_total=messages_total,
        affects_reputation=affects_reputation,
        has_incentive=has_incentive,
        date_created=claim_data.get("date_created"),
        last_updated=claim_data.get("last_updated"),
        resource_id=str(claim_data.get("resource_id", "")),
    )


def _fetch_all_ml_endpoints(
    client: httpx.Client, claim_id: str, claim_data: dict
) -> tuple[
    Optional[dict],  # detail_data
    Optional[dict],  # reason_data
    Optional[list],  # expected_res_data
    Optional[dict],  # return_data
    Optional[dict],  # change_data
    Optional[dict],  # messages_data
    Optional[dict],  # affects_rep_data
]:
    """
    Fetch all secondary ML endpoints for a claim. Each call is
    wrapped in try/except so one failure doesn't block the rest.
    """
    detail_data = None
    reason_data = None
    expected_res_data = None
    return_data = None
    change_data = None
    messages_data = None
    affects_rep_data = None

    # 1. /claims/{id}/detail
    try:
        r = client.get(
            ML_WEBHOOK_RENDER_URL,
            params={"resource": f"/post-purchase/v1/claims/{claim_id}/detail", "format": "json"},
        )
        if r.status_code == 200:
            detail_data = r.json()
    except Exception:
        pass

    # 2. /claims/reasons/{reason_id}
    reason_id = claim_data.get("reason_id")
    if reason_id:
        try:
            r = client.get(
                ML_WEBHOOK_RENDER_URL,
                params={"resource": f"/post-purchase/v1/claims/reasons/{reason_id}", "format": "json"},
            )
            if r.status_code == 200:
                reason_data = r.json()
        except Exception:
            pass

    # 3. /claims/{id}/expected-resolutions
    try:
        r = client.get(
            ML_WEBHOOK_RENDER_URL,
            params={"resource": f"/post-purchase/v1/claims/{claim_id}/expected-resolutions", "format": "json"},
        )
        if r.status_code == 200:
            data = r.json()
            # API returns array or object with data key
            if isinstance(data, list):
                expected_res_data = data
            elif isinstance(data, dict) and "data" in data:
                expected_res_data = data["data"]
    except Exception:
        pass

    # 4. /v2/claims/{id}/returns (only if related_entities indicates return)
    related = claim_data.get("related_entities") or []
    has_return = any((e == "return" if isinstance(e, str) else e.get("entity_type") == "return") for e in related)
    if has_return:
        try:
            r = client.get(
                ML_WEBHOOK_RENDER_URL,
                params={"resource": f"/post-purchase/v2/claims/{claim_id}/returns", "format": "json"},
            )
            if r.status_code == 200:
                return_data = r.json()
        except Exception:
            pass

    # 5. /v1/claims/{id}/changes (only if related_entities indicates change)
    has_change = any((e == "change" if isinstance(e, str) else e.get("entity_type") == "change") for e in related)
    if has_change:
        try:
            r = client.get(
                ML_WEBHOOK_RENDER_URL,
                params={"resource": f"/post-purchase/v1/claims/{claim_id}/changes", "format": "json"},
            )
            if r.status_code == 200:
                change_data = r.json()
        except Exception:
            pass

    # 6. /claims/{id}/messages (fetch all — cached in rma_claims_ml_messages)
    try:
        r = client.get(
            ML_WEBHOOK_RENDER_URL,
            params={
                "resource": f"/post-purchase/v1/claims/{claim_id}/messages",
                "format": "json",
            },
        )
        if r.status_code == 200:
            messages_data = r.json()
    except Exception:
        pass

    # 7. /claims/{id}/affects-reputation
    try:
        r = client.get(
            ML_WEBHOOK_RENDER_URL,
            params={"resource": f"/post-purchase/v1/claims/{claim_id}/affects-reputation", "format": "json"},
        )
        if r.status_code == 200:
            affects_rep_data = r.json()
    except Exception:
        pass

    return (
        detail_data,
        reason_data,
        expected_res_data,
        return_data,
        change_data,
        messages_data,
        affects_rep_data,
    )


def _save_claim_to_cache(
    claim: ClaimML,
    raw_claim: Optional[dict] = None,
    raw_detail: Optional[dict] = None,
    raw_reason: Optional[dict] = None,
    return_data: Optional[dict] = None,
    change_data: Optional[dict] = None,
    expected_res_data: Optional[list] = None,
    messages_data: Optional[dict] = None,
    affects_rep_data: Optional[dict] = None,
) -> None:
    """
    Upsert a ClaimML + raw data into the rma_claims_ml local cache table.
    Uses a separate session so it doesn't interfere with the request's session.
    """
    try:
        claim_id_int = int(claim.claim_id) if claim.claim_id else None
        if not claim_id_int:
            return

        with get_background_db() as session:
            existing = session.query(RmaClaimML).filter(RmaClaimML.claim_id == claim_id_int).first()

            # Build return_data JSONB for storage
            return_jsonb = None
            if claim.claim_return:
                cr = claim.claim_return
                return_jsonb = {
                    "return_id": cr.return_id,
                    "status": cr.status,
                    "subtype": cr.subtype,
                    "status_money": cr.status_money,
                    "refund_at": cr.refund_at,
                    "shipments": [
                        {
                            "shipment_id": s.shipment_id,
                            "status": s.status,
                            "tracking_number": s.tracking_number,
                            "destination_name": s.destination_name,
                            "shipment_type": s.shipment_type,
                        }
                        for s in (cr.shipments or [])
                    ],
                    "date_created": cr.date_created,
                    "date_closed": cr.date_closed,
                }

            # Build change_data JSONB
            change_jsonb = None
            if claim.claim_change:
                cc = claim.claim_change
                change_jsonb = {
                    "change_type": cc.change_type,
                    "status": cc.status,
                    "status_detail": cc.status_detail,
                    "new_order_ids": cc.new_order_ids,
                    "date_created": cc.date_created,
                    "last_updated": cc.last_updated,
                }

            # Build expected_resolutions_detail JSONB
            exp_res_jsonb = None
            if claim.expected_resolutions_detail:
                exp_res_jsonb = [
                    {
                        "player_role": r.player_role,
                        "expected_resolution": r.expected_resolution,
                        "status": r.status,
                        "details": r.details,
                        "date_created": r.date_created,
                        "last_updated": r.last_updated,
                    }
                    for r in claim.expected_resolutions_detail
                ]

            # Denormalize return fields for efficient filtering
            return_status = None
            return_shipment_status = None
            return_destination = None
            return_tracking = None
            return_shipment_type = None
            if claim.claim_return:
                cr = claim.claim_return
                return_status = cr.status
                if cr.shipments:
                    first_ship = cr.shipments[0]
                    return_shipment_status = first_ship.status
                    return_destination = first_ship.destination_name
                    return_tracking = first_ship.tracking_number
                    return_shipment_type = first_ship.shipment_type

            values = {
                "resource_id": int(claim.resource_id) if claim.resource_id and claim.resource_id.isdigit() else None,
                "claim_type": claim.claim_type,
                "claim_stage": claim.claim_stage,
                "status": claim.status,
                "reason_id": claim.reason_id,
                "reason_category": claim.reason_category,
                "reason_detail": claim.reason_detail,
                "reason_name": claim.reason_detail,
                "triage_tags": claim.triage_tags,
                "expected_resolutions": claim.expected_resolutions,
                "detail_title": claim.detail_title,
                "detail_description": claim.detail_description,
                "detail_problem": claim.detail_problem,
                "fulfilled": claim.fulfilled,
                "quantity_type": claim.quantity_type,
                "claimed_quantity": claim.claimed_quantity,
                "seller_actions": claim.seller_actions,
                "mandatory_actions": claim.mandatory_actions,
                "nearest_due_date": claim.nearest_due_date,
                "action_responsible": claim.action_responsible,
                "resolution_reason": claim.resolution_reason,
                "resolution_closed_by": claim.resolution_closed_by,
                "resolution_coverage": claim.resolution_coverage,
                "related_entities": claim.related_entities,
                "expected_resolutions_detail": exp_res_jsonb,
                "return_data": return_jsonb,
                "change_data": change_jsonb,
                "messages_total": claim.messages_total,
                "affects_reputation": claim.affects_reputation,
                "has_incentive": claim.has_incentive,
                "ml_date_created": claim.date_created,
                "ml_last_updated": claim.last_updated,
                "raw_claim": raw_claim,
                "raw_detail": raw_detail,
                "raw_reason": raw_reason,
                # Denormalized return fields
                "return_status": return_status,
                "return_shipment_status": return_shipment_status,
                "return_destination": return_destination,
                "return_tracking": return_tracking,
                "return_shipment_type": return_shipment_type,
            }

            if existing:
                for key, val in values.items():
                    setattr(existing, key, val)
            else:
                row = RmaClaimML(claim_id=claim_id_int, **values)
                session.add(row)

            # commit is handled by get_background_db() on exit
    except Exception:
        logger.warning("Failed to save claim %s to cache", claim.claim_id, exc_info=True)


def _save_messages_to_cache(claim_id: str, messages_data: Optional[dict | list]) -> None:
    """
    Save messages from /claims/{id}/messages into rma_claims_ml_messages.
    Only saves messages not already in the DB (by claim_id + ml_date_created).
    ML may return a list directly OR a dict with {paging, data}.
    """
    if not messages_data:
        return
    if isinstance(messages_data, list):
        messages = messages_data
    else:
        messages = messages_data.get("data") or []
    if not messages:
        return

    try:
        claim_id_int = int(claim_id)
        with get_background_db() as session:
            # Get existing message dates to avoid duplicates
            existing_dates = {
                row.ml_date_created
                for row in session.query(RmaClaimMLMessage.ml_date_created)
                .filter(RmaClaimMLMessage.claim_id == claim_id_int)
                .all()
            }

            for msg in messages:
                msg_date = msg.get("date_created")
                if msg_date in existing_dates:
                    continue

                row = RmaClaimMLMessage(
                    claim_id=claim_id_int,
                    sender_role=msg.get("sender_role"),
                    receiver_role=msg.get("receiver_role"),
                    message=msg.get("message"),
                    status=msg.get("status"),
                    stage=msg.get("stage"),
                    attachments=msg.get("attachments"),
                    message_moderation=msg.get("message_moderation"),
                    date_read=msg.get("date_read"),
                    ml_date_created=msg_date,
                )
                session.add(row)

            # commit is handled by get_background_db() on exit
    except Exception:
        logger.warning("Failed to save messages for claim %s", claim_id, exc_info=True)


def _enrich_claim_via_http(claim_id: str, _max_retries: int = 2) -> Optional[ClaimML]:
    """
    Enrich a single claim by calling 7+ ML API endpoints via webhook proxy.
    Saves ALL data to rma_claims_ml cache after fetching.
    Returns ClaimML or None if the base API call fails.
    Retries up to _max_retries times on timeout/connection errors.
    """
    import time as _time

    for attempt in range(_max_retries + 1):
        try:
            return _enrich_claim_via_http_attempt(claim_id)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            if attempt < _max_retries:
                wait = 2**attempt  # 1s, 2s
                logger.info(
                    "[claims] Retry %d/%d for claim %s after %s (wait %ds)",
                    attempt + 1,
                    _max_retries,
                    claim_id,
                    type(exc).__name__,
                    wait,
                )
                _time.sleep(wait)
            else:
                logger.warning(
                    "[claims] EXCEPTION enriching claim %s after %d retries", claim_id, _max_retries, exc_info=True
                )
                return None
        except Exception:
            logger.warning("[claims] EXCEPTION enriching claim %s", claim_id, exc_info=True)
            return None
    return None


def _enrich_claim_via_http_attempt(claim_id: str) -> Optional[ClaimML]:
    """Single attempt to enrich a claim. Raises on timeout/connection errors."""
    try:
        with httpx.Client(timeout=_HTTPX_TIMEOUT) as client:
            # 1. Claim base data (required — if this fails, abort)
            r1 = client.get(
                ML_WEBHOOK_RENDER_URL,
                params={
                    "resource": f"/post-purchase/v1/claims/{claim_id}",
                    "format": "json",
                },
            )
            if r1.status_code != 200:
                logger.warning("[claims] Base claim %s returned status %s", claim_id, r1.status_code)
                return None
            claim_data = r1.json()
            logger.info("[claims] Fetched base claim %s (status=%s)", claim_id, claim_data.get("status"))

            # 2-7. All secondary endpoints
            (
                detail_data,
                reason_data,
                expected_res_data,
                return_data,
                change_data,
                messages_data,
                affects_rep_data,
            ) = _fetch_all_ml_endpoints(client, claim_id, claim_data)

            # Build the ClaimML schema
            claim = _build_claim_from_ml_api(
                claim_data,
                detail_data=detail_data,
                reason_data=reason_data,
                expected_res_data=expected_res_data,
                return_data=return_data,
                change_data=change_data,
                messages_data=messages_data,
                affects_rep_data=affects_rep_data,
            )
            logger.info("[claims] Built ClaimML %s OK", claim_id)

            # Save to local cache (fire-and-forget: uses its own session)
            _save_claim_to_cache(
                claim,
                raw_claim=claim_data,
                raw_detail=detail_data,
                raw_reason=reason_data,
                return_data=return_data,
                change_data=change_data,
                expected_res_data=expected_res_data,
                messages_data=messages_data,
                affects_rep_data=affects_rep_data,
            )

            # Save messages to cache (only if we got messages)
            if messages_data:
                has_messages = (isinstance(messages_data, list) and len(messages_data) > 0) or (
                    isinstance(messages_data, dict) and messages_data.get("data")
                )
                if has_messages:
                    _save_messages_to_cache(claim_id, messages_data)

            return claim
    except (httpx.TimeoutException, httpx.ConnectError):
        raise  # Let the retry wrapper handle these
    except Exception:
        logger.warning("[claims] EXCEPTION enriching claim %s", claim_id, exc_info=True)
        return None


def _search_claims_via_api(order_ids: list[str], exclude_claim_ids: set[str]) -> list[ClaimML]:
    """
    Search for claims via ML API (through webhook proxy) by order_id.
    Skips claims already found in the DB (by claim_id).
    Returns list of ClaimML.
    """
    claims: list[ClaimML] = []
    try:
        with httpx.Client(timeout=_HTTPX_TIMEOUT) as client:
            for order_id in order_ids:
                try:
                    r = client.get(
                        ML_WEBHOOK_RENDER_URL,
                        params={
                            "resource": f"/post-purchase/v1/claims/search?order_id={order_id}",
                            "format": "json",
                        },
                    )
                    if r.status_code != 200:
                        continue
                    search_data = r.json()
                    for claim_data in search_data.get("data") or []:
                        cid = str(claim_data.get("id", ""))
                        if cid in exclude_claim_ids:
                            continue
                        exclude_claim_ids.add(cid)
                        # Enrich with ALL endpoints (saves to cache internally)
                        enriched = _enrich_claim_via_http(cid)
                        if enriched:
                            claims.append(enriched)
                except Exception:
                    logger.debug(
                        "Failed to search claims for order %s",
                        order_id,
                        exc_info=True,
                    )
                    continue
    except Exception:
        logger.warning("Failed to create HTTP client for claims search", exc_info=True)
    return claims


def _fetch_claims_by_order_ids(order_ids: list[str]) -> list[ClaimML]:
    """
    Busca claims de MercadoLibre por order IDs con invalidación por webhook.

    Flujo:
    1. Cargar cache local (rma_claims_ml) → indexar por claim_id
    2. Consultar webhook DB (ml_previews) → para cada claim:
       a. Si NO está en cache → enriquecer vía HTTP y guardar
       b. Si está en cache pero ml_previews.last_updated > cache.updated_at
          → el webhook recibió un cambio → re-enriquecer vía HTTP
       c. Si está en cache y es más reciente que ml_previews → usar cache
    3. Claims en cache que NO aparecieron en ml_previews:
       - Cerrados → usar cache (nunca cambian)
       - Abiertos → fallback por tiempo (24hs) en caso de que la webhook DB
         no tenga el registro (raro pero posible)
    4. Search ML API → para claims que no están en ninguna DB

    Silencioso: si algún paso falla, continúa con el siguiente.
    """
    if not order_ids:
        return []

    logger.info("[claims] _fetch_claims_by_order_ids called with order_ids=%s", order_ids)

    claims: list[ClaimML] = []
    seen_claim_ids: set[str] = set()
    # Cache rows indexed by claim_id (str) for comparison in Step 2
    cache_by_claim_id: dict[str, RmaClaimML] = {}
    # Track which cached claims were checked against ml_previews
    cache_checked_via_webhook: set[str] = set()

    # ── Step 1: Load local cache (rma_claims_ml) ────────────────────────────
    try:
        with get_background_db() as session:
            order_id_ints = []
            for oid in order_ids:
                try:
                    order_id_ints.append(int(oid))
                except (ValueError, TypeError):
                    continue

            if order_id_ints:
                cached_rows = session.query(RmaClaimML).filter(RmaClaimML.resource_id.in_(order_id_ints)).all()
                for row in cached_rows:
                    # Expunge para que el objeto sobreviva fuera de la sesión.
                    # Sin esto, acceder a columnas JSONB (expected_resolutions_detail,
                    # return_data, etc.) después de cerrar la sesión causa
                    # DetachedInstanceError.
                    session.expunge(row)
                    cid = str(row.claim_id)
                    cache_by_claim_id[cid] = row
    except Exception:
        logger.warning("Failed to read claims from local cache", exc_info=True)

    # ── Step 2: Webhook DB (ml_previews) — invalidation source ──────────────
    webhook_db_available = False
    try:
        engine = get_mlwebhook_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT
                        p.resource,
                        p.status,
                        p.title,
                        p.extra_data,
                        p.last_updated
                    FROM ml_previews p
                    WHERE p.resource LIKE '/post-purchase/v1/claims/%'
                      AND p.resource NOT LIKE '%/detail'
                      AND p.resource NOT LIKE '%/reasons/%'
                      AND p.resource NOT LIKE '%/search%'
                      AND p.resource NOT LIKE '%/actions-history'
                      AND p.resource NOT LIKE '%/status-history'
                      AND (p.extra_data->>'resource_id')::text = ANY(:order_ids)
                    ORDER BY p.last_updated DESC
                """),
                {"order_ids": order_ids},
            ).fetchall()

        webhook_db_available = True

        for row in rows:
            resource, db_status, title, extra, webhook_last_updated = row
            ed = extra or {}

            # Extract claim_id
            claim_id = str(ed.get("claim_id", ""))
            if not claim_id:
                parts = resource.rstrip("/").split("/")
                claim_id = parts[-1] if parts[-1].isdigit() else ""

            if not claim_id or claim_id in seen_claim_ids:
                continue
            seen_claim_ids.add(claim_id)
            cache_checked_via_webhook.add(claim_id)

            cached_row = cache_by_claim_id.get(claim_id)

            if cached_row:
                # Compare timestamps: did webhook receive an update after our cache?
                cache_updated = cached_row.updated_at
                if cache_updated and cache_updated.tzinfo is None:
                    cache_updated = cache_updated.replace(tzinfo=timezone.utc)
                wh_updated = webhook_last_updated
                if wh_updated and hasattr(wh_updated, "tzinfo") and wh_updated.tzinfo is None:
                    wh_updated = wh_updated.replace(tzinfo=timezone.utc)

                if wh_updated and cache_updated and wh_updated <= cache_updated:
                    # Cache is up-to-date — use it
                    claims.append(_build_claim_from_db_cache(cached_row))
                    continue

                # Webhook is newer → re-enrich via HTTP
                enriched = _enrich_claim_via_http(claim_id)
                if enriched:
                    claims.append(enriched)
                else:
                    # HTTP failed — use stale cache as fallback
                    claims.append(_build_claim_from_db_cache(cached_row))
                continue

            # Not in cache at all — enrich from scratch
            if ed.get("claim_id") and ed.get("triage_tags"):
                # Webhook has enriched data — use it and save to cache
                built = _build_claim_from_enriched_extra(ed, status_override=db_status, title_fallback=title)
                claims.append(built)
                _save_claim_to_cache(built)
                continue

            # Incomplete data — full HTTP enrich (saves to cache internally)
            enriched = _enrich_claim_via_http(claim_id)
            if enriched:
                claims.append(enriched)

    except RuntimeError:
        # ML_WEBHOOK_DB_URL not configured — skip webhook DB
        pass
    except Exception:
        logger.warning("Failed to fetch claims from webhook DB", exc_info=True)

    # ── Step 3: Cached claims NOT seen in ml_previews ───────────────────────
    for cid, cached_row in cache_by_claim_id.items():
        if cid in seen_claim_ids:
            continue
        seen_claim_ids.add(cid)

        if not webhook_db_available and _is_cache_stale_by_time(cached_row):
            # Webhook DB unavailable — time-based fallback for open claims
            enriched = _enrich_claim_via_http(cid)
            if enriched:
                claims.append(enriched)
            else:
                claims.append(_build_claim_from_db_cache(cached_row))
        else:
            # Webhook DB was available but claim wasn't there, or cache is fresh
            claims.append(_build_claim_from_db_cache(cached_row))

    # ── Step 4: Search ML API for claims not found anywhere ─────────────────
    api_claims = _search_claims_via_api(order_ids, seen_claim_ids)
    claims.extend(api_claims)

    return claims


# =============================================================================
# ENDPOINT
# =============================================================================


@router.get(
    "/claims/{claim_id}/messages",
    response_model=list[ClaimMessageResponse],
)
def get_claim_messages(
    claim_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[ClaimMessageResponse]:
    """
    Devuelve los mensajes cacheados de un reclamo de ML.
    Si no hay mensajes en cache, intenta fetchearlos de la API de ML,
    los guarda en cache y los devuelve.
    """
    # 1. Try local cache first
    rows = (
        db.query(RmaClaimMLMessage)
        .filter(RmaClaimMLMessage.claim_id == claim_id)
        .order_by(RmaClaimMLMessage.ml_date_created.asc())
        .all()
    )
    if rows:
        return rows

    # 2. Fetch from ML API and save to cache
    claim_id_str = str(claim_id)
    try:
        with httpx.Client(timeout=_HTTPX_TIMEOUT) as client:
            r = client.get(
                ML_WEBHOOK_RENDER_URL,
                params={
                    "resource": f"/post-purchase/v1/claims/{claim_id_str}/messages",
                    "format": "json",
                },
            )
            if r.status_code == 200:
                messages_data = r.json()
                _save_messages_to_cache(claim_id_str, messages_data)

                # Re-query after save
                rows = (
                    db.query(RmaClaimMLMessage)
                    .filter(RmaClaimMLMessage.claim_id == claim_id)
                    .order_by(RmaClaimMLMessage.ml_date_created.asc())
                    .all()
                )
                return rows
    except Exception:
        logger.warning(
            "[claims] Failed to fetch messages for claim %s",
            claim_id,
            exc_info=True,
        )

    return []
