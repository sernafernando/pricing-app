"""Structure of the board's SQL on Postgres (perf work): what a request
computes ONCE and what it reads many times. Statement shapes, never timings
(a wall-clock bound would be flaky); the numbers themselves are pinned by
`test_board_characterization_postgres.py`.

Measured on production-like volume: every chip count, the KPI totals, the page
and the group views re-aggregated the whole pair table (11 aggregations of
25.000 pairs per request), `ANALYZE` read the statistics of every wide display
column (255 ms for one temp table), and the KPI series joined a keys CTE to the
pairs AFTER the fact (a nested loop over millions of comparisons).
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.ml_daily_metrics import board
from tests.services.ml_daily_metrics import test_board_volume_postgres as volume

SCALE = volume.Scale(products=200, publications=600, groups=4000, dense=1500)


@pytest.fixture(scope="module")
def world(board_pg_engine):
    connection = board_pg_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    volume._seed(session, SCALE)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(autouse=True)
def _frozen_world(monkeypatch):
    monkeypatch.setattr(board, "now_utc", lambda: volume.NOW)
    monkeypatch.setattr(settings, "ML_USER_ID", 999)


def _statements(session, **filters):
    response, recorder, _ms = volume._request(session, limit=20, **filters)
    assert response.rows
    return [re.sub(r"\s+", " ", sql) for sql, _params in recorder.statements]


def _created(statements, prefix: str):
    return [s for s in statements if s.startswith(f"CREATE TEMPORARY TABLE {prefix}")]


@pytest.mark.postgres
def test_the_rows_are_aggregated_once_for_an_unfiltered_request(world) -> None:
    statements = _statements(world)

    # The rows aggregate is the only statement counting a row's distinct MLAs.
    assert sum("count(distinct(fp.mla))" in s for s in statements) == 1
    assert len(_created(statements, "board_rows_")) == 1
    assert len(_created(statements, "board_members_")) == 1


@pytest.mark.postgres
def test_an_axis_without_a_filter_shares_the_tables_of_the_unfiltered_read(world) -> None:
    # Row filters (stock, ageing, solo con ventas) are WHEREs on the rows table.
    by_rows = _statements(world, stock=("sin_stock",), ageing=("up_to_30",), solo_con_ventas=True)
    assert len(_created(by_rows, "board_rows_")) == 1

    # A store filter makes "stores" a different read of the pairs: one more table of each.
    by_store = _statements(world, stores=("2645",))
    assert len(_created(by_store, "board_rows_")) == 2
    assert len(_created(by_store, "board_members_")) == 2

    # Search, an MLA restriction... apply to every axis: still the one read.
    assert len(_created(_statements(world, q="volumen"), "board_rows_")) == 1


@pytest.mark.postgres
def test_analyze_reads_only_the_columns_the_statements_filter_or_join_on(world) -> None:
    analyzed = [s for s in _statements(world) if s.startswith("ANALYZE")]

    assert analyzed
    assert all(re.fullmatch(r"ANALYZE \w+ \([\w, ]+\)", s) for s in analyzed), analyzed


@pytest.mark.postgres
def test_the_surviving_keys_are_a_semi_join_inside_the_pairs_not_a_cte_joined_after(world) -> None:
    statements = _statements(world, marcas=("Samsung",))

    assert not any(re.search(r"\bkeys_\w+ AS", s) for s in statements)
    assert not any("keys_" in s for s in statements)
