"""The Sell in "Productos" list against real tables: one row per product whose active purchase lines still have
units, with the cost mode governing today (none: FIFO), the units left, what the next sale takes per unit (the lot
viewer's value, `costing.vigentes`) and the latest purchase date. Read in a fixed number of queries, never one per
product."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import sessionmaker

from app.services.sell_in import productos_costo, visor_lotes
from app.services.sell_in.costing import get_costing
from tests.services.sell_in import _world as w

pytestmark = pytest.mark.postgres

HOY = date(2026, 10, 20)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_in_productos_costo") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _mundo(engine: Engine) -> None:
    """950: FIFO, a used-up line, the current one and one counting from a future date. 2964: weighted since 10/10.
    2270: its only line used up and a manual block starting after today (still FIFO today)."""
    w.compra(engine, [(950, 2, "200.00")], date(2026, 10, 1))
    w.compra(engine, [(950, 3, "90.00")], date(2026, 10, 5))
    w.compra(engine, [(950, 5, "50.00")], date(2026, 10, 2), cuenta_desde="ingreso", fecha_ingreso=date(2026, 11, 3))
    w.compra(engine, [(2964, 4, "40.00")], date(2026, 10, 1))
    w.compra(engine, [(2964, 2, "100.00")], date(2026, 10, 9))
    w.modo(engine, 2964, "ponderado", date(2026, 10, 10))
    w.compra(engine, [(2270, 1, "10.00")], date(2026, 10, 3))
    w.modo(engine, 2270, "manual", date(2026, 10, 25), cantidad=1, costo_unit="5", costo_base_unit="5")
    w.venta(engine, "fuera", 950, 3, date(2026, 10, 6))
    w.venta(engine, "fuera", 2270, 1, date(2026, 10, 6))
    with sessionmaker(bind=engine)() as db:
        get_costing().recompute(db, [950, 2964, 2270])
        db.commit()


def test_one_row_per_product_with_units_left_and_its_mode_units_next_sale_and_last_purchase(engine: Engine) -> None:
    _mundo(engine)

    with sessionmaker(bind=engine)() as db:
        filas = productos_costo.productos(db, HOY)
        proxima_950 = visor_lotes.lotes_de_producto(db, 950, HOY).proxima
        proxima_2964 = visor_lotes.lotes_de_producto(db, 2964, HOY).proxima

    # 2270's only line is used up; its manual block counts from 10/25 with its typed unit.
    assert [(x.item_id, x.codigo, x.modo, x.unidades, x.ultima_compra) for x in filas] == [
        (2270, "C2270", None, 1, date(2026, 10, 25)),
        (2964, "C2964", "ponderado", 6, date(2026, 10, 9)),
        (950, "C950", None, 7, date(2026, 11, 3)),
    ]  # same description: by code
    # The same value the lot viewer shows for the next sale: the FIFO line's own, the weighted pool's.
    assert filas[2].sell_in_unit == proxima_950.descuento_unit == Decimal("30.000000")
    assert filas[1].sell_in_unit == proxima_2964.descuento_unit
    assert filas[1].descripcion == "Producto"


def test_no_products_answers_an_empty_list(engine: Engine) -> None:
    with sessionmaker(bind=engine)() as db:
        assert productos_costo.productos(db, HOY) == []


def test_the_query_count_does_not_grow_with_the_products(engine: Engine) -> None:
    def contar(n: int) -> int:
        for i in range(n):
            w.compra(engine, [(950 if i % 2 else 2964, 1, "10.00")], date(2026, 10, 1 + i))
        consultas = []

        def antes(*_args) -> None:
            consultas.append(1)

        event.listen(engine, "before_cursor_execute", antes)
        try:
            with sessionmaker(bind=engine)() as db:
                productos_costo.productos(db, HOY)
        finally:
            event.remove(engine, "before_cursor_execute", antes)
        w.clean(engine)
        return len(consultas)

    w.modo(engine, 2964, "ponderado", date(2026, 10, 1))
    pocas = contar(2)
    w.modo(engine, 2964, "ponderado", date(2026, 10, 1))
    assert contar(6) == pocas


def test_a_manual_block_counts_its_own_units_not_the_ones_it_replaced(engine: Engine) -> None:
    # 100 + 100 bought, 50 sold, then 30 typed by hand: the product has 30 left, as the lot viewer says.
    w.compra(engine, [(950, 100, "1000.00")], date(2026, 10, 1))
    w.compra(engine, [(950, 100, "800.00")], date(2026, 10, 2))
    w.venta(engine, "fuera", 950, 50, date(2026, 10, 5))
    w.modo(engine, 950, "manual", date(2026, 10, 10), cantidad=30, costo_unit="49990", costo_base_unit="50000")
    with sessionmaker(bind=engine)() as db:
        get_costing().recompute(db, [950])
        db.commit()

    with sessionmaker(bind=engine)() as db:
        (fila,) = productos_costo.productos(db, HOY)
        visor = visor_lotes.lotes_de_producto(db, 950, HOY)

    assert (fila.modo, fila.unidades) == ("manual", 30)
    assert fila.unidades == sum(x.restantes for x in visor.lotes)
