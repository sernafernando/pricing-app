"""Confirmation matching for a PxQ sync.

After the write, MercadoLibre is re-read and each mirror row must be matched
to the entry that confirms it. Only from a CONFIRMED entry may the snapshot
advance -- never from what we merely attempted to send, because a stale
snapshot is what lets the next sync overwrite somebody else's change.

Extracted from `ml_pxq_write_service` on purpose. Five separate defects were
found in this logic while it sat inside a 1700-line orchestration module, and
several of them were introduced while fixing the previous one. It is small,
it is decidable on its own, and it holds the rule the whole feature rests on,
so it gets reviewed on its own -- the same reasoning that split `pxq_diff`.

Pure: no DB session, no HTTP. It mutates the mirror rows it is handed and
reports whether every one of them was confirmed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from app.models.ml_pxq_tier import ESTADO_DESCONOCIDO, ESTADO_SINCRONIZADO, MlPxqTier
from app.services.pxq_diff import _to_decimal


def is_priceable(row: MlPxqTier) -> bool:
    """A tier is priceable only once it carries a whole-shipment cost.

    Deliberately reads the DATA, not `estado`: the status field is a summary
    that nothing recomputes when the cost is cleared, so trusting it let a
    cost-less tier reach MercadoLibre.
    """
    return row.costo_envio_total is not None


def _row_matches_snapshot(row: MlPxqTier) -> bool:
    """True when the row still holds the values ML last confirmed, i.e. this
    sync treated it as a keep and its id survived."""
    return row.cantidad_sincronizada == row.cantidad_minima and row.precio_sincronizado == row.precio_unitario


def remap_and_confirm(
    rows: List[MlPxqTier],
    confirmed_raw: List[Dict[str, Any]],
    untracked_ids: Optional[Sequence[str]] = None,
) -> bool:
    """Matches each written/kept tier to its CONFIRMED live entry and writes
    the snapshot from those CONFIRMED values -- never from what we merely
    attempted to send.

    Matching everything by (quantity, amount) let a row claim a tier it never
    created: an untracked tier -- one alive in ML that we preserve as a keep and
    do not own -- with the same quantity and price could be claimed, and the
    next sync would then modify or delete somebody else's tier. List order
    decided the winner.

    So the match happens in two passes. A row whose values still equal its
    snapshot was a KEEP: its id survived the write, so it is matched by that id.
    A create or a modify has no surviving id -- a modify is emitted as
    delete-old plus create-new -- so those match by value, but only against ids
    nobody else owns: `untracked_ids` are claimed up front precisely so a
    created row cannot adopt a stranger's tier. This is the
    only place in the whole service allowed to advance
    `cantidad_sincronizada`/`precio_sincronizado`.

    PRECONDITION: every row passed here has already survived `diff_pxq_tiers`,
    which refuses a row carrying an `ml_price_id` with no snapshot ("no
    snapshot to compare against"). That matters because such a row would fall
    into pass 2 and match by value while holding a known id. This function is
    unit-tested in isolation, so the precondition is stated rather than
    assumed.

    Returns True only if EVERY priceable row was confirmed. A row that could
    not be matched goes to `desconocido`, and the caller must not report the
    sync as finished — the earlier fix covered a re-read that failed entirely
    and left this partial case reporting success."""
    all_confirmed = True
    claimed_ids: set = set(str(i) for i in (untracked_ids or ()))

    # Pass 1: keeps, matched by the id that survived the write.
    for row in rows:
        if not is_priceable(row) or row.ml_price_id is None:
            continue
        if not _row_matches_snapshot(row):
            continue
        match = next(
            (entry for entry in confirmed_raw if str(entry["id"]) == str(row.ml_price_id)),
            None,
        )
        if match is None:
            # The id we kept is gone from the confirmation — ML may have
            # rotated it. Falling through silently left the row `sincronizado`
            # pointing at an id that no longer exists, and reported success.
            row.estado = ESTADO_DESCONOCIDO
            all_confirmed = False
            continue
        claimed_ids.add(str(match["id"]))
        row.cantidad_sincronizada = row.cantidad_minima
        row.precio_sincronizado = row.precio_unitario
        row.estado = ESTADO_SINCRONIZADO

    # Pass 2: creates and modifies, matched by value over what is left.
    for row in rows:
        if not is_priceable(row):
            continue
        if row.ml_price_id is not None and _row_matches_snapshot(row):
            # Already resolved in pass 1 by its surviving id.
            continue
        # A create has no id; a modify was emitted as delete-old plus
        # create-new, so its old id is gone. Both match by value, and only
        # against ids nobody else has claimed.
        match = next(
            (
                entry
                for entry in confirmed_raw
                if str(entry["id"]) not in claimed_ids
                and int(entry["quantity"]) == row.cantidad_minima
                and _to_decimal(entry["amount"]) == _to_decimal(row.precio_unitario)
            ),
            None,
        )
        if match is None:
            # This row's write cannot be confirmed against the re-read --
            # treat it the same as an unconfirmed outcome, never guess.
            row.estado = ESTADO_DESCONOCIDO
            all_confirmed = False
            continue
        claimed_ids.add(str(match["id"]))
        row.ml_price_id = str(match["id"])
        row.cantidad_sincronizada = row.cantidad_minima
        row.precio_sincronizado = row.precio_unitario
        row.estado = ESTADO_SINCRONIZADO

    return all_confirmed
