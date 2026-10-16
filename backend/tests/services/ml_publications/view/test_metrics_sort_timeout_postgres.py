"""Sorting the Publicaciones list by Métricas ML's figures ranks the WHOLE filtered set inside a Board: a statement
timeout there is the list's controlled 503 (`consulta_lenta`), and the Board's temporary MLA-set table does not
survive it -- on no connection, pooled or not.

Real Postgres through the router (the 503 mapping is the router's): the ranking statement is slowed with a
`pg_sleep`, and a tiny `statement_timeout` is armed on that statement ONLY, AFTER the Board has materialized its MLA
set. Every earlier statement keeps the list's normal timeout, so a slow machine can never cancel one of them first
and answer the 503 before the Board exists.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

import pytest
from sqlalchemy import event, text

from app.services.ml_daily_metrics import board
from app.services.ml_publications.view import metrics_sort, status_block
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import URL, VER, seed_rows
from tests.routers.test_ml_publications_view_kpis import METRICAS, _seller, fill, pg, sell, view_pg  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

# Every temporary table named like the Board's MLA set, in ANY session (the catalog lists them all).
LEFTOVER_MLA_SETS = text("SELECT count(*) FROM pg_class WHERE relname = :name AND relpersistence = 't'")
# Only the slowed ranking statement carries this; the timeout is armed right before it, in its own transaction.
SLOW_MARKER = "pg_sleep(1)"


@pytest.fixture()
def ranked(pg):
    seed_rows(pg, fill)
    sell(pg, (1, [("MLA2", None, 4)]), (2, [("MLA1", None, 1)]), accredited=seed.real_hours_ago(1))
    return pg


def leftover_mla_sets(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(LEFTOVER_MLA_SETS, {"name": board.MLA_SET_TABLE}).scalar_one()


def test_a_timeout_while_ranking_the_whole_set_is_a_503_and_leaves_no_mla_set(
    client, ranked, db, rol_admin, admin_auth_headers, monkeypatch
) -> None:
    grant(db, rol_admin, VER, METRICAS)
    real = metrics_sort.select
    reached: list[bool] = []

    armed: list[bool] = []

    def slow(*columns):
        # Only the ranking statement is built here, once the Board has materialized the MLA set.
        reached.append(True)
        return real(*columns).where(text(f"(SELECT 1 FROM {SLOW_MARKER}) = 1"))

    def arm_timeout_at_the_ranking(conn, cursor, statement, parameters, context, executemany):
        # Same transaction as the ranking statement, so the `SET LOCAL` dies with its rollback.
        if SLOW_MARKER in statement:
            armed.append(True)
            cursor.execute("SET LOCAL statement_timeout = '50ms'")

    monkeypatch.setattr(metrics_sort, "select", slow)
    event.listen(ranked, "before_cursor_execute", arm_timeout_at_the_ranking)
    try:
        response = client.get(URL, headers=admin_auth_headers, params={"orden": "facturado_30d"})
    finally:
        event.remove(ranked, "before_cursor_execute", arm_timeout_at_the_ranking)

    assert reached, "the ranking statement was never built: the timeout did not happen inside the Board"
    assert armed == [True], "the timeout was not armed exactly once, at the ranking statement"
    assert leftover_mla_sets(ranked) == 0  # first: the cleanup holds whatever the answer
    assert ranked.pool.checkedout() == 0
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "consulta_lenta"

    monkeypatch.setattr(metrics_sort, "select", real)  # the next request is served normally
    status_block.REPORT.reset()
    again = client.get(URL, headers=admin_auth_headers, params={"orden": "facturado_30d"})
    assert again.status_code == 200, again.text
    assert [item["item_id"] for item in again.json()["items"]][:2] == ["MLA2", "MLA1"]
    assert leftover_mla_sets(ranked) == 0
