"""ventas-ml-rediseno PR20.T5 — `group_gauss_status(member_states)` truth
table.

A group is `unresolved`/`recalculating` (SM R10) if ANY member is
`pending`, `recalculating`, `unresolved`, or `failed`. Precedence mirrors
PR7.T4's per-order `metrics_state_for_orders` rule, applied across
members:

1. `'failed'` wins if ANY member is parked -- a parked member is never
   shown as recalculating forever.
2. else `'recalculating'` if ANY member lacks a fresh row (is itself
   `recalculating` or `pending`).
3. else `'unresolved'` if ANY resolved member's stored status is
   `unresolved`.
4. else the group is resolvable -- `'ok'`/`'provisional'` from the
   aggregate (this function itself never picks between those two; it only
   says the group CAN be summed -- the caller derives ok/provisional from
   the actual aggregate the same way a single order does).
"""

from __future__ import annotations

import pytest

from app.services.ml_group_metrics.state import group_gauss_status


class TestGroupGaussStatus:
    def test_all_ok_members_resolve(self):
        assert group_gauss_status(["ok", "ok"]) == "ok"

    def test_single_ok_member_resolves(self):
        assert group_gauss_status(["ok"]) == "ok"

    def test_any_failed_member_wins_over_everything(self):
        assert group_gauss_status(["ok", "failed"]) == "failed"
        assert group_gauss_status(["failed", "recalculating", "pending", "unresolved"]) == "failed"

    def test_any_recalculating_member_wins_over_unresolved_and_pending(self):
        assert group_gauss_status(["ok", "recalculating"]) == "recalculating"
        assert group_gauss_status(["recalculating", "unresolved", "pending"]) == "recalculating"

    def test_any_pending_member_without_failed_or_recalculating_is_recalculating(self):
        # "no row at all" (`pending`) is a distinct query shape from
        # `recalculating` (T20's note) but the same GROUP-level outcome:
        # the group cannot be summed yet.
        assert group_gauss_status(["ok", "pending"]) == "recalculating"

    def test_any_unresolved_member_without_failed_pending_or_recalculating_is_unresolved(self):
        assert group_gauss_status(["ok", "unresolved"]) == "unresolved"

    def test_all_provisional_resolves(self):
        assert group_gauss_status(["provisional", "provisional"]) == "provisional"

    def test_mixed_ok_and_provisional_resolves_as_provisional(self):
        # A group is only as good as its weakest resolved member -- mirrors
        # `aggregate_pack_metrics`'s all-or-nothing discipline extended to
        # status, not just to the numeric sum.
        assert group_gauss_status(["ok", "provisional"]) == "provisional"

    def test_empty_members_is_unresolved(self):
        assert group_gauss_status([]) == "unresolved"

    def test_unknown_state_raises(self):
        with pytest.raises(ValueError):
            group_gauss_status(["ok", "bogus"])
