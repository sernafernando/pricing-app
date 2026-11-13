"""The matrix guard (`per_row_plans`) on hand-made plans: a hashed subplan's hash build is not per row, any other
sequential scan of a big table run more than once is."""

from __future__ import annotations

from typing import Any

from tests.services.ml_publications.view.test_filter_matrix_plans_volume_postgres import per_row_plans


def plan(filter_: str, subplan: str) -> dict[str, Any]:
    scan = {"Node Type": "Seq Scan", "Relation Name": "ml_item_product_links", "Actual Loops": 2}
    sub = {"Node Type": "Hash Join", "Subplan Name": subplan, "Actual Loops": 2, "Plans": [scan]}
    items = {"Node Type": "Index Scan", "Relation Name": "ml_items", "Filter": filter_, "Actual Loops": 1}
    return {"Plan": {**items, "Plans": [sub]}}


def test_a_hashed_subplan_build_is_not_per_row() -> None:
    assert per_row_plans(plan("((NOT (hashed SubPlan 3)) OR (hashed SubPlan 5))", "SubPlan 3")) == []


def test_a_subplan_run_per_row_is_still_flagged() -> None:
    assert per_row_plans(plan("((NOT (SubPlan 3)) OR (hashed SubPlan 5))", "SubPlan 3")) == [
        "seq scan of ml_item_product_links x2"
    ]
