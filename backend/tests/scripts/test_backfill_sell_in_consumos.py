"""`backfill_sell_in_consumos` (sell-in-sell-out T5): brings every product that
has sell-in lines or stored consumptions up to date, in batches. It covers what
the inert drain (T4) acked without computing.

Postgres only (the recompute takes advisory locks). Throwaway schema.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.scripts.backfill_sell_in_consumos import _build_parser, run_backfill
from app.services.sell_in import costing
from tests.services.sell_in import _world as w

D = date


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_in_backfill") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _run(engine: Engine, **kwargs) -> dict:
    return run_backfill(session_factory=sessionmaker(bind=engine), **kwargs)


def _seed(engine: Engine) -> tuple:
    [a] = w.compra(engine, [(2964, 2, "20.00")])
    [b] = w.compra(engine, [(2270, 2, "40.00")])
    va = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2))
    vb = w.venta(engine, "ml", 2270, 3, D(2026, 10, 2))
    return a, b, va, vb


@pytest.mark.postgres
class TestBackfill:
    def test_it_allocates_every_product_with_sell_in_and_a_rerun_writes_nothing(self, engine: Engine) -> None:
        a, b, va, vb = _seed(engine)
        w.venta(engine, "tn", 950, 1, D(2026, 10, 2))  # no sell in: not a candidate

        first = _run(engine, limit=None, dry_run=False, batch_size=1)
        again = _run(engine, limit=None, dry_run=False, batch_size=1)

        assert w.consumos(engine) == [
            (a, "fuera", va, 2964, 1, Decimal("10.00")),
            (b, "ml", vb, 2270, 2, Decimal("40.00")),
        ]
        assert (first["products"], first["batches"], first["inserted"], first["failed"]) == (2, 2, 2, 0)
        assert (again["products"], again["inserted"], again["deleted"]) == (2, 0, 0)

    def test_a_dry_run_counts_but_writes_nothing(self, engine: Engine) -> None:
        _seed(engine)

        summary = _run(engine, limit=None, dry_run=True)

        assert summary["dry_run"] is True and summary["inserted"] == 2
        assert w.consumos(engine) == []

    def test_limit_caps_the_products_and_the_last_item_resumes(self, engine: Engine) -> None:
        _seed(engine)

        first = _run(engine, limit=1, dry_run=False)
        rest = _run(engine, limit=None, dry_run=False, after_item=first["last_item_id"])

        assert (first["products"], first["last_item_id"]) == (1, 2270)
        assert (rest["products"], rest["last_item_id"]) == (1, 2964)
        assert len(w.consumos(engine)) == 2

    def test_stale_consumptions_of_a_voided_purchase_are_released(self, engine: Engine) -> None:
        _seed(engine)
        _run(engine, limit=None, dry_run=False)
        with engine.begin() as conn:
            conn.execute(text("UPDATE sell_in_compras SET estado = 'anulada'"))

        summary = _run(engine, limit=None, dry_run=False)

        assert summary["deleted"] == 2
        assert w.consumos(engine) == []

    def test_a_failed_product_is_listed_in_the_summary_and_can_be_rerun_alone(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        a, b, va, vb = _seed(engine)
        escribir = costing.FifoPurchaseCosting._escribir

        def _falla(db, item_id, deseados, guardados):
            if item_id == 2270:
                raise RuntimeError("boom")
            return escribir(db, item_id, deseados, guardados)

        monkeypatch.setattr(costing.FifoPurchaseCosting, "_escribir", staticmethod(_falla))
        first = _run(engine, limit=None, dry_run=False)
        assert (first["failed"], first["failed_items"], first["last_item_id"]) == (1, [2270], 2964)
        assert w.consumos(engine) == [(a, "fuera", va, 2964, 1, Decimal("10.00"))]
        monkeypatch.undo()

        retry = _run(engine, limit=None, dry_run=False, items=first["failed_items"])

        assert (retry["products"], retry["inserted"], retry["failed"], retry["failed_items"]) == (1, 1, 0, [])
        assert w.consumos(engine) == [
            (a, "fuera", va, 2964, 1, Decimal("10.00")),
            (b, "ml", vb, 2270, 2, Decimal("40.00")),
        ]

    def test_a_failed_batch_lists_its_products_and_the_run_goes_on(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        a, b, va, vb = _seed(engine)
        guardados = costing.FifoPurchaseCosting._guardados

        def _falla(db, ids):
            # A shared batch read fails outside the per-product savepoint.
            if 2270 in ids:
                raise RuntimeError("statement timeout")
            return guardados(db, ids)

        monkeypatch.setattr(costing.FifoPurchaseCosting, "_guardados", staticmethod(_falla))
        summary = _run(engine, limit=None, dry_run=False, batch_size=1)

        assert (summary["products"], summary["failed"], summary["failed_items"]) == (2, 1, [2270])
        assert summary["last_item_id"] == 2964
        assert w.consumos(engine) == [(a, "fuera", va, 2964, 1, Decimal("10.00"))]

    def test_items_runs_exactly_the_given_products_in_batches(self, engine: Engine) -> None:
        a, b, va, vb = _seed(engine)

        summary = _run(engine, limit=None, dry_run=False, batch_size=1, items=[2964, 2964])

        assert (summary["products"], summary["batches"], summary["inserted"]) == (1, 1, 1)
        assert w.consumos(engine) == [(a, "fuera", va, 2964, 1, Decimal("10.00"))]


class TestParser:
    def test_items_takes_a_csv_of_item_ids(self) -> None:
        assert _build_parser().parse_args(["--items", "2964, 2270"]).items == [2270, 2964]

    def test_items_rejects_a_non_numeric_id(self) -> None:
        with pytest.raises(SystemExit):
            _build_parser().parse_args(["--items", "2964,abc"])
