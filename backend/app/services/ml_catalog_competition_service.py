"""
Catalog-competition snapshot writer (promos-catalog-prices-and-official-store,
slice C1b).

Given a list of MLAs, fetches each one's catalog-competition listing via
`ml_webhook_client.get_catalog_competition`, buckets and prices every
competitor, and PERSISTS one snapshot row per MLA into
`ml_catalog_competition`. This is a plain service function — not an
endpoint handler — precisely so a manual refresh endpoint (slice C2) and a
future cron job can call the exact same code path unchanged.

Design reference: design #1210 sections 3.3-3.6.

Hard rules encoded here (do not relax without re-reading the design):
  - Competitors are stored EVERY ONE of them, regardless of bucket. Bucket
    filtering happens at READ time (slice C2), never at write time, so the
    bucket definition can evolve without re-fetching through the throttled
    proxy.
  - `_to_ars` NEVER falls through to the raw number on an unconvertible
    currency — it returns None. `convertir_a_pesos` itself fails OPEN
    (returns the input unchanged when `tipo_cambio` is falsy), which is
    fine for our own product cost but would silently make a USD
    competitor look ~1000x cheaper than an ARS one. This service never
    calls `convertir_a_pesos` without the `_to_ars` guard in front of it.
  - `_resolve_pricing_context` is called EXACTLY ONCE per MLA; markup for
    every competitor of that MLA reuses the same resolved context via
    `_markup_con_contexto`, never `markup_para_precio` per competitor.
  - Our own row is identified strictly by `item_id == queried mla`. No
    seller_id allowlist, no official-store cross-join.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.ml_catalog_competition import MLCatalogCompetition
from app.services.ml_promotions_pricing import _markup_con_contexto, _resolve_pricing_context
from app.services.ml_webhook_client import ml_webhook_client
from app.services.pricing_calculator import convertir_a_pesos, obtener_tipo_cambio_actual

logger = get_logger(__name__)

# WARNING threshold for a suspiciously round competitor count — see design
# risk table: `/products/{id}/items` pagination is unverified, and a round
# count like these is how silent truncation would show up.
_SUSPICIOUS_ROUND_COUNTS = frozenset({10, 20, 50, 100})


def _normalize_installments(entry: Dict[str, Any]) -> str:
    """`"0"` when there are no installments (absent/None). Otherwise
    `str(quantity)` when interest-free (`rate == 0`), or `f"{quantity}c"`
    when interest-bearing (`rate > 0`) — an interest-bearing offer is NOT
    the same offer as an interest-free one with the same installment
    count, and they must not share a bucket. Never raises: any
    unresolvable shape degrades to `"0"`.
    """
    installments = entry.get("installments")
    if not installments:
        return "0"
    try:
        quantity = int(installments.get("quantity") or 0)
        rate = float(installments.get("rate") or 0)
    except (AttributeError, TypeError, ValueError):
        return "0"
    if quantity <= 0:
        return "0"
    return f"{quantity}c" if rate > 0 else str(quantity)


# Sentinel listing id for an entry whose listing_type_id cannot be resolved.
# Marks the absence of a bucket; never treat two of these as the same bucket.
_UNKNOWN_LISTING = "unknown"


def _bucket_key(entry: Dict[str, Any]) -> str:
    """Bucket key: `"{listing_type_id}|{installments}"`.

    `listing_type_id` is the machine field and the primary component;
    `listing_label` is a human string and is NEVER part of the key so
    that two differently-worded labels for the same `listing_type_id`
    land in the same bucket. Unresolvable input collapses to
    `"unknown|0"` rather than raising. That value marks the ABSENCE of a
    bucket, so two of them must NEVER be compared for equality:
    `_build_ok_row` drops our own key to None when it degrades, which
    disables the comparison entirely. The fail-safe direction is
    "under-claim comparability", never "falsely claim cheaper than us".
    """
    try:
        listing = (entry.get("listing_type_id") or "").strip().lower() or _UNKNOWN_LISTING
    except AttributeError:
        listing = _UNKNOWN_LISTING
    cuotas = _normalize_installments(entry) if isinstance(entry, dict) else "0"
    return f"{listing}|{cuotas}"


def _to_ars(price: Optional[float], currency_id: Optional[str], tc_usd: Optional[float]) -> Optional[float]:
    """ARS value of a competitor `price`, or None when it cannot be
    established. None is NOT zero and NOT the raw number: an
    unconvertible price must be excluded from comparison and from the
    markup chain rather than silently compared as if it were ARS.

    `convertir_a_pesos` (pricing_calculator.py) returns its input
    UNCHANGED when `tipo_cambio` is falsy — acceptable fail-open for our
    own product cost, catastrophic here. This function never delegates a
    falsy-`tc_usd` USD price to it.
    """
    if price is None:
        return None
    if currency_id == "ARS":
        return float(price)
    if currency_id == "USD" and tc_usd:
        return convertir_a_pesos(float(price), "USD", tc_usd)
    return None


def _build_competitor(
    entry: Dict[str, Any],
    our_bucket_key: Optional[str],
    our_price_ars: Optional[float],
    context: Any,
    tc_usd: Optional[float],
    db: Session,
    mla: str,
) -> Dict[str, Any]:
    price = entry.get("price")
    currency_id = entry.get("currency_id")
    price_ars = _to_ars(price, currency_id, tc_usd)
    bucket_key = _bucket_key(entry)
    same_bucket = our_bucket_key is not None and bucket_key == our_bucket_key

    markup: Optional[float] = None
    if context is not None and price_ars is not None:
        markup = _markup_con_contexto(db, context, price_ars, mla=mla)

    is_cheaper_than_us: Optional[bool] = None
    if same_bucket and price_ars is not None and our_price_ars is not None:
        is_cheaper_than_us = price_ars < our_price_ars

    return {
        "seller_id": entry.get("seller_id"),
        "item_id": entry.get("item_id"),
        "seller_nickname": entry.get("nickname"),
        "price": price,
        "currency_id": currency_id,
        "price_ars": price_ars,
        "currency_unconvertible": price is not None and price_ars is None,
        "listing_type_id": entry.get("listing_type_id"),
        "listing_label": entry.get("listing_label"),
        "installments": entry.get("installments"),
        "bucket_key": bucket_key,
        "same_bucket": same_bucket,
        "markup": markup,
        "is_cheaper_than_us": is_cheaper_than_us,
        "shipping_free": bool(entry.get("shipping_free")) if "shipping_free" in entry else None,
    }


def _build_ok_row(db: Session, mla: str, payload: Dict[str, Any]) -> MLCatalogCompetition:
    raw_competitors = payload.get("competitors") or []

    our_entry = next((c for c in raw_competitors if c.get("item_id") == mla), None)
    # A degraded ("unknown|…") key is the ABSENCE of a bucket, not a bucket.
    # Keeping it would make every other degraded competitor compare equal to
    # us and produce a bogus `is_cheaper_than_us` — the exact "falsely claim
    # cheaper than us" direction this module forbids. None disables the
    # comparison instead.
    our_bucket_key = _bucket_key(our_entry) if our_entry is not None else None
    if our_bucket_key is not None and our_bucket_key.startswith(f"{_UNKNOWN_LISTING}|"):
        our_bucket_key = None
    our_price = our_entry.get("price") if our_entry is not None else None
    our_currency_id = our_entry.get("currency_id") if our_entry is not None else None
    our_seller_id = our_entry.get("seller_id") if our_entry is not None else None

    context = _resolve_pricing_context(db, mla)
    tc_usd = obtener_tipo_cambio_actual(db, "USD")
    our_price_ars = _to_ars(our_price, our_currency_id, tc_usd)

    competitors = [
        _build_competitor(entry, our_bucket_key, our_price_ars, context, tc_usd, db, mla) for entry in raw_competitors
    ]

    competitor_count = len(competitors)
    if competitor_count in _SUSPICIOUS_ROUND_COUNTS:
        logger.warning(
            "Catalog competition for %s returned a suspiciously round competitor count (%d) — "
            "possible silent pagination truncation upstream.",
            mla,
            competitor_count,
        )

    canonical_bytes = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    source_payload_hash = sha256(canonical_bytes).hexdigest()

    return MLCatalogCompetition(
        mla=mla,
        fecha_consulta=datetime.now(UTC),
        catalog_product_id=payload.get("catalog_product_id"),
        fetch_status="ok",
        our_item_id=our_entry.get("item_id") if our_entry is not None else None,
        our_seller_id=our_seller_id,
        our_price=our_price,
        our_currency_id=our_currency_id,
        our_bucket_key=our_bucket_key,
        competitors=competitors,
        competitor_count=competitor_count,
        source_payload_hash=source_payload_hash,
        error_detail=None,
    )


def _build_failed_row(mla: str, fetch_status: str, detail: Optional[str]) -> MLCatalogCompetition:
    """Row for `not_catalog` / `error` outcomes: storing the failure IS the
    point — it lets a future cron record a no-op and lets the UI
    distinguish "no aplica" from "falló" instead of showing nothing."""
    return MLCatalogCompetition(
        mla=mla,
        fecha_consulta=datetime.now(UTC),
        catalog_product_id=None,
        fetch_status=fetch_status,
        our_item_id=None,
        our_seller_id=None,
        our_price=None,
        our_currency_id=None,
        our_bucket_key=None,
        competitors=[],
        competitor_count=0,
        source_payload_hash=None,
        error_detail=detail,
    )


async def refrescar_competencia_catalogo(db: Session, mlas: List[str]) -> List[MLCatalogCompetition]:
    """Fetches, buckets, prices and PERSISTS one snapshot row per MLA in
    `mlas`. Called today by the manual per-MLA refresh endpoint (slice C2)
    and, unchanged, by a future cron — adding the cron adds no schema
    change and no new code path here.

    Never raises for a single MLA's failure: a `not_catalog` or `error`
    outcome from the client still produces a persisted row so the caller
    always gets exactly `len(mlas)` rows back.
    """
    rows: List[MLCatalogCompetition] = []

    for mla in mlas:
        # A batch is expensive: each MLA costs 3+N calls through ml-webhook's
        # globally throttled ML proxy. The commit happens once, after the
        # loop, so ANY exception here would discard every row already paid
        # for — not just this MLA's. Degrade to an error row instead.
        try:
            result = await ml_webhook_client.get_catalog_competition(mla)
            # `status` is normalised because it lands in a NOT NULL column:
            # persisting None would fail the commit for the whole batch.
            status = (result or {}).get("status") or "error"

            if status == "ok":
                row = _build_ok_row(db, mla, result.get("payload") or {})
            else:
                row = _build_failed_row(mla, status, (result or {}).get("detail"))
        except Exception as e:  # noqa: BLE001 — one MLA must not sink the batch
            logger.exception("Fallo inesperado obteniendo competencia de catálogo para %s", mla)
            row = _build_failed_row(mla, "error", str(e)[:500])

        db.add(row)
        rows.append(row)

    db.commit()
    for row in rows:
        db.refresh(row)

    return rows
