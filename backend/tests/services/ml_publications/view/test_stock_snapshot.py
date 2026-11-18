"""The daily stock photo (auditoria-stock-rotacion L1): one row per product per day with its ERP and Full units, taken
by the existing worker, kept 400 days, and averaged over the last 30 days for the Auditoría's Rotación. Invented data
only; the world is the Auditoría's (`test_ml_publications_view_stock_audit.fill`)."""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.ml_publications.view import stock_snapshot
from tests.routers.test_ml_publications_view import seed_rows
from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401
from tests.routers.test_ml_publications_view_stock_audit import fill
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401

TODAY = date(2026, 11, 18)
ROWS = "SELECT fecha, item_id, stock_erp, stock_full FROM producto_stock_diario ORDER BY fecha, item_id"


def rows(engine) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(ROWS))]


def photo(engine, day: date, **stock: tuple[int, int]) -> None:
    """Rows of `day`: item -> (erp, full), keyed `p<item>`."""
    with engine.begin() as conn:
        for key, (erp, full) in stock.items():
            conn.execute(
                text("INSERT INTO producto_stock_diario VALUES (:f, :i, :e, :u)"),
                {"f": day, "i": int(key[1:]), "e": erp, "u": full},
            )


@pytest.fixture()
def world(pg):
    seed_rows(pg, fill)
    return pg


@pytest.mark.postgres
class TestTake:
    def test_one_row_per_product_with_stock_erp_and_full_apart(self, world) -> None:
        with Session(bind=world) as db:
            assert stock_snapshot.take(db, TODAY) == 7
            db.commit()
        # Full is each product's publications' user products counted once (UP10 is shared by MLA10 and MLA11), a
        # combo's in its own units; products without any stock get no row.
        assert rows(world) == [
            (TODAY, 100, 5, 2),
            (TODAY, 101, 3, 1),
            (TODAY, 110, 0, 3),
            (TODAY, 111, 100, 0),
            (TODAY, 120, 0, 4),
            (TODAY, 130, 1, 0),
            (TODAY, 140, 2, 0),
        ]

    def test_taking_the_day_again_replaces_it_and_leaves_other_days_alone(self, world) -> None:
        photo(world, TODAY - timedelta(days=1), p100=(9, 9))
        photo(world, TODAY, p150=(4, 0))  # 150 has no stock any more: today's photo drops it
        with world.begin() as conn:
            conn.execute(text("UPDATE productos_erp SET stock = 6 WHERE item_id = 100"))
        with Session(bind=world) as db:
            stock_snapshot.take(db, TODAY)
            stock_snapshot.take(db, TODAY)
            db.commit()
        today = [r for r in rows(world) if r[0] == TODAY]
        assert (TODAY, 100, 6, 2) in today and len(today) == 7
        assert not [r for r in today if r[1] == 150]
        assert (TODAY - timedelta(days=1), 100, 9, 9) in rows(world)


@pytest.mark.postgres
class TestPrune:
    def test_it_keeps_the_last_400_days(self, world) -> None:
        photo(world, TODAY - timedelta(days=399), p100=(1, 0))
        photo(world, TODAY - timedelta(days=400), p100=(2, 0))
        photo(world, TODAY - timedelta(days=500), p100=(3, 0))
        with Session(bind=world) as db:
            assert stock_snapshot.prune(db, TODAY) == 2
            db.commit()
        assert rows(world) == [(TODAY - timedelta(days=399), 100, 1, 0)]


@pytest.mark.postgres
class TestAverages:
    def test_the_average_of_the_days_photographed_in_the_last_30(self, world) -> None:
        photo(world, TODAY, p100=(4, 2), p101=(0, 1))
        photo(world, TODAY - timedelta(days=29), p100=(2, 0))  # 101 had nothing that day: it counts as 0
        photo(world, TODAY - timedelta(days=30), p100=(1000, 0), p140=(7, 0))  # out of the window
        with Session(bind=world) as db:
            found = stock_snapshot.averages(db, [100, 101, 140, 999], TODAY)
        assert found.dias == 2
        assert found.stock == {100: (3.0, 1.0), 101: (0.0, 0.5)}

    def test_without_a_photo_in_the_window_there_are_no_days(self, world) -> None:
        photo(world, TODAY - timedelta(days=31), p100=(4, 2))
        with Session(bind=world) as db:
            found = stock_snapshot.averages(db, [100], TODAY)
        assert (found.dias, found.stock) == (0, {})
