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
    members = _created(statements, "board_members_")
    assert members and all(" IN (SELECT " in s for s in members)


def _lines_read(session, **filters):
    """`(statement, rows)` of the request's `board_lines` CREATE: the rows it
    materialized say how many sold lines the request had to compute."""
    from sqlalchemy import event

    seen = {}

    def after(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("CREATE TEMPORARY TABLE board_lines"):
            seen["statement"], seen["rows"] = re.sub(r"\s+", " ", statement), cursor.rowcount

    connection = session.connection()
    event.listen(connection, "after_cursor_execute", after)
    try:
        response, _recorder, _ms = volume._request(session, limit=20, **filters)
    finally:
        event.remove(connection, "after_cursor_execute", after)
    return response, seen["statement"], seen["rows"]


@pytest.mark.postgres
@pytest.mark.parametrize(
    "filters",
    [
        {"q": "volumen 17"},
        {"scope_pairs": [("EPSON", "CAT0")]},
    ],
    ids=["search", "pm-scope"],
)
def test_a_request_wide_filter_bounds_the_groups_read_below_the_windows(world, filters) -> None:
    _full, plain_statement, plain_rows = _lines_read(world)
    response, statement, rows = _lines_read(world, **filters)

    assert response.rows
    assert "board_touched_groups" not in plain_statement
    # The semi-join is INSIDE the subquery that holds the windows, so the
    # per-order and per-group windows only ever see the touched groups.
    assert "board_touched_groups" in statement
    assert statement.index("board_touched_groups") < statement.index(") AS sold")
    assert rows * 4 < plain_rows, (rows, plain_rows)


@pytest.mark.postgres
def test_an_mla_restriction_bounds_the_groups_read_below_the_windows(world) -> None:
    from sqlalchemy import select

    from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado as Pub

    mlas = select(Pub.mlp_publicationID).where(Pub.mlp_id < 8000000 + 20)
    _full, _plain_statement, plain_rows = _lines_read(world)
    response, statement, rows = _lines_read(world, mla_source=mlas)

    assert response.rows
    assert statement.index("board_touched_groups") < statement.index(") AS sold")
    assert rows * 4 < plain_rows, (rows, plain_rows)


@pytest.mark.postgres
def test_a_search_too_broad_to_bound_the_read_pays_for_no_restriction(world) -> None:
    """ "a" matches almost every product: restricting the groups would touch
    nearly all of them after a costly semi-join (measured: +500 ms), so the
    base reads everything, as it does without a search."""
    _response, statement, rows = _lines_read(world, q="a")
    _plain, plain_statement, plain_rows = _lines_read(world)

    assert "board_touched_groups" not in statement
    assert rows == plain_rows


@pytest.mark.postgres
def test_a_publication_row_without_an_mla_does_not_break_the_search(world) -> None:
    """`mlp_publicationid` is nullable. A matching title on such a row must not
    reach the lookup of candidate MLAs (a NULL cannot be sorted or probed)."""
    from sqlalchemy import text

    nested = world.begin_nested()
    try:
        world.execute(
            text(
                "INSERT INTO tb_mercadolibre_items_publicados (mlp_id, mlp_publicationid, item_id, mlp_itemtitle) "
                "VALUES (9999998, NULL, 800001, 'Publicación volumen 17 sin MLA'), "
                "(9999999, 'MLA77000001', 800001, 'Publicación volumen 17 con MLA')"
            )
        )
        response, _recorder, _ms = volume._request(world, limit=20, q="volumen 17")
        assert response.rows
    finally:
        nested.rollback()
