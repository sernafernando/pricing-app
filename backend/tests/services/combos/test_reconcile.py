"""Pure reconcile of the combo bill of materials (combos-propios C1).

A source hands a FULL snapshot {combo: {component: quantity}}; the reconcile
diffs it against the stored rows. Removal is by absence: the source has no
deleted flag, so a pair (or a whole combo) missing from a full snapshot goes.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import pytest

from app.services.combos.reconcile import PISO_SNAPSHOT_COMPLETO, Plan, normalize, plan_combo, plan_full

D = Decimal


class TestNormalize:
    def test_drops_rows_without_a_positive_quantity_and_combos_left_empty(self) -> None:
        snapshot = {
            100: {500: 2, 501: 0, 502: None, 503: D("-1")},
            200: {600: 0},
        }
        assert normalize(snapshot) == {100: {500: D("2")}}

    def test_rounds_to_the_stored_scale(self) -> None:
        # Stored as Numeric(18, 4): an unrounded source value would look changed on every run.
        assert normalize({100: {500: D("1.00004")}}) == {100: {500: D("1.0000")}}

    def test_a_quantity_that_rounds_to_zero_is_not_a_component(self) -> None:
        # The CHECK (cantidad > 0) would reject the stored 0.0000.
        assert normalize({100: {500: D("0.00004")}}) == {}
        assert normalize({100: {500: D("0.00001")}}) == {}
        assert normalize({100: {500: 0.00001}}) == {}

    @pytest.mark.parametrize(
        "value",
        ["abc", "", "NaN", "inf", "-Infinity", float("nan"), float("inf"), D("NaN"), D("sNaN"), D("Infinity"), True],
    )
    def test_a_quantity_that_is_not_a_finite_number_is_not_a_component(self, value) -> None:
        # One bad source row must not abort the whole reconcile.
        assert normalize({100: {500: value, 501: D("1")}}) == {100: {501: D("1")}}

    def test_a_quantity_over_the_stored_precision_is_not_a_component(self) -> None:
        # Numeric(18, 4) holds under 10**14: a bigger value would abort the write.
        assert normalize({100: {500: D("1e14"), 501: D("1e30"), 502: D("99999999999999.9999")}}) == {
            100: {502: D("99999999999999.9999")}
        }


class TestPlanFull:
    def test_inserts_updates_and_deletes_by_absence(self) -> None:
        current = {
            100: {500: D("1"), 600: D("1")},
            200: {700: D("3")},
        }
        desired = {
            # 500 changes quantity, 600 is gone, 601 is new.
            100: {500: D("2"), 601: D("1")},
            200: {700: D("3")},
        }

        plan = plan_full(desired, current)

        assert plan.inserts == ((100, 601, D("1")),)
        assert plan.updates == ((100, 500, D("2")),)
        assert plan.deletes == ((100, 600),)
        assert plan.deletions_skipped is False

    def test_a_combo_absent_from_the_snapshot_loses_all_its_rows(self) -> None:
        current = {100: {500: D("1")}, 200: {700: D("1"), 701: D("2")}}
        plan = plan_full({100: {500: D("1")}}, current)
        assert plan.deletes == ((200, 700), (200, 701))
        assert plan.inserts == () and plan.updates == ()

    def test_an_equal_quantity_with_another_scale_is_not_an_update(self) -> None:
        plan = plan_full({100: {500: D("2")}}, {100: {500: D("2.0000")}})
        assert plan == Plan()

    def test_source_rows_without_a_positive_quantity_are_not_stored(self) -> None:
        # A row the source now reports with quantity 0 is removed like an absent one.
        plan = plan_full({100: {500: 0, 501: D("1")}}, {100: {500: D("1")}})
        assert plan.inserts == ((100, 501, D("1")),)
        assert plan.deletes == ((100, 500),)

    def test_empty_snapshot_deletes_nothing_and_warns(self, caplog) -> None:
        current = {100: {500: D("1")}}
        with caplog.at_level(logging.WARNING):
            plan = plan_full({}, current)
        assert plan.deletes == ()
        assert plan.deletions_skipped is True
        assert "combos" in caplog.text

    def test_snapshot_under_the_floor_skips_deletions_but_still_writes(self, caplog) -> None:
        # 4 stored combos, the snapshot brings 1 (25% < 50%): looks truncated.
        current = {c: {500: D("1")} for c in (100, 200, 300, 400)}
        with caplog.at_level(logging.WARNING):
            plan = plan_full({100: {500: D("2"), 501: D("1")}}, current)
        assert PISO_SNAPSHOT_COMPLETO == 0.5
        assert plan.deletes == ()
        assert plan.deletions_skipped is True
        assert plan.updates == ((100, 500, D("2")),)
        assert plan.inserts == ((100, 501, D("1")),)
        assert "floor" in caplog.text

    def test_snapshot_exactly_at_the_floor_deletes(self) -> None:
        current = {c: {500: D("1")} for c in (100, 200, 300, 400)}
        plan = plan_full({100: {500: D("1")}, 200: {500: D("1")}}, current)
        assert plan.deletions_skipped is False
        assert plan.deletes == ((300, 500), (400, 500))

    def test_a_snapshot_of_only_new_combos_deletes_nothing(self, caplog) -> None:
        # It brings as many combos as are stored, but none of them: the stored ones look lost.
        current = {c: {500: D("1")} for c in (100, 200, 300, 400)}
        with caplog.at_level(logging.WARNING):
            plan = plan_full({c: {500: D("1")} for c in (900, 901, 902, 903)}, current)
        assert plan.deletions_skipped is True
        assert plan.deletes == ()
        assert plan.inserts == tuple((c, 500, D("1")) for c in (900, 901, 902, 903))
        assert "floor" in caplog.text

    def test_the_floor_counts_stored_combos_the_snapshot_brings_not_new_ones(self) -> None:
        # 1 of 4 stored (25%) plus 3 new ones: under the floor however many new ones come.
        current = {c: {500: D("1")} for c in (100, 200, 300, 400)}
        plan = plan_full({c: {500: D("1")} for c in (100, 900, 901, 902)}, current)
        assert plan.deletions_skipped is True
        assert plan.deletes == ()

    def test_new_combos_do_not_stop_deletions_at_the_floor(self) -> None:
        # 2 of 4 stored (50%) plus new ones: at the floor, absences are trusted.
        current = {c: {500: D("1")} for c in (100, 200, 300, 400)}
        plan = plan_full({c: {500: D("1")} for c in (100, 200, 900)}, current)
        assert plan.deletions_skipped is False
        assert plan.deletes == ((300, 500), (400, 500))
        assert plan.inserts == ((900, 500, D("1")),)

    def test_first_fill_into_an_empty_table(self) -> None:
        plan = plan_full({100: {500: D("1")}}, {})
        assert plan.inserts == ((100, 500, D("1")),)
        assert plan.deletions_skipped is False


class TestPlanCombo:
    def test_reconciles_only_the_given_combo(self) -> None:
        current = {500: D("1"), 600: D("1")}
        plan = plan_combo(100, {500: D("3"), 601: D("1")}, current)
        assert plan.inserts == ((100, 601, D("1")),)
        assert plan.updates == ((100, 500, D("3")),)
        assert plan.deletes == ((100, 600),)

    def test_empty_components_delete_nothing_and_warn(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            plan = plan_combo(100, {500: 0}, {500: D("1")})
        assert plan.deletes == ()
        assert plan.deletions_skipped is True
        assert "100" in caplog.text
