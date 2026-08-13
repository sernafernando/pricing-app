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
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class SkippedLiveEntry:
    """One live MercadoLibre price this mirror deliberately does not import.

    Reported rather than dropped because the panel puts the LIVE column beside
    the mirror column: the skipped price is visible on the left and will never
    appear on the right, and nothing on that screen explains why the two
    disagree by a row. A bare count would leave the operator reading "2 tramos
    importados" as "the mirror now matches ML".

    `ml_price_id` is what ties this back to the exact entry on MercadoLibre --
    the quantity alone does not, and it is the id the logs and the live read
    both key on.
    """

    ml_price_id: str
    cantidad_minima: int


@dataclass(frozen=True)
class AdoptOutcome:
    """What one `adopt-live` actually did: the rows it created, and the live
    entries it knowingly left behind.

    A bare `List[MlPxqTier]` cannot express the second half, and the caller
    genuinely needs both -- `imported == []` means two DIFFERENT things
    depending on whether `skipped` is empty ("MercadoLibre holds no tiers")
    or not ("MercadoLibre holds prices this panel cannot represent"), and the
    frontend renders different copy for each.
    """

    imported: List[MlPxqTier] = field(default_factory=list)
    skipped: List[SkippedLiveEntry] = field(default_factory=list)


def _read_unavailable(reason: str) -> HTTPException:
    """The single shape for "we have no trustworthy view of live state".

    Raised when the read fails outright, when the payload cannot be parsed,
    and when it carries more tiers than MercadoLibre itself can hold: from
    here all three are the same situation, and importing under any of them
    would invent the very data this path exists to recover.
    """
    return HTTPException(status_code=503, detail={"status": "adopt_read_unavailable", "reason": reason})


def adopt_live_pxq_tiers(
    db: Session,
    usuario: Any,
    item_id: str,
    *,
    publicacion_ml_id: int,
) -> AdoptOutcome:
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
        An `AdoptOutcome`: the rows it created, plus the live entries it
        skipped because this mirror cannot represent them (see the partition
        below). Both lists are empty when MercadoLibre holds no tiers.

    Raises:
        HTTPException(403): missing `pxq.escribir`.
        HTTPException(503): `adopt_read_unavailable` -- the live read failed,
            its payload could not be parsed, or it returned more than
            `MAX_TIERS` entries, which is MercadoLibre's own platform limit and
            therefore an impossible state rather than an operator-resolvable
            one. Nothing is written.
        HTTPException(409): `adopt_conflict` -- the publication already has at
            least one local row. Nothing is written.
        HTTPException(422): propagated from `create_pxq_tier` when a live
            entry cannot be a valid tier -- e.g. two entries sharing a
            quantity. NOT `quantity < 1`, which is the one condition this
            service skips ahead of the call instead of propagating; see the
            partition below for why that one and only that one. These fire
            INSIDE the import loop, AFTER earlier rows were already
            `db.add`-ed and flushed -- so rows do exist, pending, when this
            raises. Nothing is COMMITTED, so nothing is persisted: the
            request's session is closed without a commit.

            No explicit `db.rollback()` here, deliberately. This service does
            not own the session it was handed -- `get_db` opens it, never
            commits it, and discards it in its `finally` -- so unwinding it
            would be deciding the fate of a transaction that may enclose work
            this service knows nothing about. The guarantee is structural, not
            something a rollback call would strengthen. Guarded by
            `test_a_422_raised_mid_loop_persists_nothing`.
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
        return AdoptOutcome()

    if len(live_raw) > MAX_TIERS:
        # `MAX_TIERS` is MercadoLibre's OWN platform limit (see the constant in
        # `pxq_diff`), not a rule of ours, so this branch is an IMPOSSIBLE
        # state: either ML changed that limit, the proxy returned garbage, or
        # we read the wrong item. All three say the same thing -- the live read
        # is not trustworthy -- which is exactly `_read_unavailable`, NOT a
        # conflict. A 409 would hand the operator an action they cannot take:
        # they cannot go to MercadoLibre and delete tiers it would never have
        # let them create.
        #
        # `create_pxq_tier` keeps a 422 for the SAME ceiling on purpose. There
        # the operator DID send a tier that does not fit and can send another
        # one; here nobody sent anything, the number came off the wire. The
        # asymmetry is "your input does not fit" vs "our view of ML is broken".
        #
        # ERROR, where every other refusal in this module is WARNING: this one
        # is an invariant violation and somebody has to see it.
        logger.error(
            "PxQ adopt-live refused: live read returned %s tiers, above MercadoLibre's platform limit of %s "
            "item_id=%s publicacion_ml_id=%s usuario_id=%s",
            len(live_raw),
            MAX_TIERS,
            item_id,
            publicacion_ml_id,
            usuario_id,
        )
        raise _read_unavailable(
            f"Live read returned {len(live_raw)} tiers, above MercadoLibre's platform limit of {MAX_TIERS}; "
            "the read cannot be trusted and nothing was imported"
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

    # The partition STAYS; what falls on which side moved. The property this
    # implements is general and unchanged: import every entry this mirror can
    # represent, REPORT the ones it cannot, never abort the whole request over
    # a single entry. Only the definition of "irrepresentable" narrowed.
    #
    # It used to be `<= 1`, on the belief that a one-unit price was not a
    # tramo. That was wrong twice over. MercadoLibre ACCEPTS
    # `min_purchase_unit: 1` and holds it in production -- MLA1563835240
    # carries `{"id": "3396", "amount": 80999, "min_purchase_unit": 1}` with
    # both `context_restrictions` -- and, decisively, that entry is what makes
    # the publication appear as "Venta para negocios". It is the switch for the
    # B2B shelf, so dropping it meant the mirror could not describe whether the
    # listing was on that shelf at all. `ck_ml_pxq_tier_cantidad_minima_ge_1`
    # carries the full reasoning.
    #
    # So today's trigger is `< 1` -- zero or negative -- a DEFENSIVE case ML
    # should never produce. If it ever does, the entry still cannot be a tier
    # and the import still must not die on it.
    #
    # Skipping is safe, and that is a property of `pxq_diff`, not an
    # assumption: every live tier no local row references is re-emitted as an
    # untracked keep (`array.append({"id": live.id})`), so the skipped node
    # survives untouched on MercadoLibre even though nothing here mirrors it.
    #
    # Checked EXPLICITLY here rather than by catching `create_pxq_tier`'s
    # HTTPException and reading its message: a skip that depends on the wording
    # of an error string breaks silently the day someone rephrases it, and this
    # is a money path.
    #
    # And ONLY this condition. It is individually decidable -- no other entry
    # can change the verdict on it -- and known by design. Every other 422 the
    # loop can raise still propagates and aborts: two entries sharing a
    # `cantidad_minima` is AMBIGUOUS (nothing says which price wins), and
    # picking one silently would persist a money value nobody chose. Guarded by
    # `test_a_duplicate_quantity_still_aborts_because_nothing_says_which_entry_wins`.
    importable = [f for f in fields if f.cantidad_minima >= 1]
    skipped = [
        SkippedLiveEntry(ml_price_id=f.ml_price_id, cantidad_minima=f.cantidad_minima)
        for f in fields
        if f.cantidad_minima < 1
    ]

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
        for f in importable
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
    if skipped:
        # WARNING, and only AFTER the commit: this records what the import
        # actually left behind, not what it was about to. A 422 raised mid-loop
        # never reaches here, and logging a skip for a request that persisted
        # nothing would be a false record on a money path.
        logger.warning(
            "PxQ adopt-live skipped %s live price(s) this mirror cannot represent (cantidad_minima < 1) "
            "item_id=%s publicacion_ml_id=%s ml_price_ids=%s cantidades=%s usuario_id=%s",
            len(skipped),
            item_id,
            publicacion_ml_id,
            [s.ml_price_id for s in skipped],
            [s.cantidad_minima for s in skipped],
            usuario_id,
        )
    return AdoptOutcome(imported=rows, skipped=skipped)
