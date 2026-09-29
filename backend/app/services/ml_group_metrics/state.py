"""Group-level `gauss_status` derivation (ventas-ml-rediseno PR20.T5/T6,
spec `ml-order-stored-metrics` R9/R10).

Mirrors `order_metrics.read.metrics_state_for_orders`'s per-order
precedence (PR7.T4), applied across a group's members: a group is only as
resolved as its WEAKEST member, never a partial view over the ones that
happen to be ready.
"""

from __future__ import annotations

from typing import Sequence

# Any member in this state means the group as a whole cannot be summed yet
# -- the group is `recalculating` (mirrors PR7.T4's "recalculating wins
# over the stored status"). `pending` (no row at all) collapses into the
# SAME group-level outcome as `recalculating` even though it is a distinct
# per-order query shape (T20's note) -- the group-level caller does not
# need to tell the two apart, only the per-order reader does.
_NOT_YET_RESOLVED = frozenset({"recalculating", "pending"})

_KNOWN_MEMBER_STATES = frozenset({"ok", "provisional", "unresolved", "recalculating", "pending", "failed"})


def group_gauss_status(member_states: Sequence[str]) -> str:
    """Derives the group's `gauss_status` from its members' per-order
    `metrics_state` values (`order_metrics.read.metrics_state_for_orders`'s
    vocabulary). Precedence, in order:

    1. `'failed'` -- ANY member is parked. Wins over everything else.
    2. `'recalculating'` -- ANY member lacks a fresh row (`recalculating`
       or `pending`).
    3. `'unresolved'` -- ANY resolved member's own stored status is
       `unresolved`.
    4. `'provisional'` -- ANY resolved member's own stored status is
       `provisional` (the group is only as good as its weakest resolved
       member, same all-or-nothing spirit as `aggregate_pack_metrics`'s
       numeric sum, extended to status).
    5. `'ok'` -- every member is `ok`.

    An empty `member_states` (a group with zero current members) is
    `'unresolved'` -- there is nothing to sum, so it is never falsely
    reported as `ok`. In practice `recompute_group_metrics` never calls
    this with an empty list for a group it still stores (R14: a group with
    zero members gets no record at all) -- this is a defensive fallback,
    not a code path this module expects to be exercised.

    Raises `ValueError` on an unrecognized member state -- fails closed
    rather than silently treating a typo/new-status as resolved."""
    states = list(member_states)

    unknown = set(states) - _KNOWN_MEMBER_STATES
    if unknown:
        raise ValueError(f"unknown member gauss/metrics state(s): {sorted(unknown)!r}")

    if not states:
        return "unresolved"

    if "failed" in states:
        return "failed"
    if _NOT_YET_RESOLVED & set(states):
        return "recalculating"
    if "unresolved" in states:
        return "unresolved"
    if "provisional" in states:
        return "provisional"
    return "ok"
