"""Import-only orchestration for MercadoLibre PxQ tiers -- `adopt-live`
(change `pxq-adopt-live`, design D10-D12/D15).

Reads MercadoLibre's LIVE wholesale tiers and writes them into an EMPTY local
mirror. It exists because four publications lost their mirrored tiers while ML
still held them, and without this path the only recovery was retyping money
values by hand.

Deliberately a separate module from `ml_pxq_write_service`: that one is a
single tightly-scoped outbound gate chain, this one is a structurally
different, inbound, import-only orchestration. The `ml_pxq*` filename prefix
keeps it inside the AST base-price boundary scan
(`tests/unit/test_pxq_base_price_boundary.py`) at no extra cost.

Gate order is permission -> live read -> ceiling -> parse -> LOCK ->
conflict check -> insert -> commit. Each step states its own reasoning at the
branch that decides it; the two rules that span the whole module are:

  * NOT gated by `settings.PXQ_WRITE_ENABLED`. That switch scopes the
    irreversible outbound array-replace POST, which this path never performs,
    and all three local-write CRUD endpoints gate on `pxq.escribir` alone.
    `_assert_no_base_price_dirty` is imported from the write service below and
    drags `settings` in transitively -- that is NOT this module adopting the
    kill-switch.
  * `None` from the live read (it FAILED) and `[]` (ML genuinely holds no
    tiers) are two DIFFERENT facts and never share a code path. Collapsing
    them is the exact bug class this whole change repairs.

This module NEVER calls a MercadoLibre write endpoint, and it must NEVER
import `ProductoPricing` (design D3).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.ml_pxq_tier import MlPxqTier
from app.models.publicacion_ml import PublicacionML
from app.services.ml_pxq_write_service import _assert_no_base_price_dirty
from app.services.ml_webhook_client import ml_webhook_client
from app.services.permisos_service import PermisosService
from app.services.pxq_confirm import live_entry_to_tier_fields
from app.services.pxq_diff import MAX_TIERS
from app.services.pxq_permissions_backfill import PXQ_ESCRIBIR_CODE
from app.services.pxq_tier_service import create_pxq_tier
from app.utils.async_bridge import resolve_maybe_async as _resolve

logger = logging.getLogger(__name__)


def _read_unavailable(reason: str) -> HTTPException:
    """The single shape for "we have no trustworthy view of live state".

    Raised both when the read fails outright and when the payload cannot be
    parsed: from here the two are the same situation, and importing under
    either would invent the very data this path exists to recover.
    """
    return HTTPException(status_code=503, detail={"status": "adopt_read_unavailable", "reason": reason})


def adopt_live_pxq_tiers(
    db: Session,
    usuario: Any,
    item_id: str,
    *,
    publicacion_ml_id: int,
) -> List[MlPxqTier]:
    """Imports MercadoLibre's live PxQ tiers for `item_id` into an EMPTY local
    mirror. Import-only: no ML write endpoint is called on any path.

    Every imported row carries `cantidad_sincronizada`/`precio_sincronizado`
    from the SAME live read that produced its `cantidad_minima`/
    `precio_unitario`, so the snapshot is correct by construction. A row
    persisted with `ml_price_id` set and a NULL snapshot is refused forever by
    `pxq_diff` with "no snapshot to compare against" -- permanently
    un-syncable, which is precisely the damage being repaired.

    `costo_envio_total` is left NULL and `estado` stays `incompleto`:
    MercadoLibre does not report the whole-shipment cost, so the row genuinely
    is incomplete until the operator supplies it. Write-eligibility is decided
    by `costo_envio_total`, never by `estado` (`pxq_confirm.is_priceable`).

    Returns:
        The rows it created, empty when MercadoLibre holds no tiers.

    Raises:
        HTTPException(403): missing `pxq.escribir`.
        HTTPException(503): `adopt_read_unavailable` -- the live read failed or
            its payload could not be parsed. Nothing is written.
        HTTPException(409): `adopt_too_many_live_tiers` (more than `MAX_TIERS`
            live entries) or `adopt_conflict` (the publication already has at
            least one local row). Nothing is written.
        HTTPException(422): propagated from `create_pxq_tier` when a live
            entry cannot be a valid tier (e.g. `quantity <= 1`, or two entries
            sharing a quantity). Nothing is COMMITTED, so nothing is
            persisted -- the request's session is closed without a commit.
    """
    usuario_id = getattr(usuario, "id", None)
    logger.info(
        "PxQ adopt-live start item_id=%s publicacion_ml_id=%s usuario_id=%s",
        item_id,
        publicacion_ml_id,
        usuario_id,
    )

    permisos = PermisosService(db)
    if not permisos.tiene_permiso(usuario, PXQ_ESCRIBIR_CODE):
        logger.warning(
            "PxQ adopt-live denied: missing %s item_id=%s usuario_id=%s",
            PXQ_ESCRIBIR_CODE,
            item_id,
            usuario_id,
        )
        raise HTTPException(status_code=403, detail=f"No tienes permiso: {PXQ_ESCRIBIR_CODE}")

    # NO lock is held across this call -- see D11 in the module docstring.
    live_raw = _resolve(ml_webhook_client.get_pxq_prices(item_id))
    if live_raw is None:
        logger.warning(
            "PxQ adopt-live refused: live read unavailable item_id=%s publicacion_ml_id=%s usuario_id=%s",
            item_id,
            publicacion_ml_id,
            usuario_id,
        )
        raise _read_unavailable("Live get_pxq_prices() read failed; nothing was imported")

    logger.info(
        "PxQ adopt-live live read ok item_id=%s live_count=%s usuario_id=%s",
        item_id,
        len(live_raw),
        usuario_id,
    )

    if not live_raw:
        # A genuinely empty live set is SUCCESS with nothing imported, not an
        # error -- and it short-circuits ahead of the conflict check, so an
        # operator is never told to resolve a local conflict when there was
        # nothing on ML to import in the first place.
        logger.info(
            "PxQ adopt-live no-op: MercadoLibre holds no tiers item_id=%s usuario_id=%s",
            item_id,
            usuario_id,
        )
        return []

    if len(live_raw) > MAX_TIERS:
        logger.warning(
            "PxQ adopt-live refused: live holds %s tiers, max is %s item_id=%s usuario_id=%s",
            len(live_raw),
            MAX_TIERS,
            item_id,
            usuario_id,
        )
        raise HTTPException(
            status_code=409,
            detail={"status": "adopt_too_many_live_tiers", "live_count": len(live_raw), "max": MAX_TIERS},
        )

    try:
        fields = [live_entry_to_tier_fields(entry) for entry in live_raw]
    except (KeyError, TypeError, ValueError, ArithmeticError):
        # Exactly the tuple `live_entry_to_tier_fields` documents. It is pure
        # and has no outcome vocabulary, so the refusal is decided here.
        # `ArithmeticError` covers `decimal.InvalidOperation`, which is NOT a
        # `ValueError` -- the bug `_live_tiers_from_raw` was already fixed for.
        logger.warning(
            "PxQ adopt-live refused: live payload unparseable item_id=%s publicacion_ml_id=%s usuario_id=%s",
            item_id,
            publicacion_ml_id,
            usuario_id,
        )
        raise _read_unavailable("Live payload could not be parsed; nothing was imported")

    # --- LOCK OPENS ------------------------------------------------------
    # Once, on the publication row -- not per tier. Held from here through the
    # conflict check and every insert to the single commit below, which is
    # what makes "check empty, then import N" atomic. A concurrent second
    # import blocks here, then sees the now-non-empty mirror and gets a clean
    # 409 instead of an `IntegrityError` surfacing as a 500. `create_pxq_tier`
    # re-locks the same row inside the loop: a no-op in this transaction, kept
    # because removing it would weaken the CRUD path that owns it.
    #
    # A publication that does not exist takes no lock (nothing to lock) and
    # falls through to `create_pxq_tier`'s clean 422 for exactly that case.
    db.query(PublicacionML.id).filter(PublicacionML.id == publicacion_ml_id).with_for_update().first()

    existing = (
        db.query(MlPxqTier.id, MlPxqTier.cantidad_minima)
        .filter(MlPxqTier.publicacion_ml_id == publicacion_ml_id)
        .order_by(MlPxqTier.cantidad_minima)
        .all()
    )
    if existing:
        conflicts: List[Dict[str, int]] = [
            {"tier_id": row.id, "cantidad_minima": row.cantidad_minima} for row in existing
        ]
        logger.warning(
            "PxQ adopt-live refused: mirror not empty item_id=%s publicacion_ml_id=%s existing_tier_ids=%s "
            "existing_cantidades=%s usuario_id=%s",
            item_id,
            publicacion_ml_id,
            [c["tier_id"] for c in conflicts],
            [c["cantidad_minima"] for c in conflicts],
            usuario_id,
        )
        raise HTTPException(
            status_code=409,
            detail={
                "status": "adopt_conflict",
                "reason": (
                    "The local mirror already has tiers for this publication; nothing was imported. "
                    "Delete the conflicting tiers and retry."
                ),
                "conflicts": conflicts,
            },
        )

    rows = [
        create_pxq_tier(
            db,
            publicacion_ml_id=publicacion_ml_id,
            item_id=item_id,
            cantidad_minima=f.cantidad_minima,
            precio_unitario=f.precio_unitario,
            usuario_id=usuario_id,
            ml_price_id=f.ml_price_id,
            cantidad_sincronizada=f.cantidad_sincronizada,
            precio_sincronizado=f.precio_sincronizado,
        )
        for f in fields
    ]

    # D3 runtime guard, immediately before the ONE commit -- the sibling write
    # service calls it before every one of its four commits, and this path
    # must not be the exception. Imported rather than hand-copied: a second
    # copy of a safety condition is the drift class this feature keeps getting
    # bitten by.
    _assert_no_base_price_dirty(db)
    db.commit()
    # --- LOCK CLOSES (released by the commit) ----------------------------

    for row in rows:
        db.refresh(row)

    logger.info(
        "PxQ adopt-live imported %s tiers item_id=%s publicacion_ml_id=%s cantidades=%s usuario_id=%s",
        len(rows),
        item_id,
        publicacion_ml_id,
        [row.cantidad_minima for row in rows],
        usuario_id,
    )
    return rows
