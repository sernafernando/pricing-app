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
              values moved since the last sync while LIVE did not
              -> delete the old id (omit) + create a new entry without an id.
              The mutated id is NEVER sent back.

  * A live tier with no matching desired row (its id is not referenced by any
    desired tier's `ml_price_id`) is an UNTRACKED live tier and is preserved
    as a keep -- deleting something we never mirrored would be exactly the
    silent-delete failure mode this module exists to prevent (spec: "Unmirrored
    live tier is preserved").

  * DIVERGENCE (refuse, no array built) happens when:
      - a desired tier's `ml_price_id` is not present in the live read at all
        (we believe we synced it; live disagrees entirely -- something
        external happened to it), or
      - LIVE moved since the last sync, i.e. the live values differ from the
        SNAPSHOT this mirror recorded when ML last confirmed the tier.

    The snapshot (`synced_quantity` / `synced_amount`) is the shared base that
    makes this a three-way merge, and it is what the decision actually turns
    on:

      local vs snapshot | live vs snapshot | outcome
      ------------------|------------------|----------------------------------
      unchanged         | unchanged        | keep
      CHANGED           | unchanged        | modify (our edit, safe to write)
      unchanged         | CHANGED          | refuse: writing reverts their edit
      CHANGED           | CHANGED          | refuse: genuine concurrent edit

    A NULL snapshot means the tier was never synced, so there is nothing to
    have diverged from and it is a create.

    An earlier version of this module decided the same question by reading the
    row's `estado`. That field is a proxy for intent, and it cannot tell a
    local edit from a remote one: a tier sitting at `listo` overwrote whatever
    MercadoLibre held, silently, on the money path. Comparing local-only
    against live has the same blind spot — the two edits are
    indistinguishable without a shared base.

  * The empty-desired guard: an empty `desired_tiers` list refuses the write
    unless `allow_clear=True` is passed explicitly (design: "deleting all
    tiers must be intentional"). With `allow_clear=True` the emitted array is
    the empty array `[]` -- a full, explicit wipe of every live tier,
    including untracked ones; that is the one case where untracked live tiers
    are NOT preserved, because the caller asked for exactly that.

  * The result also carries `counts` (`PxqDiffCounts`): how many tiers fell
    into keep / create / modify / delete. Those four are NOT recoverable from
    the emitted array -- create and modify are byte-identical there, both
    `{quantity, amount}` with no id -- so the classification is recorded at
    the branch that decides it. See `PxqDiffCounts` for what `deletes` counts
    and why it overlaps `modifies`.

  * Invariant: this function never emits an `id` that was not present in
    `live_tiers`. Ids only ever come from `live_tiers` entries (either
    directly, for untracked keeps, or via a desired tier's `ml_price_id`
    which is validated against the live set before being echoed back).

This module receives already-selected data (which desired tiers should exist
after the sync (the snapshot columns), and the current
fresh live read). Deciding WHICH mirror rows are "desired" and performing the
actual HTTP call are the orchestrator's job (PR 3), not this module's.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Union, Tuple

# Declared HERE, and imported by `pxq_tier_service`, not the other way round.
# This module is pure by design — that is the whole reason it was split into
# its own slice — and importing the service would drag FastAPI and SQLAlchemy
# in behind it. Dependencies point from the service to the primitive.
#
# WHY 5: it is MercadoLibre's PLATFORM limit for PxQ tiers, established when
# this module was built — not a policy of ours we could relax. Consequence: a
# LIVE read returning more than 5 is an impossible state, so it means the read
# is untrustworthy (ML moved the limit, the proxy returned garbage, or we read
# the wrong item) and must degrade to a read-unavailable refusal, never to a
# conflict the operator is told to resolve — they cannot delete tiers ML would
# never have let them create. A ceiling breach on data the operator SENT is a
# different thing and stays a 422 (`pxq_tier_service.create_pxq_tier`).
#
# ponytail: `frontend/src/components/promociones/PxqPanel.jsx:7` declares a
# second copy (`const MAX_TIERS = 5`) — two copies of a platform limit drift
# silently. Unify when slice 5 of `pxq-adopt-live` touches that panel.
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

    `synced_quantity` / `synced_amount` are the SNAPSHOT: what MercadoLibre
    confirmed at the last successful sync. They are the shared base that makes
    this a three-way merge — local and live are each judged against it, so
    "who changed what" is answerable instead of guessed. `None` means the tier
    has never been synced, and there is nothing to have diverged from.

    This replaced an earlier rule that read `estado` to decide whether a
    difference was an intentional local edit. `estado` cannot distinguish a
    local edit from a remote one, so a tier sitting at `listo` overwrote
    whatever MercadoLibre held, silently, on the money path.
    """

    quantity: int
    amount: Money
    ml_price_id: Optional[str] = None
    synced_quantity: Optional[int] = None
    synced_amount: Optional[Money] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _to_decimal(self.amount))
        if self.synced_amount is not None:
            object.__setattr__(self, "synced_amount", _to_decimal(self.synced_amount))

    @property
    def has_snapshot(self) -> bool:
        return self.synced_quantity is not None and self.synced_amount is not None

    @property
    def local_changed(self) -> bool:
        """Did WE move it since the last sync?"""
        if not self.has_snapshot:
            return True
        return self.quantity != self.synced_quantity or self.amount != self.synced_amount

    def live_changed(self, live: "LiveTier") -> bool:
        """Did MERCADOLIBRE move it since the last sync?"""
        if not self.has_snapshot:
            return False
        return live.quantity != self.synced_quantity or live.amount != self.synced_amount


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
class PxqDiffCounts:
    """How many tiers landed in each of the four outcomes above.

    The emitted array CANNOT be classified after the fact: a keep emits
    `{"id": ...}`, but a create and a modify BOTH emit `{quantity, amount}`
    with no id. Anything downstream that infers the breakdown from the array
    ("has an id" vs "has no id") reports a price replacement of an existing
    tier as a brand-new tier -- which is what the sync log did, in a change
    whose entire purpose was making the next incident reconstructable. Only
    this module knows the answer, at emit time, so it says so here.

    `deletes` counts LIVE tiers that will no longer be represented in the
    emitted array, i.e. what stops existing on MercadoLibre's side. It is NOT
    disjoint from `modifies`: array-replace implements a modify as omit-the-
    old-id + create-a-new-entry, so every modify makes its live tier vanish
    and contributes one delete. The other -- and only other -- source is an
    explicit `allow_clear=True` wipe, where every live tier is dropped. An
    untracked live tier is preserved as a keep, so merely dropping a mirror
    row never registers as a delete; that is the whole point of the
    untracked-keep rule.

    Plain data: counting what was decided does not make this module impure.
    """

    keeps: int = 0
    creates: int = 0
    modifies: int = 0
    deletes: int = 0


@dataclass(frozen=True)
class PxqDiffResult:
    """Either an `array` ready to POST, or a `refusal` -- never both."""

    array: Optional[List[Dict[str, Any]]] = None
    refusal: Optional[PxqDiffRefusal] = None
    # Live ids no desired row references: preserved as keeps, never ours. The
    # write path claims them before value-matching, so a created tier cannot
    # adopt a stranger's id when the two happen to share quantity and price.
    untracked_ids: Tuple[str, ...] = ()
    # Defaulted so a refusal (which builds no array) reports all zeros without
    # every construction site having to say so.
    counts: PxqDiffCounts = PxqDiffCounts()

    @property
    def ok(self) -> bool:
        return self.refusal is None


def _tier_entry(quantity: Money, amount: Money) -> Dict[str, Any]:
    return {"quantity": int(quantity), "amount": float(_to_decimal(amount))}


def _count_vanishing_live_tiers(live_tiers: Sequence[LiveTier], array: List[Dict[str, Any]]) -> int:
    """How many live tiers the emitted array will make disappear.

    Read off the finished array on purpose: under array-replace, "will this
    live tier still exist afterwards?" is answered by exactly one thing --
    whether its id is echoed back. That is directly knowable here, and it is
    the only one of the four counts that is a property of the whole array
    rather than of a single desired row.
    """
    emitted_ids = {entry["id"] for entry in array if "id" in entry}
    return sum(1 for live in live_tiers if live.id not in emitted_ids)


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

    synced_ids = [d.ml_price_id for d in desired_tiers if d.ml_price_id is not None]
    if len(synced_ids) != len(set(synced_ids)):
        # Two desired rows pointing at the same live tier would emit that id
        # twice, handing MercadoLibre an array that contradicts itself.
        duplicated = sorted({i for i in synced_ids if synced_ids.count(i) > 1})
        return PxqDiffResult(
            refusal=PxqDiffRefusal(
                reason="duplicate_ml_price_id",
                divergences=[
                    PxqDivergence(ml_price_id=i, reason="duplicate ml_price_id across desired tiers")
                    for i in duplicated
                ],
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
        return PxqDiffResult(array=[], counts=PxqDiffCounts(deletes=len(live_tiers)))

    live_by_id: Dict[str, LiveTier] = {tier.id: tier for tier in live_tiers}

    divergences: List[PxqDivergence] = []
    referenced_live_ids: set = set()
    untracked: List[str] = []
    array: List[Dict[str, Any]] = []
    # Counted at the branch that DECIDES the outcome, never re-derived from the
    # finished array -- the array cannot tell a create from a modify.
    keeps = 0
    creates = 0
    modifies = 0

    for desired in desired_tiers:
        if desired.ml_price_id is None:
            # create: never synced before.
            array.append(_tier_entry(desired.quantity, desired.amount))
            creates += 1
            continue

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

        # Registered only once the id was actually found in the live read.
        # Doing it before the lookup happened to be harmless, because any
        # divergence aborts before the untracked-keep pass runs — but that ties
        # two unrelated invariants to the order of the code. It must hold for
        # every branch below, keeps included, so it goes here.
        referenced_live_ids.add(desired.ml_price_id)

        if not desired.has_snapshot:
            # The row claims to be synced (it carries an id) but records no
            # baseline, so "who moved this" is unanswerable. Treating it as a
            # local edit is what overwrote MercadoLibre before the snapshot
            # existed; the honest answer is to refuse and let a human look.
            divergences.append(
                PxqDivergence(
                    ml_price_id=desired.ml_price_id,
                    reason="no snapshot to compare against",
                    live={"id": live.id, "quantity": live.quantity, "amount": float(live.amount)},
                    desired={"quantity": desired.quantity, "amount": float(desired.amount)},
                )
            )
            continue

        matches = live.quantity == desired.quantity and live.amount == desired.amount
        if matches:
            # keep: only the id is echoed back, never invented, always the
            # exact id observed in `live_tiers`.
            array.append({"id": desired.ml_price_id})
            keeps += 1
            continue

        if desired.live_changed(live):
            # MercadoLibre moved since our last sync. Writing our value would
            # revert their change — and if we moved too, it is a genuine
            # concurrent edit. Either way the caller decides, not this diff.
            reason = (
                "both sides changed since the last sync"
                if desired.local_changed
                else "live changed since the last sync"
            )
            divergences.append(
                PxqDivergence(
                    ml_price_id=desired.ml_price_id,
                    reason=reason,
                    live={"id": live.id, "quantity": live.quantity, "amount": float(live.amount)},
                    desired={"quantity": desired.quantity, "amount": float(desired.amount)},
                )
            )
            continue

        # modify: an intentional, not-yet-synced local edit.
        # Delete-old (simply omitted) + create-new (no id) -- the mutated id
        # is never sent back.
        array.append(_tier_entry(desired.quantity, desired.amount))
        modifies += 1

    if divergences:
        return PxqDiffResult(refusal=PxqDiffRefusal(reason="divergence", divergences=divergences))

    # Untracked live tiers -- no desired tier referenced their id -- are
    # preserved as keeps. Not reached when we already refused above.
    for live in live_tiers:
        if live.id not in referenced_live_ids:
            untracked.append(live.id)
            array.append({"id": live.id})
            keeps += 1

    return PxqDiffResult(
        array=array,
        untracked_ids=tuple(untracked),
        counts=PxqDiffCounts(
            keeps=keeps,
            creates=creates,
            modifies=modifies,
            deletes=_count_vanishing_live_tiers(live_tiers, array),
        ),
    )
