"""Upsert live seller promotions from the ml-webhook proxy into the mirror DB.

Used when Pricing's `ML_WEBHOOK_DB_URL` is NOT the same database that the
proxy refreshes (local sandbox): after `refresh_item_promotions` succeeds,
the panel still reads `ml_item_promotions` via `get_mlwebhook_engine()`, so
we copy the proxy's live GET into that engine.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Dict, Optional, Set

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, TEXT

from app.core.database import get_mlwebhook_engine
from app.core.logging import get_logger
from app.services.ml_webhook_client import ml_webhook_client
from app.utils.async_bridge import resolve_maybe_async

logger = get_logger(__name__)


def _promotion_id(entry: Dict[str, Any]) -> Optional[str]:
    """PRICE_DISCOUNT often has no `id`; ML uses type as the key."""
    raw = entry.get("id") or entry.get("type")
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _num(entry: Dict[str, Any], key: str) -> Optional[float]:
    value = entry.get(key)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def upsert_item_promotions_from_proxy(mla_id: str) -> bool:
    """Fetch live promos for `mla_id` from the proxy and upsert the mirror.

    Returns:
        True when the live payload was applied (including an empty list that
        finishes every prior row). False when the live read failed — the
        caller keeps the previous mirror and still reports refresh ok/fail
        from the proxy refresh itself.
    """
    live = resolve_maybe_async(ml_webhook_client.get_item_promotions(mla_id))
    if live is None:
        logger.warning("promo mirror sync skipped for %s: live GET unavailable", mla_id)
        return False
    if not isinstance(live, list):
        logger.warning("promo mirror sync skipped for %s: unexpected payload type %s", mla_id, type(live).__name__)
        return False

    now = datetime.now(UTC)
    seen: Set[str] = set()
    engine = get_mlwebhook_engine()

    with engine.begin() as conn:
        for entry in live:
            if not isinstance(entry, dict):
                continue
            promotion_id = _promotion_id(entry)
            if not promotion_id:
                continue
            seen.add(promotion_id)
            promotion_type = entry.get("type")
            sub_type = entry.get("sub_type")
            status = entry.get("status")
            name = entry.get("name") or None
            start_date = entry.get("start_date") or None
            finish_date = entry.get("finish_date") or None
            payload = dict(entry)

            conn.execute(
                text(
                    """
                    INSERT INTO ml_promotions (
                      promotion_id, promotion_type, sub_type, status, name,
                      start_date, finish_date, deadline_date, payload, updated_at
                    ) VALUES (
                      :promotion_id, :promotion_type, :sub_type, :status, :name,
                      CAST(:start_date AS timestamptz), CAST(:finish_date AS timestamptz),
                      NULL, CAST(:payload AS jsonb), :updated_at
                    )
                    ON CONFLICT (promotion_id) DO UPDATE SET
                      promotion_type = EXCLUDED.promotion_type,
                      sub_type = EXCLUDED.sub_type,
                      status = EXCLUDED.status,
                      name = COALESCE(EXCLUDED.name, ml_promotions.name),
                      start_date = COALESCE(EXCLUDED.start_date, ml_promotions.start_date),
                      finish_date = COALESCE(EXCLUDED.finish_date, ml_promotions.finish_date),
                      payload = EXCLUDED.payload,
                      updated_at = EXCLUDED.updated_at
                    """
                ),
                {
                    "promotion_id": promotion_id,
                    "promotion_type": promotion_type,
                    "sub_type": sub_type,
                    "status": status,
                    "name": name,
                    "start_date": start_date,
                    "finish_date": finish_date,
                    "payload": json.dumps(payload),
                    "updated_at": now,
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO ml_item_promotions (
                      mla, promotion_id, promotion_type, sub_type, status,
                      original_price, price, min_discounted_price, max_discounted_price,
                      suggested_discounted_price, payload, updated_at
                    ) VALUES (
                      :mla, :promotion_id, :promotion_type, :sub_type, :status,
                      :original_price, :price, :min_discounted_price, :max_discounted_price,
                      :suggested_discounted_price, CAST(:payload AS jsonb), :updated_at
                    )
                    ON CONFLICT (mla, promotion_id) DO UPDATE SET
                      promotion_type = EXCLUDED.promotion_type,
                      sub_type = EXCLUDED.sub_type,
                      status = EXCLUDED.status,
                      original_price = EXCLUDED.original_price,
                      price = EXCLUDED.price,
                      min_discounted_price = EXCLUDED.min_discounted_price,
                      max_discounted_price = EXCLUDED.max_discounted_price,
                      suggested_discounted_price = EXCLUDED.suggested_discounted_price,
                      payload = EXCLUDED.payload,
                      updated_at = EXCLUDED.updated_at
                    """
                ),
                {
                    "mla": mla_id,
                    "promotion_id": promotion_id,
                    "promotion_type": promotion_type,
                    "sub_type": sub_type,
                    "status": status,
                    "original_price": _num(entry, "original_price"),
                    "price": _num(entry, "price"),
                    "min_discounted_price": _num(entry, "min_discounted_price"),
                    "max_discounted_price": _num(entry, "max_discounted_price"),
                    "suggested_discounted_price": _num(entry, "suggested_discounted_price"),
                    "payload": json.dumps(payload),
                    "updated_at": now,
                },
            )

        if seen:
            finish_stmt = text(
                """
                UPDATE ml_item_promotions
                SET status = 'finished', updated_at = :updated_at
                WHERE mla = :mla
                  AND status IS DISTINCT FROM 'finished'
                  AND NOT (promotion_id = ANY(:ids))
                """
            ).bindparams(bindparam("ids", type_=ARRAY(TEXT)))
            conn.execute(
                finish_stmt,
                {"mla": mla_id, "updated_at": now, "ids": list(seen)},
            )
        else:
            conn.execute(
                text(
                    """
                    UPDATE ml_item_promotions
                    SET status = 'finished', updated_at = :updated_at
                    WHERE mla = :mla
                      AND status IS DISTINCT FROM 'finished'
                    """
                ),
                {"mla": mla_id, "updated_at": now},
            )

    logger.info("promo mirror sync applied for %s (%d live entries)", mla_id, len(seen))
    return True
