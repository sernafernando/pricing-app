"""
Write-orchestration service for ML Seller Promotions (PR2).

Owns the policy for enroll/remove writes against the ML Central de
Promociones proxy (ml-webhook), on top of the read primitives already
built in PR1 (`ml_promotions_service.fetch_item_promotions`,
`MLWebhookClient.get_item_promotions`).

Order of operations (`enroll_one_item` / `remove_one_item`):
  1. Kill-switch (`settings.PROMOS_WRITE_ENABLED`) checked FIRST, before
     any read or proxy call. This is a local gate, independent of the
     proxy's own authorization.
  2. `promotion_type` restricted to SELLER_CAMPAIGN / DEAL — the only
     writable types (PRICE_DISCOUNT/SMART/DOD/LIGHTNING are read-only
     always, per spec).
  3. Fresh LIVE read of the item (`ml_webhook_client.get_item_promotions`)
     to obtain the current [min_discounted_price, max_discounted_price]
     and `suggested_discounted_price` for the target promotion. Never a
     cached/stale value.
  4. Defensive range validation: `deal_price` must be within
     [min, max] BEFORE the POST — reject out-of-range without a wasted
     round-trip to the proxy.
  5. Single POST/DELETE via `MLWebhookClient` (no retry — a blind retry
     on an ambiguous write could double-apply it).
  6. On ambiguous outcome (timeout/5xx): reconcile via
     `ml_item_promotions` (mirrors the `reconciliar_ml_cancelaciones.py`
     precedent — read-the-source-of-truth instead of retrying the write).
     On success (2xx): return `submitted` WITHOUT asserting a confirmed
     `enrolled` state — eventual consistency means an immediate read-back
     can still show `candidate` for up to ~2s; `ml_item_promotions`
     remains the source of truth, not the 201 response.

This module is intentionally NOT a cron/script: writes are single-item,
low-volume, human-triggered, so reconciliation happens inline on the
ambiguous response rather than via a scheduled sweep (see design decision).
"""

import asyncio
import inspect
import logging
from typing import Any, Dict, Optional

from app.core.config import settings
from app.services.ml_promotions_service import fetch_item_promotions
from app.services.ml_webhook_client import ml_webhook_client

logger = logging.getLogger(__name__)

WRITABLE_PROMOTION_TYPES = {"SELLER_CAMPAIGN", "DEAL"}


def _resolve(value: Any) -> Any:
    """Bridges `MLWebhookClient`'s async methods into this module's
    synchronous API. Real calls return a coroutine (awaited here via
    `asyncio.run`); unit-test mocks (`patch.object(..., return_value=...)`)
    return the plain value directly, so both paths work unchanged.
    """
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value


def _disabled_outcome() -> Dict[str, Any]:
    """Outcome returned when PROMOS_WRITE_ENABLED is False (kill-switch)."""
    return {
        "submitted": False,
        "status": "disabled",
        "detail": "Writes are disabled (PROMOS_WRITE_ENABLED=false)",
    }


def _rejected_unsupported_type(promotion_type: str) -> Dict[str, Any]:
    return {
        "submitted": False,
        "status": "rejected_unsupported_type",
        "detail": (
            f"promotion_type={promotion_type!r} is not writable; only "
            f"{sorted(WRITABLE_PROMOTION_TYPES)} support enroll/remove"
        ),
    }


def _find_live_promotion(live_item_promotions: Optional[Dict[str, Any]], promotion_id: str) -> Optional[Dict[str, Any]]:
    """Locates the target promotion's pricing block in a live get_item_promotions() payload."""
    if not live_item_promotions:
        return None
    for promo in live_item_promotions.get("promotions") or []:
        if promo.get("promotion_id") == promotion_id:
            return promo
    return None


_RECONCILED_ROW_FIELDS = (
    "mla",
    "promotion_id",
    "promotion_type",
    "status",
    "original_price",
    "price",
    "min_discounted_price",
    "max_discounted_price",
    "suggested_discounted_price",
    "updated_at",
)


def _trim_reconciled_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Strips the raw `payload` JSONB (and any other non-whitelisted keys)
    from a `ml_item_promotions` row before it goes into an API response —
    only the fields the caller actually needs are exposed."""
    if row is None:
        return None
    return {field: row.get(field) for field in _RECONCILED_ROW_FIELDS if field in row}


def reconcile_write_outcome(mla_id: str, promotion_id: str, operation: str = "enroll") -> Dict[str, Any]:
    """Reconciles an ambiguous write outcome by reading `ml_item_promotions`
    (source of truth), mirroring the `reconciliar_ml_cancelaciones.py`
    precedent: read-then-classify instead of retrying the original write.

    The interpretation of "row present" is DIRECTION-DEPENDENT:
      - operation="enroll": row present (candidate/started/finished) means
        the enrollment IS in effect -> reconciled_applied. Row absent ->
        reconciled_not_applied.
      - operation="remove": row absent means the removal DID take effect
        (the price is no longer discounted) -> reconciled_applied. Row
        still present means the removal did NOT take effect (item is
        still discounted) -> reconciled_not_applied.

    Returns:
        `{status: "reconciled_applied"|"reconciled_not_applied"|"ambiguous", row}`.
        `status="ambiguous"` when the reconciliation read itself fails
        (e.g. `ML_WEBHOOK_DB_URL` unset / DB error) — we genuinely don't
        know the outcome in that case.
    """
    try:
        rows = fetch_item_promotions(mla_id)
    except Exception as e:
        logger.error("Reconciliation read failed for %s/%s: %s", mla_id, promotion_id, e)
        return {"status": "ambiguous", "row": None}

    matched_row: Optional[Dict[str, Any]] = None
    for row in rows:
        if row.get("promotion_id") == promotion_id:
            matched_row = row
            break

    row_present = matched_row is not None
    applied = (not row_present) if operation == "remove" else row_present

    status = "reconciled_applied" if applied else "reconciled_not_applied"
    return {"status": status, "row": _trim_reconciled_row(matched_row)}


def enroll_one_item(
    mla_id: str,
    promotion_id: str,
    promotion_type: str,
    deal_price: Optional[float] = None,
    top_deal_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Enrolls a single item in a promotion (SELLER_CAMPAIGN or DEAL only).

    Args:
        mla_id: The item ID (e.g. MLA2361127120).
        promotion_id: Target promotion ID.
        promotion_type: Must be SELLER_CAMPAIGN or DEAL.
        deal_price: Discounted price to submit. If None, defaults to the
            item's fresh `suggested_discounted_price`.
        top_deal_price: Optional cap price.

    Returns:
        See module docstring for the outcome contract. Keys always
        include `submitted` and `status`; on submission also `price` and
        `original_price` (echoed), never asserting a confirmed `enrolled`
        state.
    """
    if not settings.PROMOS_WRITE_ENABLED:
        return _disabled_outcome()

    if promotion_type not in WRITABLE_PROMOTION_TYPES:
        return _rejected_unsupported_type(promotion_type)

    live = _resolve(ml_webhook_client.get_item_promotions(mla_id))
    if live is None:
        logger.warning(
            "ML promo enroll rejected_read_unavailable mla=%s promotion_id=%s promotion_type=%s",
            mla_id,
            promotion_id,
            promotion_type,
        )
        return {
            "submitted": False,
            "status": "rejected_read_unavailable",
            "detail": "Live get_item_promotions() read failed; refusing to write without a fresh price check",
        }

    promo = _find_live_promotion(live, promotion_id)
    if promo is None:
        logger.warning(
            "ML promo enroll rejected_promotion_not_found mla=%s promotion_id=%s promotion_type=%s",
            mla_id,
            promotion_id,
            promotion_type,
        )
        return {
            "submitted": False,
            "status": "rejected_promotion_not_found",
            "detail": f"promotion_id={promotion_id!r} not present in the live item promotions payload",
        }

    min_price = promo.get("min_discounted_price")
    max_price = promo.get("max_discounted_price")
    suggested = promo.get("suggested_discounted_price")

    if deal_price is None:
        deal_price = suggested

    if deal_price is None or min_price is None or max_price is None:
        logger.warning(
            "ML promo enroll rejected_price_unresolved mla=%s promotion_id=%s promotion_type=%s deal_price=%s",
            mla_id,
            promotion_id,
            promotion_type,
            deal_price,
        )
        return {
            "submitted": False,
            "status": "rejected_price_unresolved",
            "detail": "deal_price could not be resolved or the live [min,max] range is unavailable",
        }

    if not (min_price <= deal_price <= max_price):
        logger.warning(
            "ML promo enroll rejected_out_of_range mla=%s promotion_id=%s promotion_type=%s deal_price=%s min=%s max=%s",
            mla_id,
            promotion_id,
            promotion_type,
            deal_price,
            min_price,
            max_price,
        )
        return {
            "submitted": False,
            "status": "rejected_out_of_range",
            "detail": f"deal_price={deal_price} outside [{min_price}, {max_price}]",
        }

    write_result = _resolve(
        ml_webhook_client.enroll_item(mla_id, promotion_id, promotion_type, deal_price, top_deal_price=top_deal_price)
    )
    return _classify_write_outcome(
        write_result, mla_id, promotion_id, price=deal_price, promotion_type=promotion_type, operation="enroll"
    )


def remove_one_item(mla_id: str, promotion_type: str, promotion_id: str) -> Dict[str, Any]:
    """Removes a single item from a promotion (SELLER_CAMPAIGN or DEAL only).

    Args:
        mla_id: The item ID.
        promotion_type: Must be SELLER_CAMPAIGN or DEAL.
        promotion_id: Target promotion ID.

    Returns:
        See module docstring for the outcome contract.
    """
    if not settings.PROMOS_WRITE_ENABLED:
        return _disabled_outcome()

    if promotion_type not in WRITABLE_PROMOTION_TYPES:
        return _rejected_unsupported_type(promotion_type)

    write_result = _resolve(ml_webhook_client.remove_item(mla_id, promotion_type, promotion_id))
    return _classify_write_outcome(
        write_result, mla_id, promotion_id, price=None, promotion_type=promotion_type, operation="remove"
    )


def _classify_write_outcome(
    write_result: Dict[str, Any],
    mla_id: str,
    promotion_id: str,
    price: Optional[float],
    promotion_type: Optional[str] = None,
    operation: str = "enroll",
) -> Dict[str, Any]:
    """Classifies a single-shot POST/DELETE result into the final outcome.

    2xx -> submitted (source of truth is `ml_item_promotions`, NOT this
    response — eventual consistency, no immediate "enrolled" assertion).
    4xx (ambiguous=False) -> definitive rejection by the proxy, no
    reconciliation attempted.
    timeout/5xx (ambiguous=True) -> reconcile via `ml_item_promotions`,
    direction-aware (`operation`) — see `reconcile_write_outcome`.
    """
    if write_result["ok"]:
        logger.info(
            "ML promo write submitted operation=%s mla=%s promotion_id=%s promotion_type=%s price=%s status_code=%s",
            operation,
            mla_id,
            promotion_id,
            promotion_type,
            price,
            write_result["status_code"],
        )
        return {
            "submitted": True,
            "status": "submitted",
            "price": price,
            "status_code": write_result["status_code"],
        }

    if not write_result["ambiguous"]:
        logger.warning(
            "ML promo write rejected_by_proxy operation=%s mla=%s promotion_id=%s promotion_type=%s status_code=%s",
            operation,
            mla_id,
            promotion_id,
            promotion_type,
            write_result["status_code"],
        )
        return {
            "submitted": False,
            "status": "rejected_by_proxy",
            "status_code": write_result["status_code"],
            "detail": write_result.get("body"),
        }

    reconciliation = reconcile_write_outcome(mla_id, promotion_id, operation=operation)
    if reconciliation["status"] == "ambiguous":
        logger.warning(
            "ML promo write ambiguous (reconciliation read failed) operation=%s mla=%s promotion_id=%s promotion_type=%s",
            operation,
            mla_id,
            promotion_id,
            promotion_type,
        )
    elif reconciliation["status"] == "reconciled_not_applied":
        logger.warning(
            "ML promo write reconciled_not_applied operation=%s mla=%s promotion_id=%s promotion_type=%s",
            operation,
            mla_id,
            promotion_id,
            promotion_type,
        )
    else:
        logger.info(
            "ML promo write reconciled_applied operation=%s mla=%s promotion_id=%s promotion_type=%s",
            operation,
            mla_id,
            promotion_id,
            promotion_type,
        )
    return {
        "submitted": False,
        "status": reconciliation["status"],
        "status_code": write_result["status_code"],
        "reconciled_row": reconciliation["row"],
    }
