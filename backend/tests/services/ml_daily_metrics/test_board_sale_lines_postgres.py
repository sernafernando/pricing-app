"""The board reading the persisted sold lines (`ml_sale_lines`) behind
`METRICAS_SALE_LINES_ENABLED`.

- OFF (the default): the board is exactly as it was -- no statement mentions the
  table (the characterization digests and the SQL pin cover the rest).
- ON: every one of the characterization scenarios (rows, totals, KPIs, facets,
  series, sub-rows, group nodes) gives the SAME digests as the live computation,
  with the recompute queue applied at read time.
"""

from __future__ import annotations

import json
import re

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, settings
from app.models.ml_sale_line import MlSaleLine
from app.services.ml_daily_metrics import board
from app.services.ml_daily_metrics.sales import sale_lines
from app.services.order_metrics.sale_lines_store import COLUMNS
from tests.services.ml_daily_metrics import test_board_characterization_postgres as characterization
from tests.services.ml_daily_metrics import test_board_volume_postgres as volume


def populate_sale_lines(session) -> int:
    """Fills `ml_sale_lines` with what `sale_lines` derives (queue ignored) for the
    whole seeded world: the table the drain would have written."""
    lines = sale_lines(sqlite=False, queue=False, keyed=True)
    session.execute(insert(MlSaleLine.__table__).from_select(list(COLUMNS), select(*(lines.c[n] for n in COLUMNS))))
    return session.execute(text("SELECT count(*) FROM ml_sale_lines")).scalar()


@pytest.fixture(scope="module")
def world(board_pg_engine):
    connection = board_pg_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    volume._seed(session, characterization.SCALE)
    settings.ML_USER_ID = 999
    assert populate_sale_lines(session) > 1000
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(autouse=True)
def _frozen_world(monkeypatch):
    monkeypatch.setattr(board, "now_utc", lambda: volume.NOW)
    monkeypatch.setattr(settings, "ML_USER_ID", 999)


def test_the_flag_defaults_to_off_in_code(monkeypatch) -> None:
    monkeypatch.delenv("METRICAS_SALE_LINES_ENABLED", raising=False)

    assert Settings(_env_file=None).METRICAS_SALE_LINES_ENABLED is False


@pytest.mark.postgres
def test_every_characterization_scenario_gives_the_same_digests_with_the_lines_on(world, monkeypatch) -> None:
    monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", True)

    actual = characterization._compute(world)

    expected = json.loads(characterization.GOLDEN.read_text())
    changed = {
        f"{name}.{section}": (expected[name].get(section), digest)
        for name, sections in actual.items()
        for section, digest in sections.items()
        if expected[name].get(section) != digest
    }
    assert sorted(actual) == sorted(expected)
    assert not changed, f"board output changed with the lines ON (scenario.section -> (golden, actual)): {changed}"


def _statements(session, **filters):
    response, recorder, _ms = volume._request(session, limit=20, **filters)
    assert response.rows
    return [re.sub(r"\s+", " ", sql) for sql, _params in recorder.statements]


@pytest.mark.postgres
def test_with_the_flag_off_no_statement_touches_the_table(world, monkeypatch) -> None:
    monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", False)

    assert not any("ml_sale_lines" in s for s in _statements(world))


@pytest.mark.postgres
def test_with_the_flag_on_the_base_reads_the_table_without_windows_or_joins(world, monkeypatch) -> None:
    monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", True)

    statements = _statements(world)
    lines = next(s for s in statements if s.startswith("CREATE TEMPORARY TABLE board_lines"))
    pairs = next(s for s in statements if s.startswith("CREATE TEMPORARY TABLE board_pair_agg"))

    assert "ml_sale_lines" in lines and "ml_sale_lines" in pairs
    for table in ("ml_group_metrics", "ml_order_items_ops", "ml_order_item_costos", "ml_order_metrics "):
        assert table not in lines and table not in pairs
    # The orders table is only reached by the queue overlay (the groups of the queued orders).
    assert "ml_orders_ops" not in pairs
    assert "ml_order_metrics_dirty" in lines and "JOIN ml_orders_ops" not in lines
    assert " OVER (" not in lines


@pytest.mark.postgres
@pytest.mark.parametrize(
    "filters", [{"q": "volumen 17"}, {"scope_pairs": [("EPSON", "CAT0")]}], ids=["search", "scope"]
)
def test_with_the_flag_on_a_filter_needs_no_lookup_nor_touched_groups(world, monkeypatch, filters) -> None:
    """The lines are independent rows: the pair filters already bound the read."""
    monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", True)

    statements = _statements(world, **filters)

    assert not any("board_touched_groups" in s for s in statements)
    assert len(statements) == len(_statements(world))


@pytest.mark.postgres
def test_an_order_in_the_queue_has_no_money_and_holds_back_the_markup_of_its_group(world, monkeypatch) -> None:
    """The recompute queue is applied at read time, as the live derivation does."""
    monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", True)
    f = board.BoardFilter(date_from=volume.TODAY.replace(day=1), date_to=volume.TODAY, group_by="publication")
    order = world.execute(
        text(
            "SELECT l.order_id, l.group_key FROM ml_sale_lines l WHERE l.tg > 0 "
            "AND NOT EXISTS (SELECT 1 FROM ml_order_metrics_dirty d WHERE d.order_id = l.order_id) "
            "AND l.group_date >= :since ORDER BY l.order_id LIMIT 1"
        ),
        {"since": volume.NOW.replace(day=1)},
    ).one()

    def money():
        with board.Board(world, f, scope_pairs=None) as b:
            return sum(row.tg for row in b.page(None, with_series=False))

    before = money()
    nested = world.begin_nested()
    world.execute(
        text("INSERT INTO ml_order_metrics_dirty (order_id, version, reason) VALUES (:o, 1, 'x')"),
        {"o": order.order_id},
    )
    try:
        during = money()
    finally:
        nested.rollback()

    assert during < before
