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

from dataclasses import dataclass
from decimal import Decimal
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


def is_keep(row: MlPxqTier) -> bool:
    """True when the row still holds the values ML last confirmed, i.e. this
    sync treated it as a keep and its id survived.

    Public (slice C, D5): `sync_pxq_tiers` classifies keep/create/modify off
    this SAME predicate, BEFORE the POST -- once `remap_and_confirm` has run,
    every row looks like a keep, so the classification has to be captured
    ahead of it."""
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
    created row cannot adopt a stranger's tier.

    Exactly TWO code paths may advance
    `cantidad_sincronizada`/`precio_sincronizado`, and both write values
    MercadoLibre itself reported:

      * this function -- POST-WRITE CONFIRMATION. The values come from the
        re-read that proves the POST landed, never from what we merely
        attempted to send.
      * `live_entry_to_tier_fields` -- IMPORT (`ml_pxq_adopt_service`). The
        values come from the same live read that produced the row's
        `cantidad_minima`/`precio_unitario`, in the same operation, for a row
        that did not exist before. There is no prior value to overwrite and
        no third party's edit to lose.

    Nothing else may, and in particular `update_pxq_tier` must not: advancing
    the snapshot on an edit makes a local change look, to the next sync,
    exactly like nobody changed anything, and that sync then silently
    overwrites whatever MercadoLibre holds. The rule is not "only one
    writer" -- it is "only from a value ML reported".

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
        if not is_keep(row):
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
        if row.ml_price_id is not None and is_keep(row):
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


@dataclass(frozen=True)
class ImportedTierFields:
    """The fields needed to construct one `MlPxqTier` from a live ML entry.

    `cantidad_sincronizada`/`precio_sincronizado` equal
    `cantidad_minima`/`precio_unitario` BY CONSTRUCTION, and that is the whole
    point: on an import the local value IS the value MercadoLibre reported, in
    the same operation, so the snapshot is already correct and there is
    nothing to have diverged from. Carrying them as separate fields rather
    than letting the caller re-derive them is what stops a caller from
    forgetting the snapshot and leaving behind a row that every future sync
    refuses with "no snapshot to compare against" (`pxq_diff`) -- a row that
    is permanently un-syncable, which is the very damage this import exists to
    repair.
    """

    cantidad_minima: int
    precio_unitario: Decimal
    ml_price_id: str
    cantidad_sincronizada: int
    precio_sincronizado: Decimal


def live_entry_to_tier_fields(entry: Dict[str, Any]) -> ImportedTierFields:
    """Maps ONE raw live PxQ entry to the fields of a new mirror row.

    Pure: no DB session, no HTTP -- the same discipline as the rest of this
    module. It builds values; it does not decide what to do with them.

    `id` is coerced with `str()` because MercadoLibre may return it as a
    NUMBER; `ml_price_id` is `String(64)` and every other reader in this
    feature (`_parse_live_tiers`, `_live_tiers_from_raw`, `remap_and_confirm`)
    already does `str(entry["id"])`.

    `amount` goes through `_to_decimal`, i.e. `Decimal(str(value))`, NEVER
    `Decimal(float)` -- a direct float construction bakes in binary noise and
    produces false "differs" verdicts against the DB-sourced `Decimal` on the
    very next sync.

    Raises:
        KeyError, TypeError, ValueError or ArithmeticError on a malformed
        entry. Deliberately NOT swallowed here: this module is pure and has no
        outcome vocabulary, so inventing one would mean guessing what the
        caller wants. The orchestrator catches exactly that tuple and answers
        `adopt_read_unavailable`. `ArithmeticError` is in it because
        `decimal.InvalidOperation` is NOT a `ValueError` -- the bug
        `_live_tiers_from_raw` was already fixed for, after it escaped as a
        raw 500.
    """
    quantity = int(entry["quantity"])
    amount = _to_decimal(entry["amount"])
    return ImportedTierFields(
        cantidad_minima=quantity,
        precio_unitario=amount,
        ml_price_id=str(entry["id"]),
        cantidad_sincronizada=quantity,
        precio_sincronizado=amount,
    )
