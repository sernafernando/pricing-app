"""Pure array-replace diff for MercadoLibre PxQ tiers (design D4).

`POST /items/{ITEM_ID}/prices/standard/quantity` REPLACES the ENTIRE prices
array. There is no PATCH. Any tier omitted from the emitted array is deleted
on ML's side, whether or not this module ever heard of it. That is the single
highest-risk behavior in the whole PxQ feature, which is why the function is
kept pure (no DB session, no HTTP) and isolated into its own PR slice.

Semantics (design.md "Reconcile + Diff Algorithm", spec.md "Array-replace
write semantics" / "Refuse write on local/live divergence"):

  * keep   -> a desired tier's `ml_price_id` is present in the live read and
              the live tier's quantity/amount match what is desired
              -> emit `{"id": ml_price_id}` only.
  * create -> a desired tier has no `ml_price_id` (never synced)
              -> emit `{quantity, amount}`, no id.
  * delete -> a live tier is simply omitted from the emitted array (either
              because no desired tier references it, and it's an untracked
              live tier that stays as a "keep", OR a desired row that no
              longer exists is left out entirely by the caller not passing it
              in `desired_tiers`).
  * modify -> a desired tier previously synced (`ml_price_id` set) whose
              current values no longer match the live tier AND whose `estado`
              says the mismatch is an intentional, not-yet-synced local edit
              (`estado == "listo"`) -> delete the old id (omit) + create a
              new entry without an id. The mutated id is NEVER sent back.

  * A live tier with no matching desired row (its id is not referenced by any
    desired tier's `ml_price_id`) is an UNTRACKED live tier and is preserved
    as a keep -- deleting something we never mirrored would be exactly the
    silent-delete failure mode this module exists to prevent (spec: "Unmirrored
    live tier is preserved").

  * DIVERGENCE (refuse, no array built) happens when:
      - a desired tier's `ml_price_id` is not present in the live read at all
        (we believe we synced it; live disagrees entirely -- something
        external happened to it), or
      - a desired tier's `ml_price_id` IS present in live but its
        quantity/amount differ AND `estado == "sincronizado"` (we believe this
        row is already in sync with live; a live-side value we did not
        change ourselves disagreeing means an external actor changed it).
    `estado == "listo"` is what distinguishes an intentional, not-yet-synced
    local edit (-> modify) from an unexpected external change (-> divergence);
    without that flag "the price changed" and "someone edited ML behind our
    back" would be indistinguishable, and every routine price edit would
    incorrectly refuse.

  * The empty-desired guard: an empty `desired_tiers` list refuses the write
    unless `allow_clear=True` is passed explicitly (design: "deleting all
    tiers must be intentional"). With `allow_clear=True` the emitted array is
    the empty array `[]` -- a full, explicit wipe of every live tier,
    including untracked ones; that is the one case where untracked live tiers
    are NOT preserved, because the caller asked for exactly that.

  * Invariant: this function never emits an `id` that was not present in
    `live_tiers`. Ids only ever come from `live_tiers` entries (either
    directly, for untracked keeps, or via a desired tier's `ml_price_id`
    which is validated against the live set before being echoed back).

This module receives already-selected data (which desired tiers should exist
after the sync, e.g. `estado` in {"listo", "sincronizado"}, and the current
fresh live read). Deciding WHICH mirror rows are "desired" and performing the
actual HTTP call are the orchestrator's job (PR 3), not this module's.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Union

MAX_TIERS = 5

Money = Union[int, float, Decimal]


def _to_decimal(value: Money) -> Decimal:
    """Normalizes any numeric money representation to `Decimal` via its
    string form, never via a direct `Decimal(float)` construction -- that
    would bake in binary-float noise (e.g. `Decimal(0.1)` != `Decimal("0.1")`)
    and produce false "differs" verdicts between a DB-sourced `Decimal` and a
    JSON-sourced `float`."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass(frozen=True)
class LiveTier:
    """One tier as currently reported by MercadoLibre's live read.

    `id` is a plain string: it is opaque to this module and only ever
    round-tripped, never parsed or generated.
    """

    id: str
    quantity: int
    amount: Money

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _to_decimal(self.amount))


@dataclass(frozen=True)
class DesiredTier:
    """One tier as the local mirror wants it to exist after this sync.

    `ml_price_id` is `None` for a tier that has never been synced (create).
    `estado` disambiguates a matched-but-differing id: `"listo"` means the
    difference is an intentional local edit not yet pushed (modify);
    `"sincronizado"` means the row believes it already matches live, so a
    difference is an unexpected external change (divergence).
    """

    quantity: int
    amount: Money
    ml_price_id: Optional[str] = None
    estado: str = "listo"

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _to_decimal(self.amount))


@dataclass(frozen=True)
class PxqDivergence:
    """One disagreement between live and the local mirror, part of the
    refusal payload -- never part of a write array."""

    ml_price_id: Optional[str]
    reason: str
    live: Optional[Dict[str, Any]] = None
    desired: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class PxqDiffRefusal:
    """Signals the diff refuses to build a write array. Carries the diff so
    the caller (PR 3) can surface it as a 409 with the divergence detail --
    this module itself never raises HTTP exceptions."""

    reason: str
    divergences: List[PxqDivergence]


@dataclass(frozen=True)
class PxqDiffResult:
    """Either an `array` ready to POST, or a `refusal` -- never both."""

    array: Optional[List[Dict[str, Any]]] = None
    refusal: Optional[PxqDiffRefusal] = None

    @property
    def ok(self) -> bool:
        return self.refusal is None


def _tier_entry(quantity: Money, amount: Money) -> Dict[str, Any]:
    return {"quantity": int(quantity), "amount": float(_to_decimal(amount))}


def diff_pxq_tiers(
    live_tiers: Sequence[LiveTier],
    desired_tiers: Sequence[DesiredTier],
    *,
    allow_clear: bool = False,
) -> PxqDiffResult:
    """Computes the full array to POST to
    `/items/{ITEM_ID}/prices/standard/quantity`, or refuses with the reason
    and diff. Pure: no DB session, no HTTP, no I/O."""

    if len(desired_tiers) > MAX_TIERS:
        return PxqDiffResult(
            refusal=PxqDiffRefusal(
                reason="too_many_tiers",
                divergences=[PxqDivergence(ml_price_id=None, reason=f"more than {MAX_TIERS} desired tiers")],
            )
        )

    if not desired_tiers:
        if not allow_clear:
            return PxqDiffResult(
                refusal=PxqDiffRefusal(
                    reason="empty_desired_set",
                    divergences=[
                        PxqDivergence(
                            ml_price_id=live_tier.id,
                            reason="empty desired set would delete this live tier without an explicit allow_clear=True",
                            live={
                                "id": live_tier.id,
                                "quantity": live_tier.quantity,
                                "amount": float(live_tier.amount),
                            },
                        )
                        for live_tier in live_tiers
                    ],
                )
            )
        # Explicit, intentional full wipe: every live tier (tracked or not)
        # is dropped. The empty array itself carries that intent to ML.
        return PxqDiffResult(array=[])

    live_by_id: Dict[str, LiveTier] = {tier.id: tier for tier in live_tiers}

    divergences: List[PxqDivergence] = []
    referenced_live_ids: set = set()
    array: List[Dict[str, Any]] = []

    for desired in desired_tiers:
        if desired.ml_price_id is None:
            # create: never synced before.
            array.append(_tier_entry(desired.quantity, desired.amount))
            continue

        referenced_live_ids.add(desired.ml_price_id)
        live = live_by_id.get(desired.ml_price_id)

        if live is None:
            # Mirror believes this id exists; live disagrees entirely.
            divergences.append(
                PxqDivergence(
                    ml_price_id=desired.ml_price_id,
                    reason="mirror ml_price_id absent from live read",
                    desired={"quantity": desired.quantity, "amount": float(desired.amount)},
                )
            )
            continue

        matches = live.quantity == desired.quantity and live.amount == desired.amount
        if matches:
            # keep: only the id is echoed back, never invented, always the
            # exact id observed in `live_tiers`.
            array.append({"id": desired.ml_price_id})
            continue

        if desired.estado == "sincronizado":
            # Mirror believed this was already in sync with live; an
            # unexplained difference means something external changed it.
            divergences.append(
                PxqDivergence(
                    ml_price_id=desired.ml_price_id,
                    reason="matched id differs in quantity/amount",
                    live={"id": live.id, "quantity": live.quantity, "amount": float(live.amount)},
                    desired={"quantity": desired.quantity, "amount": float(desired.amount)},
                )
            )
            continue

        # modify: an intentional, not-yet-synced local edit.
        # Delete-old (simply omitted) + create-new (no id) -- the mutated id
        # is never sent back.
        array.append(_tier_entry(desired.quantity, desired.amount))

    if divergences:
        return PxqDiffResult(refusal=PxqDiffRefusal(reason="divergence", divergences=divergences))

    # Untracked live tiers -- no desired tier referenced their id -- are
    # preserved as keeps. Not reached when we already refused above.
    for live in live_tiers:
        if live.id not in referenced_live_ids:
            array.append({"id": live.id})

    return PxqDiffResult(array=array)
