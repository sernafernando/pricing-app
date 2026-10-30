"""Fetch and persist the latest Full inbound reception (Target source).

ML contract (probed 2026-10-30):
  GET /stock/fulfillment/operations/search
    seller_id, inventory_id, date_from, date_to as YYYY-MM-DD
    type=INBOUND_RECEPTION
    max range 60 days per call
  Target qty = detail.available_quantity of the newest result.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ml_fulfillment_last_inbound import MlFulfillmentLastInbound
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import Pacer

ENDPOINT_FAMILY = "fulfillment_operations"
OPERATIONS_PATH = "/stock/fulfillment/operations/search"
MAX_RANGE_DAYS = 60
LOOKBACK_DAYS = 365  # ML keeps ~12 months; walk in 60-day windows
TYPE_INBOUND = "INBOUND_RECEPTION"


def _parse_occurred_at(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _inbound_id_from_refs(refs: Any) -> Optional[str]:
    if not isinstance(refs, list):
        return None
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        if str(ref.get("type") or "").lower() == "inbound_id":
            value = ref.get("value")
            return str(value) if value is not None else None
    return None


def pick_last_inbound(results: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Newest INBOUND_RECEPTION with a non-null available_quantity."""
    candidates: list[tuple[datetime, dict[str, Any], int]] = []
    for row in results:
        if str(row.get("type") or "").upper() != TYPE_INBOUND:
            continue
        occurred = _parse_occurred_at(row.get("date_created"))
        if occurred is None:
            continue
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        qty = detail.get("available_quantity")
        if qty is None:
            continue
        try:
            cantidad = int(qty)
        except (TypeError, ValueError):
            continue
        candidates.append((occurred, row, cantidad))
    if not candidates:
        return None
    occurred, row, cantidad = max(candidates, key=lambda item: item[0])
    op_id = row.get("id")
    try:
        operation_id = int(op_id) if op_id is not None else None
    except (TypeError, ValueError):
        operation_id = None
    return {
        "cantidad": cantidad,
        "occurred_at": occurred,
        "operation_id": operation_id,
        "inbound_id": _inbound_id_from_refs(row.get("external_references")),
    }


def _window_bounds(end: date, *, span_days: int = MAX_RANGE_DAYS) -> tuple[date, date]:
    start = end - timedelta(days=span_days - 1)
    return start, end


def fetch_last_inbound_for_inventory(
    client: MlHttpClient,
    *,
    inventory_id: str,
    seller_id: Optional[str] = None,
    today: Optional[date] = None,
    lookback_days: int = LOOKBACK_DAYS,
) -> Optional[dict[str, Any]]:
    """Walk 60-day windows backward until an inbound is found or lookback ends."""
    seller = seller_id or str(settings.ML_USER_ID or "")
    if not seller or not inventory_id:
        return None

    cursor_end = today or datetime.now(UTC).date()
    earliest = cursor_end - timedelta(days=max(1, lookback_days))
    best: Optional[dict[str, Any]] = None
    saw_success = False

    while cursor_end >= earliest:
        start, end = _window_bounds(cursor_end)
        if start < earliest:
            start = earliest
        response = client.get(
            ENDPOINT_FAMILY,
            OPERATIONS_PATH,
            {
                "seller_id": seller,
                "inventory_id": inventory_id,
                "date_from": start.isoformat(),
                "date_to": end.isoformat(),
                "type": TYPE_INBOUND,
            },
        )
        if response.status == 429:
            break
        if response.status != 200 or not isinstance(response.body, dict):
            cursor_end = start - timedelta(days=1)
            continue
        saw_success = True
        results = response.body.get("results") or []
        if not isinstance(results, list):
            results = []
        picked = pick_last_inbound([r for r in results if isinstance(r, dict)])
        if picked is not None:
            best = picked
            break
        cursor_end = start - timedelta(days=1)

    if best is not None:
        return best
    if saw_success:
        return {"cantidad": None, "occurred_at": None, "operation_id": None, "inbound_id": None}
    return None


def upsert_last_inbound(
    db: Session,
    *,
    inventory_id: str,
    cantidad: Optional[int],
    occurred_at: Optional[datetime],
    operation_id: Optional[int] = None,
    inbound_id: Optional[str] = None,
) -> MlFulfillmentLastInbound:
    """Create or replace the snapshot row for inventory_id."""
    now = datetime.now(UTC)
    row = db.get(MlFulfillmentLastInbound, inventory_id)
    if row is None:
        row = MlFulfillmentLastInbound(
            inventory_id=inventory_id,
            cantidad=cantidad,
            occurred_at=occurred_at,
            operation_id=operation_id,
            inbound_id=inbound_id,
            fetched_at=now,
        )
        db.add(row)
    else:
        if cantidad is not None:
            row.cantidad = cantidad
            row.occurred_at = occurred_at
            row.operation_id = operation_id
            row.inbound_id = inbound_id
        # Empty check: keep prior Target, only bump fetched_at.
        row.fetched_at = now
    db.commit()
    db.refresh(row)
    return row


_CLAIM_SQL = text(
    """
    SELECT DISTINCT i.inventory_id
    FROM ml_items i
    WHERE i.inventory_id IS NOT NULL
      AND i.never_existed IS NOT TRUE
      AND i.gone_at IS NULL
      AND NOT EXISTS (
        SELECT 1
        FROM ml_fulfillment_last_inbound f
        WHERE f.inventory_id = i.inventory_id
          AND f.fetched_at >= :fresh_after
      )
    ORDER BY i.inventory_id
    LIMIT :limit
    """
)


def claim_inventory_ids_for_inbound_refresh(
    db: Session,
    *,
    limit: int = 1,
    fresh_within_days: int = 6,
    now: Optional[datetime] = None,
) -> list[str]:
    """Oldest-unchecked Full inventory_ids (skip ones fetched within fresh_within_days)."""
    moment = now or datetime.now(UTC)
    fresh_after = moment - timedelta(days=max(1, fresh_within_days))
    rows = (
        db.execute(
            _CLAIM_SQL,
            {"limit": max(1, limit), "fresh_after": fresh_after},
        )
        .scalars()
        .all()
    )
    return [str(r) for r in rows]


def refresh_last_inbound(
    db: Session,
    inventory_id: str,
    *,
    client: Optional[MlHttpClient] = None,
    lookback_days: int = LOOKBACK_DAYS,
) -> Optional[MlFulfillmentLastInbound]:
    """Call ML and persist the newest inbound for one inventory_id."""
    owns_client = client is None
    http = client or MlHttpClient(pacer=Pacer())
    try:
        picked = fetch_last_inbound_for_inventory(http, inventory_id=inventory_id, lookback_days=lookback_days)
        if picked is None:
            return None
        return upsert_last_inbound(
            db,
            inventory_id=inventory_id,
            cantidad=picked["cantidad"],
            occurred_at=picked["occurred_at"],
            operation_id=picked.get("operation_id"),
            inbound_id=picked.get("inbound_id"),
        )
    finally:
        if owns_client:
            http.close()
