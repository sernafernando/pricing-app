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
  2. `promotion_type` restricted to the writable types SELLER_CAMPAIGN /
     DEAL / SMART / PRE_NEGOTIATED. DOD/LIGHTNING stay ML-managed
     (read-only); PRICE_DISCOUNT is out of write scope (offers array).
  3. Fresh LIVE read of the item (`ml_webhook_client.get_item_promotions`)
     to obtain the current pricing for the target promotion. Never a
     cached/stale value. For SELLER_CAMPAIGN/DEAL this yields
     [min_discounted_price, max_discounted_price] + `suggested_discounted_price`;
     for SMART/PRE_NEGOTIATED it yields the entry's `price` (the deal_price
     to submit) and its `ref_id` (the required `offer_id`), and there is NO
     [min,max].
  4. Defensive validation BEFORE the POST: for SELLER_CAMPAIGN/DEAL,
     `deal_price` must be within [min, max] (reject out-of-range without a
     wasted round-trip). For SMART/PRE_NEGOTIATED there is no range — fail
     closed instead if the entry's `price`/`ref_id` are missing.
  5. Single POST/DELETE via `MLWebhookClient` (no retry — a blind retry
     on an ambiguous write could double-apply it).
  6. On ambiguous outcome (timeout/5xx): reconcile via
     `ml_item_promotions` (mirrors the `reconciliar_ml_cancelaciones.py`
     precedent — read-the-source-of-truth instead of retrying the write).
     On success (2xx): return `submitted` WITHOUT asserting a confirmed
     `enrolled` state — eventual consistency means an immediate read-back
     can still show `candidate` for up to ~2s (SELLER_CAMPAIGN/DEAL) or
     ~10-18s (SMART, slower); `ml_item_promotions` remains the source of
     truth, not the 201 response.

This module is intentionally NOT a cron/script: writes are single-item,
low-volume, human-triggered, so reconciliation happens inline on the
ambiguous response rather than via a scheduled sweep (see design decision).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.core.database import get_background_db
from app.models.promo_refresh_pending import PromoRefreshPending
from app.models.publicacion_ml import PublicacionML
from app.services.ml_promotions_service import fetch_item_promotions
from app.services.ml_webhook_client import ml_webhook_client
from app.services.promo_price_propagation import recompute_item
from app.utils.async_bridge import resolve_maybe_async as _resolve

logger = logging.getLogger(__name__)

# Outcomes that mean the promo actually changed state at ML — only these
# are worth triggering a price recompute for.
_RECOMPUTE_TRIGGER_STATUSES = {"submitted", "reconciled_applied"}

# Outcomes worth triggering a server-side point-refresh for. Deliberately
# WIDER than _RECOMPUTE_TRIGGER_STATUSES: "ambiguous" is included here (a
# truth-revealing refresh matters most when we genuinely don't know the
# outcome), but must NEVER leak into the recompute trigger set above — a
# recompute for an outcome that may not have actually changed anything at
# ML would be wasted work at best.
_REFRESH_TRIGGER_STATUSES = {"submitted", "reconciled_applied", "ambiguous"}

# Retry queue tuning (see PromoRefreshPending / drain_promo_refresh.py).
REFRESH_RETRY_DELAY_SECONDS = 60

# NOTE: PRICE_MATCHING_MELI_ALL is intentionally EXCLUDED from this set
# (ML-autogestionado, not writable by us). Its absence here is what enforces
# the deny (enroll/remove both fail-close on `not in WRITABLE_PROMOTION_TYPES`)
# — never add it, and never use startswith/prefix matching against
# "PRICE_MATCHING" that could accidentally admit it.
WRITABLE_PROMOTION_TYPES = {"SELLER_CAMPAIGN", "DEAL", "SMART", "PRE_NEGOTIATED", "PRICE_MATCHING"}

# PRE_NEGOTIATED and PRICE_MATCHING behave identically to SMART in the write
# path: they use an `offer_id` (from the live entry's `ref_id`, not a
# promotion-id-based POST) and the entry's own `price` (no [min,max] range),
# and remove re-reads live for the current offer_id. Also share SMART's
# slower eventual-consistency window for reconciliation purposes.
# NOTE: PRICE_MATCHING_MELI_ALL is intentionally EXCLUDED here too (see
# WRITABLE_PROMOTION_TYPES comment above) — exact set membership only.
SMART_LIKE_PROMOTION_TYPES = {"SMART", "PRE_NEGOTIATED", "PRICE_MATCHING"}


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


def _find_live_promotion(
    live_item_promotions: Optional[List[Dict[str, Any]]], promotion_id: str
) -> Optional[Dict[str, Any]]:
    """Locates the target promotion's pricing block in a live
    `get_item_promotions()` payload.

    The proxy `GET /api/promociones/item/<MLA>` returns a bare LIST of promo
    entries (NOT a `{"promotions": [...]}` wrapper), and each entry's
    promotion id is in the `id` key (which may be absent for PRICE_DISCOUNT).
    """
    if not live_item_promotions:
        return None
    for promo in live_item_promotions:
        if promo.get("id") == promotion_id:
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


def reconcile_write_outcome(
    mla_id: str, promotion_id: str, operation: str = "enroll", slow_consistency: bool = False
) -> Dict[str, Any]:
    """Reconciles an ambiguous write outcome by reading `ml_item_promotions`
    (source of truth), mirroring the `reconciliar_ml_cancelaciones.py`
    precedent: read-then-classify instead of retrying the original write.

    The interpretation is DIRECTION-DEPENDENT:
      - operation="enroll": row present (candidate/started/finished) means
        the enrollment IS in effect -> reconciled_applied. Row absent ->
        reconciled_not_applied (unless slow_consistency, see below).
      - operation="remove": keyed on STATUS, not presence. A successful
        DELETE returns the item to status='candidate' — the row PERSISTS
        in `ml_item_promotions`, it does NOT disappear. So "removed" means
        the item is no longer ACTIVELY enrolled: status != 'started'
        (row absent, or status 'candidate'/'finished') -> reconciled_applied.
        Only status == 'started' means the removal did NOT take effect
        (still actively enrolled) -> reconciled_not_applied (unless
        slow_consistency, see below).

    slow_consistency (True for SMART, ~10-18s to settle vs ~2s for
    SELLER_CAMPAIGN/DEAL): the POSITIVE verdict (row present on enroll, row
    absent on remove) stays reconciled_applied — it is trustworthy either
    way. The NEGATIVE verdict (row absent on enroll, row present on remove)
    becomes "ambiguous" instead of "reconciled_not_applied": an immediate
    read can still miss a just-applied SMART write, and confidently
    reporting "not applied" would be a false negative that could make an
    operator re-apply a price that already changed.

    Returns:
        `{status: "reconciled_applied"|"reconciled_not_applied"|"ambiguous", row}`.
        `status="ambiguous"` when the reconciliation read itself fails
        (e.g. `ML_WEBHOOK_DB_URL` unset / DB error), or when slow_consistency
        is True and the read yields the negative verdict — in both cases we
        genuinely don't have a trustworthy "not applied" outcome.
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
    matched_status = matched_row.get("status") if matched_row is not None else None
    if operation == "remove":
        # A successful DELETE returns the item to 'candidate' — the row
        # PERSISTS, so presence != "still enrolled". Removal took effect
        # unless the item is still actively enrolled (status 'started').
        applied = matched_status != "started"
    else:  # enroll
        applied = row_present

    if applied:
        status = "reconciled_applied"
    elif slow_consistency:
        status = "ambiguous"
    else:
        status = "reconciled_not_applied"

    result: Dict[str, Any] = {"status": status, "row": _trim_reconciled_row(matched_row)}
    if status == "ambiguous" and slow_consistency:
        result["detail"] = (
            "SMART consistency is slower (~10-18s) than campaigns; the row "
            "may still be settling. ml_item_promotions is the source of "
            "truth — re-check it before assuming the write did not apply."
        )
    return result


def _enqueue_refresh_retry(mla_id: str) -> None:
    """Upserts a `promo_refresh_pending` row for `mla_id`, due ~60s from
    now, in a short-lived `get_background_db()` session (ADR-5 /
    DB-pool-exhaustion incident pattern — never hold a session across
    unrelated work).

    Idempotent via a NATIVE `INSERT ... ON CONFLICT (mla) DO UPDATE`, not a
    `.query().first()` read followed by `.add()` — a SELECT-then-INSERT is
    not atomic: two overlapping enroll/remove calls for the same mla can
    both read no existing row, both `.add()`, and the second `.commit()`
    then raises `IntegrityError` (caught/swallowed by the caller), silently
    dropping that mla's durable retry. The upsert makes concurrent enqueues
    for the same mla converge on one row with due_at/attempts reset,
    matching the pre-existing idempotency contract — reconcile on the
    ml-webhook side is itself an idempotent upsert, so a duplicate/extra
    refresh is harmless.

    `attempts` resets to 0 on every enqueue BY DESIGN: each fresh operator
    action deserves its own full retry window. Trade-off: repeatedly acting on
    the same mla while ml-webhook is down keeps resetting the counter so that
    row never quarantines — but each reset also re-issues the immediate
    refresh, and the 3x/day backfill is the ultimate backstop.
    """
    due_at = datetime.now(timezone.utc) + timedelta(seconds=REFRESH_RETRY_DELAY_SECONDS)
    stmt = pg_insert(PromoRefreshPending).values(mla=mla_id, due_at=due_at, attempts=0)
    stmt = stmt.on_conflict_do_update(
        index_elements=["mla"],
        set_={"due_at": due_at, "attempts": 0},
    )
    with get_background_db() as db:
        db.execute(stmt)
        db.commit()


def _maybe_refresh_after_write(mla_id: str, outcome: Dict[str, Any]) -> None:
    """Best-effort post-write hook: triggers a server-side point-refresh of
    the `ml_item_promotions` mirror for this `mla_id`, AFTER the
    enroll/remove reconciliation completed, so dependent consumers (panel/
    L1 badges, list filters, price sync) stop showing stale state until
    the next webhook/backfill cycle.

    Fires for a WIDER set of outcomes than `_maybe_recompute_after_write`
    (`_REFRESH_TRIGGER_STATUSES` includes "ambiguous" — a truth-revealing
    refresh matters most there, since we genuinely don't know what
    happened at ML). `_RECOMPUTE_TRIGGER_STATUSES` is intentionally NOT
    touched by this widening.

    Does two things, in INDEPENDENT best-effort steps: (a) enqueues a ~60s
    retry FIRST (the reliable follow-up for slower-consistency writes like
    SMART, ~10-18s) so the durable retry is guaranteed even if the immediate
    refresh below fails to run, and (b) an immediate best-effort refresh
    (campaign consistency may already be settled by the time this runs). The
    drainer is idempotent, so a successful immediate refresh just makes the
    queued retry a cheap confirming no-op.

    Defensive by design, mirroring `_maybe_recompute_after_write`'s
    isolation contract exactly: the enroll/remove already happened at ML
    by the time this runs, so a refresh/enqueue failure (mlwebhook down,
    route absent, DB error) must NEVER corrupt or reverse the
    enroll/remove result — each step is independently logged, never raised.
    """
    if outcome.get("status") not in _REFRESH_TRIGGER_STATUSES:
        return
    # (a) Durable retry FIRST — independent of the immediate refresh so the
    # reliable ~60s follow-up is queued even if (b) blows up.
    try:
        _enqueue_refresh_retry(mla_id)
    except Exception as e:
        logger.error(
            "Promo refresh-retry enqueue failed for mla=%s (enroll/remove outcome is unaffected): %s",
            mla_id,
            e,
            exc_info=True,
        )
    # (b) Immediate best-effort refresh — independent of (a).
    try:
        _resolve(ml_webhook_client.refresh_item_promotions(mla_id))
    except Exception as e:
        logger.error(
            "Promo immediate point-refresh failed for mla=%s (enroll/remove outcome is unaffected): %s",
            mla_id,
            e,
            exc_info=True,
        )


def _maybe_recompute_after_write(mla_id: str, outcome: Dict[str, Any]) -> None:
    """Best-effort post-write hook: recomputes promo-driven price columns
    for the item this `mla_id` belongs to, AFTER the enroll/remove
    reconciliation completed.

    Only fires for outcomes where the promo actually changed state at ML
    (`submitted`/`reconciled_applied`) — a rejected/disabled/ambiguous
    outcome changed nothing, so there is nothing to recompute.

    Defensive by design: the enroll/remove already happened at ML by the
    time this runs, so a recompute failure (mlwebhook down, unmapped
    MLA, DB error) must NEVER corrupt or reverse the enroll/remove
    result — it is only logged here, never raised.
    """
    if outcome.get("status") not in _RECOMPUTE_TRIGGER_STATUSES:
        return
    try:
        with get_background_db() as db:
            publicacion = db.query(PublicacionML).filter(PublicacionML.mla == mla_id).first()
            if publicacion is None:
                logger.warning("Promo price recompute skipped: no PublicacionML found for mla=%s", mla_id)
                return
            recompute_item(db, publicacion.item_id)
    except Exception as e:
        logger.error(
            "Promo price recompute failed for mla=%s (enroll/remove outcome is unaffected): %s",
            mla_id,
            e,
            exc_info=True,
        )


def enroll_one_item(
    mla_id: str,
    promotion_id: str,
    promotion_type: str,
    deal_price: Optional[float] = None,
    top_deal_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Enrolls a single item in a promotion, then triggers the point-refresh
    hook (`_maybe_refresh_after_write`) BEFORE the promo price recompute
    hook (`_maybe_recompute_after_write`) — see each function's docstring
    for its failure-isolation contract. See `_enroll_one_item` for the
    enroll orchestration itself."""
    outcome = _enroll_one_item(
        mla_id,
        promotion_id,
        promotion_type,
        deal_price=deal_price,
        top_deal_price=top_deal_price,
    )
    _maybe_refresh_after_write(mla_id, outcome)
    _maybe_recompute_after_write(mla_id, outcome)
    return outcome


def _enroll_one_item(
    mla_id: str,
    promotion_id: str,
    promotion_type: str,
    deal_price: Optional[float] = None,
    top_deal_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Enrolls a single item in a promotion (SELLER_CAMPAIGN, DEAL, SMART, or PRE_NEGOTIATED).

    Args:
        mla_id: The item ID (e.g. MLA2361127120).
        promotion_id: Target promotion ID.
        promotion_type: SELLER_CAMPAIGN, DEAL, SMART, or PRE_NEGOTIATED.
        deal_price: Discounted price to submit (SELLER_CAMPAIGN/DEAL only).
            If None, defaults to the item's fresh
            `suggested_discounted_price`. Ignored for SMART, whose price is
            always the live entry's own `price` (no [min,max] range exists
            to validate against for SMART).
        top_deal_price: Optional cap price.

    SMART specifics: `offer_id` is taken from the live entry's `ref_id`
    (candidate form "CANDIDATE-MLA...-N"), never cached. On success the 201
    body's authoritative `offer_id` (form "OFFER-MLA...-N") is echoed back
    in the outcome under `offer_id`, since a later remove needs the current
    id, not the candidate one.

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

    if promotion_type in SMART_LIKE_PROMOTION_TYPES:
        # SMART/PRE_NEGOTIATED have no [min,max_discounted_price] to validate against — the
        # entry's own `price` IS the deal_price, and enroll requires the
        # entry's `ref_id` (candidate state, form "CANDIDATE-MLA...-N") as
        # `offer_id`. Both are re-read fresh every time (never cached): the
        # SMART price/split is recalculated by ML over time.
        offer_id = promo.get("ref_id")
        entry_price = promo.get("price")

        if offer_id is None or entry_price is None:
            logger.warning(
                "ML promo enroll rejected_price_unresolved mla=%s promotion_id=%s promotion_type=%s ref_id=%s price=%s",
                mla_id,
                promotion_id,
                promotion_type,
                offer_id,
                entry_price,
            )
            return {
                "submitted": False,
                "status": "rejected_price_unresolved",
                "detail": f"{promotion_type} entry is missing ref_id (offer_id) or price in the live payload",
            }

        write_result = _resolve(
            ml_webhook_client.enroll_item(
                mla_id,
                promotion_id,
                promotion_type,
                entry_price,
                top_deal_price=top_deal_price,
                offer_id=offer_id,
            )
        )
        outcome = _classify_write_outcome(
            write_result,
            mla_id,
            promotion_id,
            price=entry_price,
            promotion_type=promotion_type,
            operation="enroll",
            offer_id=offer_id,
        )
        if outcome["status"] == "submitted":
            # The 201 body carries the authoritative new offer_id (form
            # "OFFER-MLA...-N") — surface it so a later remove/reconcile
            # step does not have to guess it from a stale live re-read.
            body = write_result.get("body") if isinstance(write_result.get("body"), dict) else None
            authoritative_offer_id = (body or {}).get("offer_id")
            outcome["offer_id"] = authoritative_offer_id
            logger.info(
                "ML promo enroll submitted mla=%s promotion_id=%s promotion_type=%s "
                "candidate_offer_id=%s authoritative_offer_id=%s",
                mla_id,
                promotion_id,
                promotion_type,
                offer_id,
                authoritative_offer_id,
            )
        return outcome

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
    """Removes a single item from a promotion, then triggers the
    point-refresh hook (`_maybe_refresh_after_write`) BEFORE the promo
    price recompute hook (`_maybe_recompute_after_write`). See
    `_remove_one_item` for the remove orchestration itself."""
    outcome = _remove_one_item(mla_id, promotion_type, promotion_id)
    _maybe_refresh_after_write(mla_id, outcome)
    _maybe_recompute_after_write(mla_id, outcome)
    return outcome


def _remove_one_item(mla_id: str, promotion_type: str, promotion_id: str) -> Dict[str, Any]:
    """Removes a single item from a promotion (SELLER_CAMPAIGN, DEAL, SMART, or PRE_NEGOTIATED).

    Args:
        mla_id: The item ID.
        promotion_type: SELLER_CAMPAIGN, DEAL, SMART, or PRE_NEGOTIATED.
        promotion_id: Target promotion ID.

    SMART specifics: the live item is re-read immediately before the
    DELETE to obtain the CURRENT `OFFER-...` ref_id — SMART's ref_id
    mutates on enroll (CANDIDATE-... -> OFFER-...) and a stale/candidate id
    would 400. Never reuse a previously-captured offer_id.

    Returns:
        See module docstring for the outcome contract.
    """
    if not settings.PROMOS_WRITE_ENABLED:
        return _disabled_outcome()

    if promotion_type not in WRITABLE_PROMOTION_TYPES:
        return _rejected_unsupported_type(promotion_type)

    if promotion_type in SMART_LIKE_PROMOTION_TYPES:
        # SMART/PRE_NEGOTIATED's ref_id MUTATES on enroll (CANDIDATE-... ->
        # OFFER-...) and delete requires the CURRENT offer_id — a
        # stale/candidate id 400s. Always re-read live immediately before
        # the delete; never reuse a previously-captured offer_id.
        live = _resolve(ml_webhook_client.get_item_promotions(mla_id))
        if live is None:
            logger.warning(
                "ML promo remove rejected_read_unavailable mla=%s promotion_id=%s promotion_type=%s",
                mla_id,
                promotion_id,
                promotion_type,
            )
            return {
                "submitted": False,
                "status": "rejected_read_unavailable",
                "detail": "Live get_item_promotions() read failed; refusing to delete without the current offer_id",
            }

        promo = _find_live_promotion(live, promotion_id)
        offer_id = promo.get("ref_id") if promo is not None else None
        if offer_id is None:
            logger.warning(
                "ML promo remove rejected_promotion_not_found mla=%s promotion_id=%s promotion_type=%s",
                mla_id,
                promotion_id,
                promotion_type,
            )
            return {
                "submitted": False,
                "status": "rejected_promotion_not_found",
                "detail": f"promotion_id={promotion_id!r} not present (or missing ref_id) in the live item promotions payload",
            }

        write_result = _resolve(ml_webhook_client.remove_item(mla_id, promotion_type, promotion_id, offer_id=offer_id))
        return _classify_write_outcome(
            write_result,
            mla_id,
            promotion_id,
            price=None,
            promotion_type=promotion_type,
            operation="remove",
            offer_id=offer_id,
        )

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
    offer_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Classifies a single-shot POST/DELETE result into the final outcome.

    2xx -> submitted (source of truth is `ml_item_promotions`, NOT this
    response — eventual consistency, no immediate "enrolled" assertion).
    4xx (ambiguous=False) -> definitive rejection by the proxy, no
    reconciliation attempted.
    timeout/5xx (ambiguous=True) -> reconcile via `ml_item_promotions`,
    direction-aware (`operation`) — see `reconcile_write_outcome`. For SMART
    (slower ~10-18s consistency), a negative reconciliation verdict is
    reported as "ambiguous" instead of "reconciled_not_applied" to avoid a
    false negative.
    """
    slow_consistency = promotion_type in SMART_LIKE_PROMOTION_TYPES

    if write_result["ok"]:
        logger.info(
            "ML promo write submitted operation=%s mla=%s promotion_id=%s promotion_type=%s price=%s "
            "status_code=%s offer_id=%s",
            operation,
            mla_id,
            promotion_id,
            promotion_type,
            price,
            write_result["status_code"],
            offer_id,
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

    reconciliation = reconcile_write_outcome(
        mla_id, promotion_id, operation=operation, slow_consistency=slow_consistency
    )
    if reconciliation["status"] == "ambiguous":
        logger.warning(
            "ML promo write ambiguous (reconciliation read failed or slow-consistency negative verdict) "
            "operation=%s mla=%s promotion_id=%s promotion_type=%s offer_id=%s",
            operation,
            mla_id,
            promotion_id,
            promotion_type,
            offer_id,
        )
    elif reconciliation["status"] == "reconciled_not_applied":
        logger.warning(
            "ML promo write reconciled_not_applied operation=%s mla=%s promotion_id=%s promotion_type=%s offer_id=%s",
            operation,
            mla_id,
            promotion_id,
            promotion_type,
            offer_id,
        )
    else:
        logger.info(
            "ML promo write reconciled_applied operation=%s mla=%s promotion_id=%s promotion_type=%s offer_id=%s",
            operation,
            mla_id,
            promotion_id,
            promotion_type,
            offer_id,
        )
    result = {
        "submitted": False,
        "status": reconciliation["status"],
        "status_code": write_result["status_code"],
        "reconciled_row": reconciliation["row"],
    }
    if "detail" in reconciliation:
        result["detail"] = reconciliation["detail"]
    return result
