"""P9b.T1: the KPI strip of Publicaciones is Métricas' Board over the MLAs the filter selects (S31.1, S33.1, S35.1).

Real Postgres: the store tables and the Board's tables share one throwaway schema, as they share the database in
production. The assertions that matter: the strip equals what the Board itself reports for the same set of MLAs
and period, an empty selection is empty (never the whole store), the count is the selection's size, and nothing
about the caller's PM scope leaks in (this screen is a management tool over every publication).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import String, literal, select, text, union_all
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.services.ml_daily_metrics import board
from app.services.ml_publications.view import kpis
from app.services.ml_publications.view.filters import parse_filter
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_units_sold_postgres import order

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 30)
SOLD = datetime(2026, 9, 20, 15, tzinfo=timezone.utc)  # 12:00 in Buenos Aires
FIRST, LAST = TODAY - timedelta(days=29), TODAY


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


@pytest.fixture()
def store(mlpub_pg):  # noqa: F811
    from app.models.producto import ProductoERP

    ProductoERP.__table__.create(bind=mlpub_pg)
    seed.create_board_tables(mlpub_pg)
    with mlpub_pg.begin() as conn:
        seed.add_item(conn, "MLA1", status="active")
        seed.add_item(conn, "MLA2", status="active")
        seed.add_item(conn, "MLA3", status="paused")
        seed.add_item(conn, "MLA4", status="active")  # in the set, never sold
    session = sessionmaker(bind=mlpub_pg)()
    order(session, 1, [("MLA1", None, 2)], accredited=SOLD)
    order(session, 2, [("MLA2", 11, 3), ("MLA2", 12, 4)], accredited=SOLD)
    order(session, 3, [("MLA3", None, 100)], accredited=SOLD)  # sold, but filtered out below
    session.commit()
    session.close()
    factory = sessionmaker(bind=mlpub_pg)
    reader = factory()
    yield reader
    reader.rollback()
    reader.close()


def _mlas(*values: str):
    return union_all(*(select(literal(v, String).label("mla")) for v in values))


def _metricas(db: Session, *mlas: str):
    """What Métricas ML answers for exactly these MLAs: the Board, asked directly (publication view)."""
    f = board.BoardFilter(date_from=FIRST, date_to=LAST, group_by="publication", mla_source=_mlas(*mlas))
    with board.Board(db, f, scope_pairs=None) as b:
        return b.kpis()


def _strip(db: Session, **filters: str):
    return kpis.compute(db, parse_filter(**filters), FIRST, LAST, "periodo_anterior")


def test_the_strip_equals_metricas_for_the_same_set_and_period(store) -> None:
    got = _strip(store, estado="active")
    assert got.kpis == _metricas(store, "MLA1", "MLA2", "MLA4")
    assert got.kpis.units == 9  # MLA3's 100 are outside the set


def test_the_strip_follows_the_filter_not_the_store(store) -> None:
    assert _strip(store, estado="paused").kpis == _metricas(store, "MLA3")
    assert _strip(store, q="MLA1").kpis.units == 2


def test_an_empty_selection_is_empty_never_store_wide(store) -> None:
    got = _strip(store, q="no-such-publication")
    assert got.mla_count == 0
    assert (got.kpis.units, got.kpis.rows, got.kpis.gross) == (0, 0, 0)


def test_the_count_is_the_selection_not_the_publications_that_sold(store) -> None:
    got = _strip(store, estado="active")
    assert got.mla_count == 3  # MLA4 never sold and is counted
    assert got.kpis.with_sales == 2


def test_the_period_and_its_comparison_come_back_with_the_figures(store) -> None:
    got = kpis.compute(store, parse_filter(), FIRST, LAST, "anio_anterior")
    assert (got.prev_from, got.prev_to) == (date(2025, 9, 1), date(2025, 9, 30))
    assert kpis.compute(store, parse_filter(), FIRST, LAST, "periodo_anterior").prev_to == FIRST - timedelta(days=1)


def test_the_callers_pm_scope_is_not_applied(store, monkeypatch) -> None:
    seen: list = []
    real = board.Board.__init__

    def spy(self, db, f, *args, **kwargs):
        seen.append(kwargs.get("scope_pairs", "missing"))
        real(self, db, f, *args, **kwargs)

    monkeypatch.setattr(board.Board, "__init__", spy)
    _strip(store)
    assert seen == [None]


def test_the_set_is_gone_when_the_strip_is_done(store) -> None:
    _strip(store)
    probe = text(f"SELECT to_regclass('pg_temp.{board.MLA_SET_TABLE}') IS NULL")
    assert store.execute(probe).scalar() is True
