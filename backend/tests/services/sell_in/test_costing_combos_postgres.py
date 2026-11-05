"""A combo's sale consumes the sell-in lots of each component (owner, 2026-11-05: "El combo consume los lotes de sell
in de cada componente"): `qty x cantidad` units under the component's item_id, with the sale's own `venta_ref`, on
every channel; a return gives them back; the combo is never counted as its own item; the drain recomputes the
components of a queued combo line; and with the bill of materials unsynced the FIFO refuses."""

from __future__ import annotations

from datetime import date
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.services.combos import store
from app.services.combos.componentes import CombosNoSincronizados
from app.services.combos.reconcile import plan_combo
from app.services.sell import queue
from app.services.sell_in.costing import get_costing
from tests.services.sell._schema import SEMILLA_COMBOS
from tests.services.sell_in import _world as w

pytestmark = pytest.mark.postgres

NOTEBOOK, WH, COMBO = 950, 2964, 2270


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_in_costing_combos") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _recompute(engine: Engine, ids) -> None:
    with sessionmaker(bind=engine)() as db:
        result = get_costing().recompute(db, ids, isolate_failures=False)
        db.commit()
    assert not result.failed


def _mundo(engine: Engine) -> dict[str, int]:
    """The combo is one notebook plus two WH units; the notebook and the WH have lots, and so does the combo itself."""
    w.combo(engine, COMBO, {NOTEBOOK: 1, WH: 2})
    (notebook,) = w.compra(engine, [(NOTEBOOK, 3, "30.00")], date(2026, 10, 1))
    (wh,) = w.compra(engine, [(WH, 4, "40.00")], date(2026, 10, 1))
    (propio,) = w.compra(engine, [(COMBO, 5, "50.00")], date(2026, 10, 1))
    return {"notebook": notebook, "wh": wh, "propio": propio}


@pytest.mark.parametrize("canal", ["fuera", "tn", "ml"])
def test_a_combo_sale_takes_each_components_units_under_the_component(engine: Engine, canal: str) -> None:
    lineas = _mundo(engine)
    ref = w.venta(engine, canal, COMBO, 1, date(2026, 10, 6))

    _recompute(engine, [NOTEBOOK, WH, COMBO])

    assert [(x[0], x[1], x[2], x[3], x[4]) for x in w.consumos(engine)] == [
        (lineas["notebook"], canal, ref, NOTEBOOK, 1),
        (lineas["wh"], canal, ref, WH, 2),
    ]  # and nothing from the combo's own lot: never counted twice


def test_a_combo_sale_and_a_plain_sale_share_the_components_fifo(engine: Engine) -> None:
    lineas = _mundo(engine)
    combo = w.venta(engine, "fuera", COMBO, 2, date(2026, 10, 6))
    suelta = w.venta(engine, "fuera", NOTEBOOK, 2, date(2026, 10, 7))

    _recompute(engine, [NOTEBOOK, WH])

    assert [(x[2], x[3], x[4]) for x in w.consumos(engine)] == [
        (combo, NOTEBOOK, 2),
        (suelta, NOTEBOOK, 1),
        (combo, WH, 4),
    ]
    assert {x[0] for x in w.consumos(engine)} == {lineas["notebook"], lineas["wh"]}


def test_a_combo_return_gives_the_components_units_back(engine: Engine) -> None:
    _mundo(engine)
    w.venta(engine, "fuera", COMBO, 1, date(2026, 10, 6))
    w.venta(engine, "fuera", COMBO, 1, date(2026, 10, 8), signo=-1)

    _recompute(engine, [NOTEBOOK, WH])

    assert w.consumos(engine) == []


def test_the_drain_recomputes_the_components_of_a_queued_combo_line(engine: Engine) -> None:
    _mundo(engine)
    ref = w.venta(engine, "fuera", COMBO, 1, date(2026, 10, 6))

    with sessionmaker(bind=engine)() as db:
        productos = queue.products_of(db, [("fuera", ref, COMBO)])

    assert productos == {("fuera", ref): {COMBO, NOTEBOOK, WH}}


def test_an_unsynced_bill_of_materials_is_refused_not_counted_as_the_combos_own_sale(engine: Engine) -> None:
    _mundo(engine)
    w.venta(engine, "fuera", COMBO, 1, date(2026, 10, 6))
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM combo_componentes"))
    try:
        with sessionmaker(bind=engine)() as db, pytest.raises(CombosNoSincronizados):
            get_costing().recompute(db, [COMBO], isolate_failures=False)
        assert w.consumos(engine) == []
    finally:
        with engine.begin() as conn:
            conn.execute(text(SEMILLA_COMBOS))


def _queued_items(engine: Engine) -> list:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text("SELECT canal, venta_ref, item_id FROM sell_dirty ORDER BY 1, 2"))]


def test_a_bill_of_materials_change_requeues_every_sale_of_the_combo(engine: Engine) -> None:
    """S4: the drain then recomputes the new components, the old ones (their rows are filed under them) and the
    sell-out campaigns of both."""
    w.combo(engine, COMBO, {NOTEBOOK: 1, WH: 2})
    fuera = w.venta(engine, "fuera", COMBO, 1, date(2026, 10, 6))
    ml = w.venta(engine, "ml", COMBO, 1, date(2026, 10, 7))
    w.venta(engine, "fuera", NOTEBOOK, 1, date(2026, 10, 8))  # not a sale of the combo
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM sell_dirty"))

    with sessionmaker(bind=engine)() as db:
        store.apply(db, plan_combo(COMBO, {NOTEBOOK: 1}, store.load_combo(db, COMBO)))
        db.commit()

    assert _queued_items(engine) == [("fuera", fuera, COMBO), ("ml", ml, COMBO)]


def test_an_empty_plan_queues_nothing(engine: Engine) -> None:
    w.combo(engine, COMBO, {NOTEBOOK: 1, WH: 2})
    w.venta(engine, "fuera", COMBO, 1, date(2026, 10, 6))
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM sell_dirty"))

    with sessionmaker(bind=engine)() as db:
        store.apply(db, plan_combo(COMBO, {NOTEBOOK: 1, WH: 2}, store.load_combo(db, COMBO)))
        db.commit()

    assert _queued_items(engine) == []
