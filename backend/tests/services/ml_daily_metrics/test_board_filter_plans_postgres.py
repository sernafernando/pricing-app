"""Every Métricas ML filter, alone and all at once, over the WORST period (366 days), on the volume seed: no
statement of a board request may take a plan shape that explodes with the data (ODD `metricas-filtros-performance`
S5, owner 2026-11-12: "no puede volver a pasar bajo ningún punto de vista").

Each statement the request runs is planned again with `EXPLAIN (FORMAT JSON)` right after it ran (its temporary
tables still exist) and two shapes are refused:

- a per-row subquery: a SubPlan that is not hashed (re-run for every outer row) reading a real table;
- a nested loop that re-scans a real table for every outer row (a Seq Scan on its inner side).

Real table = anything but the request's own small `board_*` temp tables. A filter is a predicate that must ride
an index, a hash or the small temp tables: a correlated `EXISTS`, a function on a column inside a per-row
subquery, or an `OR` across tables lands in one of those two shapes on this volume. Plans, never timings (a wall
clock bound would be flaky on a shared CI box); the timings are printed with `-s`.
"""

from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import Any, Dict, Iterator, List, Tuple

import pytest
from sqlalchemy import event, text

from app.routers.ml_metricas import build_board_response
from app.services.ml_daily_metrics import board
from tests.services.ml_daily_metrics import test_board_volume_postgres as volume
from tests.services.ml_daily_metrics.test_board_volume_postgres import (  # noqa: F401 -- fixtures
    _frozen_clock,
    volume_ads,
    volume_sell,
    volume_session,
)

pytestmark = [pytest.mark.postgres, pytest.mark.volume]

WORST_PERIOD_DAYS = 366
PM_PAIRS = [("EPSON", "CAT0"), ("SAMSUNG", "CAT1"), ("SONY", "CAT2")]
EVERY_FILTER: Dict[str, Any] = dict(
    stores=("2645", "57997", "sin_tienda"),
    marcas=("Samsung", "Epson", "Sony"),
    categorias=("Cat0", "Cat1"),
    subcategorias=(1, 2, 3, 4),
    pms=(1,),
    q="volumen",
    pub_status=("active", "paused"),
    pub_type=("clasica", "premium", "full"),
    pub_status_exclude=("closed",),
    pub_type_exclude=("catalogo",),
    alerts=board.ALERTS,
    stock=("con_stock", "sin_stock"),
    stock_exclude=("sin_dato",),
    ageing=("up_to_30", "from_31_to_60"),
    ageing_exclude=("over_60",),
    solo_con_ventas=True,
    compare="anio_anterior",
)
TP = {"costos_tp": True, "tp_store_ids": (2645,)}
ADS = {"restar_publicidad": True}
SCENARIOS: List[Tuple[str, Dict[str, Any]]] = [
    ("no filter", {}),
    *[(f"{name} alone", {name: value}) for name, value in EVERY_FILTER.items()],
    ("search: a sku", {"q": "sku-12"}),
    ("search: an MLA", {"q": "MLA7700012"}),
    ("search: nothing", {"q": "zzzz-nada"}),
    ("by publication", {"group_by": "publication"}),
    *[(f"grouped by {d}", {"group_by": "group", "dimension": d}) for d in volume.GROUP_DIMENSIONS],
    ("costos tp", TP),
    ("restar publicidad", ADS),
    ("restar todo", {**ADS, "restar_todo": True}),
    *[(f"sort {s}", {"sort": s, **(TP if s == "total_tp" else {})}) for s in board.SORTS if s not in board.SELL_SORTS],
    ("every filter", EVERY_FILTER),
    ("every filter, by publication", {**EVERY_FILTER, "group_by": "publication"}),
    ("every filter, grouped by pm", {**EVERY_FILTER, "group_by": "group", "dimension": "pm"}),
    ("every filter, tp, ads, sort markup", {**EVERY_FILTER, **TP, **ADS, "sort": "markup"}),
]


def _nodes(plan: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    yield plan
    for child in plan.get("Plans", ()):
        yield from _nodes(child)


def _scans_a_real_table(plan: Dict[str, Any]) -> List[str]:
    return [
        node["Relation Name"]
        for node in _nodes(plan)
        if "Scan" in node["Node Type"] and node.get("Relation Name") and not node["Relation Name"].startswith("board_")
    ]


def _seq_scans_a_real_table(plan: Dict[str, Any]) -> List[str]:
    return [
        node["Relation Name"]
        for node in _nodes(plan)
        if node["Node Type"] == "Seq Scan" and not node["Relation Name"].startswith("board_")
    ]


def explosive_shapes(plan: Dict[str, Any]) -> List[str]:
    """The per-row re-reads of a real table in `plan` (an `EXPLAIN (FORMAT JSON)` root plan)."""
    found = []
    for node in _nodes(plan):
        # The node's own expressions say how it uses a SubPlan: "(hashed SubPlan 2)" is built ONCE and probed;
        # a bare "SubPlan 2" re-runs for every row. InitPlans are not SubPlans (they run once).
        expressions = json.dumps({key: value for key, value in node.items() if key != "Plans"})
        for child in node.get("Plans", ()):
            name = child.get("Subplan Name", "")
            if child.get("Parent Relationship") == "SubPlan" and f"hashed {name}" not in expressions:
                tables = _scans_a_real_table(child)
                if tables:
                    found.append(f"per-row SubPlan over {tables}")
        if node["Node Type"] == "Nested Loop" and node["Plans"][0]["Plan Rows"] > 1:
            tables = _seq_scans_a_real_table(node["Plans"][1])
            if tables:
                found.append(f"nested loop re-scanning {tables} for {node['Plans'][0]['Plan Rows']} outer rows")
    return found


class _Planner:
    """Plans every statement a board request runs, right after it runs."""

    def __init__(self) -> None:
        self.shapes: List[Tuple[str, str]] = []
        self.statements = 0

    def after(self, conn, cursor, statement, parameters, context, executemany) -> None:
        head = statement.lstrip()
        if not head.upper().startswith(("SELECT", "WITH", "CREATE TEMPORARY TABLE")):
            return
        self.statements += 1
        body = head.split(" AS ", 1)[1] if head.startswith("CREATE TEMPORARY TABLE") else head
        explain = cursor.connection.cursor()
        explain.execute("EXPLAIN (FORMAT JSON) " + body, parameters)
        raw = explain.fetchone()[0]
        root = (raw if isinstance(raw, list) else json.loads(raw))[0]["Plan"]
        for shape in explosive_shapes(root):
            self.shapes.append((shape, " ".join(head.split())[:160]))


@pytest.fixture(scope="module")
def plans_world(volume_sell, volume_ads):  # noqa: F811 -- the imported fixtures
    # The sell in / sell out KPIs read the campaigns' groups too (empty here, like the rest of sell out).
    volume_sell.execute(
        text(
            "CREATE TEMPORARY TABLE sell_out_campana_grupos (campana_id BIGINT, grupo_id BIGINT);"
            "CREATE TEMPORARY TABLE offset_grupo_filtros (id INTEGER, grupo_id INTEGER, marca VARCHAR(255), "
            "categoria VARCHAR(255), subcategoria_id INTEGER, item_id INTEGER)"
        )
    )
    return volume_sell


@pytest.fixture(autouse=True)
def _pm_pairs(monkeypatch):
    # The PM filter's pairs, without seeding users: what `marcas_pm` resolves `pms` to.
    monkeypatch.setattr(board, "_resolve_pm_pairs", lambda db, pms: PM_PAIRS)


def _plan_request(session, filters: Dict[str, Any], scope_pairs=None) -> Tuple[_Planner, float]:
    f = board.BoardFilter(
        date_from=volume.TODAY - timedelta(days=WORST_PERIOD_DAYS - 1), date_to=volume.TODAY, **filters
    )
    planner = _Planner()
    connection = session.connection()
    event.listen(connection, "after_cursor_execute", planner.after)
    started = time.perf_counter()
    try:
        build_board_response(session, f, limit=50, offset=0, can_see_margin=True, scope_pairs=scope_pairs)
    finally:
        event.remove(connection, "after_cursor_execute", planner.after)
    return planner, (time.perf_counter() - started) * 1000


def test_the_guard_recognizes_the_explosive_shapes() -> None:
    """The two refused shapes, as Postgres reports them, so the guard cannot pass by matching nothing."""
    scan = {"Node Type": "Seq Scan", "Relation Name": "productos_erp", "Plan Rows": 2000}
    temp = {"Node Type": "Seq Scan", "Relation Name": "board_pair_agg", "Plan Rows": 2000}
    correlated = {
        "Node Type": "Seq Scan",
        "Relation Name": "board_pair_agg",
        "Plan Rows": 9,
        "Filter": "(SubPlan 1)",
        "Plans": [{**scan, "Parent Relationship": "SubPlan", "Subplan Name": "SubPlan 1"}],
    }
    hashed = {**correlated, "Filter": "(ANY (mla = (hashed SubPlan 1).col1))"}
    looped = {"Node Type": "Nested Loop", "Plan Rows": 9, "Plans": [{**temp, "Plan Rows": 500}, scan]}
    single = {"Node Type": "Nested Loop", "Plan Rows": 9, "Plans": [{**temp, "Plan Rows": 1}, scan]}

    assert explosive_shapes(correlated) == ["per-row SubPlan over ['productos_erp']"]
    assert explosive_shapes(looped) == ["nested loop re-scanning ['productos_erp'] for 500 outer rows"]
    assert explosive_shapes(hashed) == []
    assert explosive_shapes(single) == []


@pytest.mark.parametrize("label, filters", SCENARIOS, ids=[label for label, _f in SCENARIOS])
def test_no_filter_takes_an_explosive_plan_over_the_worst_period(plans_world, label, filters) -> None:
    planner, elapsed_ms = _plan_request(plans_world, filters)
    print(f"\n{label}: {planner.statements} statements planned, {elapsed_ms:.0f} ms")

    assert planner.statements > 10  # the request really ran (and was planned) statement by statement
    assert planner.shapes == []


@pytest.mark.parametrize("scope_pairs", [PM_PAIRS, PM_PAIRS[:1], []], ids=["pm scope", "pm scope one pair", "none"])
def test_a_pm_scoped_user_takes_no_explosive_plan_either(plans_world, scope_pairs) -> None:
    planner, elapsed_ms = _plan_request(plans_world, EVERY_FILTER, scope_pairs=scope_pairs)
    print(f"\nscoped {scope_pairs}: {planner.statements} statements planned, {elapsed_ms:.0f} ms")

    assert planner.statements > 5
    assert planner.shapes == []


def test_sell_in_out_takes_no_explosive_plan(plans_world) -> None:
    planner, _ms = _plan_request(plans_world, {**EVERY_FILTER, "sell_in_out": True, "sort": "markup_sell"})

    assert planner.statements > 10
    assert planner.shapes == []
