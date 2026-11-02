"""The costing replays a product's dated cost modes (`sell_in_modos_producto`) against real tables: the stored
consumptions follow `fifo.asignar` with the modes as periods, sales before a mode keep their rows untouched, and
`vigentes` (what the next sale gets) follows the mode governing the day. Owner: "si compro 100 unidades a 10 y 100 a
8, ponderar eso en 200 a 9"; "que el costo sea el del último también combinando las cantidades"."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.services.sell_in.costing import get_costing
from tests.services.sell_in import _world as w

pytestmark = pytest.mark.postgres

OCT20, OCT25, NOV1, NOV2 = date(2026, 10, 20), date(2026, 10, 25), date(2026, 11, 1), date(2026, 11, 2)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_in_costing_modos") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _dos_lotes(engine: Engine) -> tuple[int, int]:
    """Product 950: 100 units at 10 (Oct 1) and 100 at 8 (Oct 2)."""
    (diez,) = w.compra(engine, [(950, 100, "1000.00")], date(2026, 10, 1))
    (ocho,) = w.compra(engine, [(950, 100, "800.00")], date(2026, 10, 2))
    return diez, ocho


def _recompute(engine: Engine):
    with sessionmaker(bind=engine, autoflush=False)() as db:
        result = get_costing().recompute(db, [950])
        db.commit()
    return result


def _por_venta(engine: Engine) -> dict[int, list[tuple[int, int, Decimal]]]:
    salida: dict[int, list[tuple[int, int, Decimal]]] = {}
    for linea, _canal, ref, _item, unidades, descuento in w.consumos(engine):
        salida.setdefault(ref, []).append((linea, unidades, descuento))
    return salida


def test_a_weighted_mode_values_the_units_left_at_one_weighted_value(engine: Engine) -> None:
    diez, _ = _dos_lotes(engine)
    antes = w.venta(engine, "fuera", 950, 50, OCT20)
    despues = w.venta(engine, "fuera", 950, 50, NOV2)
    w.modo(engine, 950, "ponderado", NOV2)

    _recompute(engine)

    consumos = _por_venta(engine)
    assert consumos[antes] == [(diez, 50, Decimal("500.00"))]
    # Left on Nov 2: 50 at 10 and 100 at 8, 1300 over 150 units.
    assert consumos[despues] == [(diez, 50, Decimal("433.33"))]
    assert _recompute(engine).inserted == 0  # a re-run writes nothing


def test_a_mode_added_later_leaves_the_earlier_sales_rows_untouched(engine: Engine) -> None:
    _dos_lotes(engine)
    antes = w.venta(engine, "fuera", 950, 50, OCT20)
    w.venta(engine, "fuera", 950, 50, NOV2)
    _recompute(engine)
    filas_antes = [c for c in w.consumos(engine) if c[2] == antes]
    ids_antes = w.consumo_ids(engine)

    w.modo(engine, 950, "ultimo", OCT25)  # backdated before the second sale
    _recompute(engine)

    assert [c for c in w.consumos(engine) if c[2] == antes] == filas_antes
    assert w.consumo_ids(engine)[0] == ids_antes[0]  # the earlier sale's row was not rewritten


def test_last_price_values_every_unit_left_at_the_newest_lot(engine: Engine) -> None:
    _dos_lotes(engine)
    venta = w.venta(engine, "fuera", 950, 150, NOV2)
    w.modo(engine, 950, "ultimo", OCT20)

    _recompute(engine)

    assert sum(x[2] for x in _por_venta(engine)[venta]) == Decimal("1200.00")  # 150 at 8


def test_the_next_sale_gets_the_weighted_value_of_what_is_left(engine: Engine) -> None:
    _, ocho = _dos_lotes(engine)
    w.venta(engine, "fuera", 950, 100, OCT20)
    w.modo(engine, 950, "ponderado", date(2026, 10, 15))
    _recompute(engine)

    with sessionmaker(bind=engine)() as db:
        vigente = get_costing().vigentes(db, [950], NOV1)[950]

    # The pool handed 900 of its 1800 to the first 100 units (all from the lot at 10): 900 left over the 100 units of
    # the lot at 8, 9 each. The lot the units come from is still the FIFO one.
    assert (vigente.compra_item_id, vigente.descuento_unit_ars, vigente.unidades_restantes) == (
        ocho,
        Decimal("9.00"),
        100,
    )


def test_the_next_sale_under_last_price_gets_the_newest_lots_value_for_every_unit_left(engine: Engine) -> None:
    _dos_lotes(engine)
    w.venta(engine, "fuera", 950, 50, OCT20)
    w.modo(engine, 950, "ultimo", OCT25)
    _recompute(engine)

    with sessionmaker(bind=engine)() as db:
        vigente = get_costing().vigentes(db, [950], NOV1)[950]

    assert (vigente.descuento_unit_ars, vigente.unidades_restantes) == (Decimal("8.00"), 150)


def test_without_modes_the_next_sale_is_still_the_current_lot(engine: Engine) -> None:
    diez, _ = _dos_lotes(engine)
    w.venta(engine, "fuera", 950, 50, OCT20)
    _recompute(engine)

    with sessionmaker(bind=engine)() as db:
        vigente = get_costing().vigentes(db, [950], NOV1)[950]

    assert (vigente.compra_item_id, vigente.descuento_unit_ars, vigente.unidades_restantes) == (
        diez,
        Decimal("10.00"),
        50,
    )


def test_a_manual_block_is_not_applied_yet_and_fails_only_its_product(engine: Engine) -> None:
    _dos_lotes(engine)
    w.venta(engine, "fuera", 950, 50, OCT20)
    w.modo(engine, 950, "manual", OCT20, cantidad=30, costo_unit="52000", costo_base_unit="50000")

    result = _recompute(engine)

    assert list(result.failed) == [950]
    assert w.consumos(engine) == []


def test_the_lot_viewer_tells_the_same_next_sale_as_the_panels(engine: Engine) -> None:
    from app.services.sell_in import visor_lotes

    _, ocho = _dos_lotes(engine)
    w.venta(engine, "fuera", 950, 100, OCT20)
    w.modo(engine, 950, "ponderado", date(2026, 10, 15))
    _recompute(engine)

    with sessionmaker(bind=engine)() as db:
        proxima = visor_lotes.lotes_de_producto(db, 950, NOV1).proxima

    # Every unit left is in the weighted pool: no "after that" value of another lot.
    assert (proxima.compra_item_id, proxima.descuento_unit, proxima.restantes, proxima.siguiente) == (
        ocho,
        Decimal("9.00"),
        100,
        None,
    )


def test_a_manual_block_leaves_its_product_out_of_the_next_sale_without_breaking_the_others(engine: Engine) -> None:
    _dos_lotes(engine)
    (otra,) = w.compra(engine, [(2964, 10, "100.00")], date(2026, 10, 1))
    w.modo(engine, 950, "manual", OCT20, cantidad=30, costo_unit="52000", costo_base_unit="50000")

    with sessionmaker(bind=engine)() as db:
        vigentes = get_costing().vigentes(db, [950, 2964], NOV1)

    assert list(vigentes) == [2964] and vigentes[2964].compra_item_id == otra


def test_a_replay_that_breaks_skips_its_product_without_breaking_the_others(engine: Engine) -> None:
    # Another transaction can raise a line's consumed units between the two reads: the replay then fails on its maths.
    from sqlalchemy import text

    (diez,) = w.compra(engine, [(950, 10, "100.00")], date(2026, 10, 1))
    (otra,) = w.compra(engine, [(2964, 10, "100.00")], date(2026, 10, 1))
    w.modo(engine, 950, "ponderado", OCT20)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sell_in_consumos (compra_item_id, canal, venta_ref, item_id, fecha_venta, unidades, "
                "descuento_ars) VALUES (:l, 'fuera', :r, 950, :f, :u, :d)"
            ),
            [
                {"l": diez, "r": 1, "f": date(2026, 10, 5), "u": 10, "d": 100},
                {"l": diez, "r": 2, "f": OCT25, "u": 5, "d": 0},
            ],
        )

    with sessionmaker(bind=engine)() as db:
        vigentes = get_costing().vigentes(db, [950, 2964], NOV1)

    assert list(vigentes) == [2964] and vigentes[2964].compra_item_id == otra


def test_a_stored_row_of_another_products_line_skips_only_its_product(engine: Engine) -> None:
    # A line read mid-change can leave a stored row whose line is not among its product's lots.
    from sqlalchemy import text

    w.compra(engine, [(950, 10, "100.00")], date(2026, 10, 1))
    (otra,) = w.compra(engine, [(2964, 10, "100.00")], date(2026, 10, 1))
    w.modo(engine, 950, "ponderado", OCT20)
    w.modo(engine, 2964, "ponderado", OCT20)  # both products replay, so the row's line is read
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sell_in_consumos (compra_item_id, canal, venta_ref, item_id, fecha_venta, unidades, "
                "descuento_ars) VALUES (:l, 'fuera', 1, 950, :f, 1, 10)"
            ),
            {"l": otra, "f": OCT25},
        )

    with sessionmaker(bind=engine)() as db:
        vigentes = get_costing().vigentes(db, [950, 2964], NOV1)

    assert list(vigentes) == [2964] and vigentes[2964].compra_item_id == otra
