"""Write-orchestration service for ML PxQ (wholesale price-by-quantity)
tiers (PR 3b).

Mirrors `ml_promotions_write_service.py`'s order of operations, adapted to
the array-replace semantics of `/items/{ITEM_ID}/prices/standard/quantity`
(`pxq_diff.diff_pxq_tiers`, PR 3a):

  1. Kill-switch (`settings.PXQ_WRITE_ENABLED`) checked FIRST, before any
     permission check, eligibility check, or ML call.
  2. Permission `pxq.escribir` -> HTTPException(403) if missing.
  3. Eligibility: seller must carry the `business` tag, item must carry
     `standard_price_by_quantity` -> `rejected_not_eligible` otherwise.
  4. Fresh LIVE read (never cached) via `ml_webhook_client.get_pxq_prices`
     -> None means `rejected_read_unavailable`.
  5. `diff_pxq_tiers(...)` against the local mirror (the three-way merge
     against the snapshot, PR 3a) -- a refusal means NO array is built and
     NO POST is attempted (`status="divergence"`).
  6. Single POST (no retry -- an ambiguous write could double-apply).

THE SNAPSHOT RULE (the reason this table has `cantidad_sincronizada` /
`precio_sincronizado` at all): the snapshot is written ONLY when the POST
is CONFIRMED to have applied -- 2xx AND a successful post-write re-read
whose values match what was sent. Any other outcome (kill-switch, gate
rejection, divergence, POST timeout/5xx, or a failed confirmation re-read)
leaves the snapshot untouched and marks the affected mirror rows
`desconocido`, forcing the NEXT sync attempt through the divergence gate
instead of silently believing an unconfirmed write landed. Writing the
snapshot early, or on any non-confirmed path, is exactly the bug this
mirror exists to prevent -- the three-way merge degrades back to a blind
overwrite the moment the snapshot is wrong.

This module must NEVER import `ProductoPricing` (design D3, AST-enforced by
`tests/unit/test_pxq_base_price_boundary.py`) and NEVER dirty a
`ProductoPricing` row -- enforced here additionally at RUNTIME by
`_assert_no_base_price_dirty` right before every commit.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ml_pxq_tier import ESTADO_DESCONOCIDO, MlPxqTier
from app.services.permisos_service import PermisosService
from app.services.pxq_confirm import is_priceable, remap_and_confirm
from app.services.pxq_diff import DesiredTier, LiveTier, diff_pxq_tiers
from app.services.pxq_permissions_backfill import PXQ_ESCRIBIR_CODE
from app.services.ml_webhook_client import ml_webhook_client
from app.utils.async_bridge import resolve_maybe_async as _resolve

logger = logging.getLogger(__name__)

ELIGIBLE_SELLER_TAG = "business"
ELIGIBLE_ITEM_TAG = "standard_price_by_quantity"


def _disabled_outcome() -> Dict[str, Any]:
    return {"synced": False, "status": "disabled", "detail": "Writes are disabled (PXQ_WRITE_ENABLED=false)"}


def _assert_no_base_price_dirty(db: Session) -> None:
    """Runtime guard (design D3): no `ProductoPricing` instance may be
    staged for flush/insert when this service commits. Deliberately
    compares on the CLASS NAME (a string), never on the class itself --
    importing/naming `ProductoPricing` here would itself violate the
    AST-scanned boundary this assert exists to enforce."""
    for obj in list(db.dirty) + list(db.new):
        if type(obj).__name__ == "ProductoPricing":
            raise AssertionError("ml_pxq_write_service must never touch ProductoPricing (design D3)")


def _read_unavailable_outcome(detail: str = "Live read could not be parsed") -> Dict[str, Any]:
    """No trustworthy view of live state means no write. Used both when the
    read fails outright and when it comes back in a shape we cannot parse —
    the two are the same situation from here."""
    return {
        "synced": False,
        "status": "rejected_read_unavailable",
        "detail": f"{detail}; refusing to write without a fresh state check",
    }


def _live_tiers_from_raw(raw: List[Dict[str, Any]]) -> Optional[List[LiveTier]]:
    """Parses the live read, or returns None when it cannot be trusted.

    A malformed payload is the same situation as no read at all, and this
    service already has an outcome for that: `rejected_read_unavailable`.
    Refusing to write is right; raising and answering 500 is not. The read
    endpoint was already fixed to degrade — this path had been left raising.
    """
    try:
        return [LiveTier(id=str(entry["id"]), quantity=int(entry["quantity"]), amount=entry["amount"]) for entry in raw]
    except (KeyError, TypeError, ValueError, ArithmeticError):
        # ArithmeticError covers decimal.InvalidOperation: LiveTier coerces
        # through Decimal(str(value)), and that exception is NOT a ValueError,
        # so a junk amount escaped and surfaced as a 500.
        return None


def _desired_tiers_from_mirror(rows: List[MlPxqTier]) -> List[DesiredTier]:
    """Turns priceable mirror rows into desired-state.

    `diff_pxq_tiers` decides keep/create/modify/refuse from the snapshot, so
    nothing branches here beyond the priceability filter.

    That filter is redundant — the caller applies the same `is_priceable` —
    and it is kept on purpose: it holds the rule that a tier without a
    resolved whole-shipment cost never reaches MercadoLibre. Both sites call
    the SAME function; what caused the earlier drift was two hand-written
    copies of the condition, not the redundancy.
    """
    return [
        DesiredTier(
            quantity=row.cantidad_minima,
            amount=row.precio_unitario,
            ml_price_id=row.ml_price_id,
            synced_quantity=row.cantidad_sincronizada,
            synced_amount=row.precio_sincronizado,
        )
        for row in rows
        if is_priceable(row)
    ]


def _mark_desconocido(rows: List[MlPxqTier]) -> None:
    """Outcome is genuinely UNKNOWN (POST ambiguous, or POST confirmed but
    the confirmation re-read failed): mirror rows go to `desconocido` and
    `ml_price_id`/the snapshot are left EXACTLY as they were. This is what
    forces the next sync attempt through the divergence gate instead of
    assuming the write did or did not land."""
    for row in rows:
        row.estado = ESTADO_DESCONOCIDO


# Every status `sync_pxq_tiers` can return. Declared here so the router's HTTP
# mapping can be checked against the real set: the test used to carry its own
# hardcoded copy, which meant the test guarding against an unmapped status
# could not notice a new one.
SYNC_STATUSES = frozenset(
    {
        "disabled",
        "rejected_not_eligible",
        "rejected_eligibility_unknown",
        "rejected_read_unavailable",
        "divergence",
        "rejected_by_proxy",
        "submitted_unconfirmed",
        "ambiguous_needs_reconcile",
        "sincronizado",
    }
)


def _unconfirmed_outcome() -> Dict[str, Any]:
    """The POST left but the confirmation re-read failed. The mirror is
    `desconocido`, the snapshot did NOT advance, and the live state is
    genuinely unknown.

    `synced` is False on purpose: reporting success for a write nobody could
    confirm contradicts the rule this service exists to hold, and the UI would
    paint an unknown outcome as a finished one."""
    return {
        "synced": False,
        "status": "submitted_unconfirmed",
        "detail": "POST succeeded but the confirmation re-read failed; mirror marked desconocido",
    }


def sync_pxq_tiers(db: Session, usuario: Any, item_id: str, *, allow_clear: bool = False) -> Dict[str, Any]:
    """Orchestrates one PxQ sync for `item_id`. See module docstring for
    the full gate order and the snapshot rule.

    Raises:
        HTTPException(403): missing `pxq.escribir` permission.

    Returns:
        `{"synced": bool, "status": str, ...}`. `status` is one of
        `disabled`, `rejected_not_eligible`, `rejected_read_unavailable`,
        `rejected_eligibility_unknown`, `divergence`, `sincronizado`,
        `submitted_unconfirmed`,
        `ambiguous_needs_reconcile`, `rejected_by_proxy`.
    """
    if not settings.PXQ_WRITE_ENABLED:
        logger.debug(
            "PxQ sync skipped: PXQ_WRITE_ENABLED is false item_id=%s usuario_id=%s",
            item_id,
            getattr(usuario, "id", None),
        )
        return _disabled_outcome()

    permisos = PermisosService(db)
    if not permisos.tiene_permiso(usuario, PXQ_ESCRIBIR_CODE):
        logger.warning(
            "PxQ sync denied: missing %s item_id=%s usuario_id=%s",
            PXQ_ESCRIBIR_CODE,
            item_id,
            getattr(usuario, "id", None),
        )
        raise HTTPException(status_code=403, detail=f"No tienes permiso: {PXQ_ESCRIBIR_CODE}")

    eligibility = _resolve(ml_webhook_client.get_pxq_eligibility(item_id))
    if eligibility is None:
        # Unreadable is not the same as ineligible. Both refuse the write, but
        # "your seller is not enrolled in PxQ" is a permanent fact about the
        # account, and saying it when the proxy simply failed sends someone to
        # support for a problem that does not exist.
        logger.warning(
            "PxQ sync refused: eligibility unreadable item_id=%s usuario_id=%s",
            item_id,
            getattr(usuario, "id", None),
        )
        return {
            "synced": False,
            "status": "rejected_eligibility_unknown",
            "detail": "Could not read PxQ eligibility; refusing to write without confirming it",
        }
    if ELIGIBLE_SELLER_TAG not in eligibility.get("seller_tags", []) or ELIGIBLE_ITEM_TAG not in eligibility.get(
        "item_tags", []
    ):
        logger.info(
            "PxQ sync refused: seller/item not eligible item_id=%s usuario_id=%s",
            item_id,
            getattr(usuario, "id", None),
        )
        return {"synced": False, "status": "rejected_not_eligible", "detail": "seller/item not eligible for PxQ"}

    live_raw = _resolve(ml_webhook_client.get_pxq_prices(item_id))
    if live_raw is None:
        logger.warning(
            "PxQ sync refused: live read failed item_id=%s usuario_id=%s",
            item_id,
            getattr(usuario, "id", None),
        )
        return _read_unavailable_outcome("Live get_pxq_prices() read failed")

    # Ordered explicitly, because this list IS the array POSTed to ML under
    # array-replace semantics -- the whole price ladder the publication will
    # hold afterwards. Left to the query planner, the same mirror could emit
    # two differently-ordered payloads on two runs, which makes the one call in
    # this feature that cannot be undone irreproducible between them. It is
    # also the likely reason ML hands the tiers back unordered: we send them
    # that way, and `ml-webhook` preserves our order on purpose in both
    # directions.
    #
    # It also gives `priceable_rows[0].publicacion_ml_id` below something
    # defined to stand on. That read is positional and harmless in itself --
    # every row for one `item_id` belongs to the same publication -- but
    # "index 0" now means the lowest quantity instead of whatever surfaced
    # first.
    mirror_rows = db.query(MlPxqTier).filter(MlPxqTier.item_id == item_id).order_by(MlPxqTier.cantidad_minima).all()
    # Filtered ONCE. Two separate comprehensions applying the same predicate to
    # the same list were identical by construction, but only by construction —
    # touching one and not the other would have let a cost-less tier reach ML.
    priceable_rows = [row for row in mirror_rows if is_priceable(row)]
    desired = _desired_tiers_from_mirror(priceable_rows)
    live_tiers = _live_tiers_from_raw(live_raw)
    if live_tiers is None:
        logger.warning(
            "PxQ sync refused: live payload unparseable item_id=%s usuario_id=%s",
            item_id,
            getattr(usuario, "id", None),
        )
        return _read_unavailable_outcome()

    # `publicacion_ml_id` is only known once mirror rows are loaded; a
    # publication with an empty mirror simply has none to derive it from.
    publicacion_ml_id = priceable_rows[0].publicacion_ml_id if priceable_rows else None

    diff_result = diff_pxq_tiers(live_tiers, desired, allow_clear=allow_clear)
    if not diff_result.ok:
        logger.warning(
            "PxQ sync refused: divergence item_id=%s reason=%s divergence_count=%s ml_price_ids=%s "
            "publicacion_ml_id=%s usuario_id=%s",
            item_id,
            diff_result.refusal.reason,
            len(diff_result.refusal.divergences),
            [d.ml_price_id for d in diff_result.refusal.divergences],
            publicacion_ml_id,
            getattr(usuario, "id", None),
        )
        return {
            "synced": False,
            "status": "divergence",
            "reason": diff_result.refusal.reason,
            "divergences": [
                {
                    "ml_price_id": d.ml_price_id,
                    "reason": d.reason,
                    "live": d.live,
                    "desired": d.desired,
                }
                for d in diff_result.refusal.divergences
            ],
        }

    # The breakdown comes from the diff, never from inspecting the array: a
    # create and a modify are indistinguishable there (both `{quantity,
    # amount}`, no id), so the old `"id" in entry` heuristic reported the price
    # replacement of an existing tier as a brand-new tier -- a wrong fact in
    # the one log line meant to make the next incident reconstructable.
    counts = diff_result.counts
    logger.info(
        "PxQ sync posting array item_id=%s entries=%s keeps=%s creates=%s modifies=%s deletes=%s "
        "publicacion_ml_id=%s usuario_id=%s",
        item_id,
        len(diff_result.array),
        counts.keeps,
        counts.creates,
        counts.modifies,
        counts.deletes,
        publicacion_ml_id,
        getattr(usuario, "id", None),
    )
    write_result = _resolve(ml_webhook_client.post_pxq_prices(item_id, diff_result.array))

    if write_result["ok"]:
        confirm_raw = _resolve(ml_webhook_client.get_pxq_prices(item_id))
        if confirm_raw is None:
            _mark_desconocido(priceable_rows)
            _assert_no_base_price_dirty(db)
            db.commit()
            # Distinct from the incomplete-confirmation branch below: here we
            # have NO view of live at all, so the fault points at the proxy/ML.
            # Same distinction as `live_tiers: null` vs `[]` -- one message for
            # both root causes sends the next incident down the wrong path.
            logger.error(
                "PxQ sync unconfirmed: confirmation re-read failed item_id=%s usuario_id=%s",
                item_id,
                getattr(usuario, "id", None),
            )
            return _unconfirmed_outcome()
        if not diff_result.array:
            # allow_clear: with nothing sent, `remap_and_confirm` would return
            # True vacuously and report a deletion nobody verified. The only
            # confirmation that means anything here is that the live array
            # actually came back empty.
            all_confirmed = not confirm_raw
            if not all_confirmed:
                # Every other unconfirmed path marks the rows so the next sync
                # is forced through the divergence gate. Leaving them looking
                # trustworthy after a clear we could not verify is the exact
                # state this service exists to prevent.
                _mark_desconocido(priceable_rows)
        else:
            all_confirmed = remap_and_confirm(priceable_rows, confirm_raw, untracked_ids=diff_result.untracked_ids)
        _assert_no_base_price_dirty(db)
        db.commit()
        if not all_confirmed:
            # At least one row could not be matched in the re-read. Its state is
            # unknown, so the sync as a whole is not finished — reporting
            # success here is the same defect as reporting it when the re-read
            # failed entirely, one branch over.
            #
            # But NOT the same fact: the re-read arrived, so live IS readable
            # and it disagrees with what we sent. That points at the write or
            # at the confirmation matching, not at the proxy -- which is why
            # this message differs from the failed-re-read one above.
            logger.error(
                "PxQ sync unconfirmed: re-read succeeded but confirmation incomplete item_id=%s "
                "entries=%s usuario_id=%s",
                item_id,
                len(diff_result.array),
                getattr(usuario, "id", None),
            )
            return _unconfirmed_outcome()
        logger.info(
            "PxQ sync completed item_id=%s entries=%s usuario_id=%s",
            item_id,
            len(diff_result.array),
            getattr(usuario, "id", None),
        )
        return {"synced": True, "status": "sincronizado", "array": diff_result.array}

    if write_result["ambiguous"]:
        _mark_desconocido(priceable_rows)
        _assert_no_base_price_dirty(db)
        db.commit()
        logger.error(
            "PxQ sync POST unresolved item_id=%s ambiguous=%s status_code=%s usuario_id=%s",
            item_id,
            write_result["ambiguous"],
            write_result.get("status_code"),
            getattr(usuario, "id", None),
        )
        return {
            "synced": False,
            "status": "ambiguous_needs_reconcile",
            "detail": "POST timed out or 5xx; outcome unknown, mirror marked desconocido",
        }

    logger.error(
        "PxQ sync POST unresolved item_id=%s ambiguous=%s status_code=%s usuario_id=%s",
        item_id,
        write_result.get("ambiguous"),
        write_result.get("status_code"),
        getattr(usuario, "id", None),
    )
    return {
        "synced": False,
        "status": "rejected_by_proxy",
        "status_code": write_result.get("status_code"),
        "detail": write_result.get("body"),
    }
