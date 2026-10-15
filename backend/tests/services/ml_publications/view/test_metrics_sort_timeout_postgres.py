"""Sorting the Publicaciones list by Métricas ML's figures ranks the WHOLE filtered set inside a Board: a statement
timeout there is the list's controlled 503 (`consulta_lenta`), and the Board's temporary MLA-set table does not
survive it -- on no connection, pooled or not.

Real Postgres through the router (the `SET LOCAL statement_timeout` and the 503 mapping are the router's): the
ranking statement is slowed past a tiny timeout, AFTER the Board has materialized its MLA set.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.services.ml_daily_metrics import board
from app.services.ml_publications.view import listing, metrics_sort, status_block
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import URL, VER, seed_rows
from tests.routers.test_ml_publications_view_kpis import METRICAS, _seller, fill, pg, sell, view_pg  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

# Every temporary table named like the Board's MLA set, in ANY session (the catalog lists them all).
LEFTOVER_MLA_SETS = text("SELECT count(*) FROM pg_class WHERE relname = :name AND relpersistence = 't'")


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

    def slow(*columns):
        # Only the ranking statement is built here, once the Board has materialized the MLA set.
        reached.append(True)
        return real(*columns).where(text("(SELECT 1 FROM pg_sleep(1)) = 1"))

    monkeypatch.setattr(listing, "STATEMENT_TIMEOUT", "50ms")
    monkeypatch.setattr(metrics_sort, "select", slow)
    response = client.get(URL, headers=admin_auth_headers, params={"orden": "facturado_30d"})

    assert reached, "the ranking statement was never built: the timeout did not happen inside the Board"
    assert leftover_mla_sets(ranked) == 0  # first: the cleanup holds whatever the answer
    assert ranked.pool.checkedout() == 0
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "consulta_lenta"

    monkeypatch.setattr(listing, "STATEMENT_TIMEOUT", "8s")
    monkeypatch.setattr(metrics_sort, "select", real)  # the next request is served normally
    status_block.REPORT.reset()
    again = client.get(URL, headers=admin_auth_headers, params={"orden": "facturado_30d"})
    assert again.status_code == 200, again.text
    assert [item["item_id"] for item in again.json()["items"]][:2] == ["MLA2", "MLA1"]
    assert leftover_mla_sets(ranked) == 0
