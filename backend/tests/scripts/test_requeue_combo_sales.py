"""`app.scripts.requeue_combo_sales`: after deploy, every sale of every combo goes into `sell_dirty` once, under the
combo, so the drain re-counts it for its components; with the bill of materials empty it refuses and queues nothing."""

from __future__ import annotations

import json
from datetime import date
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.scripts import requeue_combo_sales
from tests.services.sell._schema import SEMILLA_COMBOS
from tests.services.sell_in import _world as w

pytestmark = pytest.mark.postgres

NOTEBOOK, WH, COMBO = 950, 2964, 2270


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("requeue_combo_sales") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))
    yield
    w.clean(engine)


def _queued(engine: Engine) -> list:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text("SELECT canal, venta_ref, item_id FROM sell_dirty ORDER BY 1, 2"))]


def test_every_sale_of_every_combo_is_queued_under_the_combo(engine: Engine, capsys) -> None:
    w.combo(engine, COMBO, {NOTEBOOK: 1, WH: 2})
    fuera = w.venta(engine, "fuera", COMBO, 1, date(2026, 10, 6))
    tn = w.venta(engine, "tn", COMBO, 2, date(2026, 10, 7))
    ml = w.venta(engine, "ml", COMBO, 1, date(2026, 10, 8))
    w.venta(engine, "fuera", NOTEBOOK, 1, date(2026, 10, 9))  # a plain sale: not queued
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM sell_dirty"))

    assert requeue_combo_sales.main([]) == 0

    assert _queued(engine) == [("fuera", fuera, COMBO), ("ml", ml, COMBO), ("tn", tn, COMBO)]
    assert json.loads(capsys.readouterr().out) == {"combos": 2}  # and the seed combo, with no sales


def test_an_empty_bill_of_materials_is_refused_and_queues_nothing(engine: Engine, capsys) -> None:
    w.venta(engine, "fuera", COMBO, 1, date(2026, 10, 6))
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM sell_dirty"))
        conn.execute(text("DELETE FROM combo_componentes"))
    try:
        assert requeue_combo_sales.main([]) == 1
        assert _queued(engine) == []
        assert "combos.sync" in json.loads(capsys.readouterr().out)["error"]
    finally:
        with engine.begin() as conn:
            conn.execute(text(SEMILLA_COMBOS))
