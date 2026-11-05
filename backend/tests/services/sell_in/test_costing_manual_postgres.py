"""The `manual` cost mode on real tables (D6, handoffs `sell-in-costos-propuesta.md`): the recompute files a manual
block's consumptions under its mode row, signed; `vigentes` and the lot viewer tell the block as the next sale's
source, and the lots it replaced as replaced. Owner: "setear cantidad y costo a mano, por si un sell in quedó defazado
al stock actual y se quiere usar un costo a mano que sea el de reposición por ejemplo"."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.services.sell_in import visor_lotes
from app.services.sell_in.costing import get_costing
from tests.services.sell_in import _world as w

pytestmark = pytest.mark.postgres

OCT1, OCT2, OCT20, OCT25, OCT30 = (date(2026, 10, d) for d in (1, 2, 20, 25, 30))
NOV1, NOV2 = date(2026, 11, 1), date(2026, 11, 2)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_in_costing_manual") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _dos_lotes(engine: Engine) -> tuple[int, int]:
    """Product 950: 100 units at 10 (Oct 1) and 100 at 8 (Oct 2)."""
    (diez,) = w.compra(engine, [(950, 100, "1000.00")], OCT1)
    (ocho,) = w.compra(engine, [(950, 100, "800.00")], OCT2)
    return diez, ocho


def _manual(engine: Engine, costo_unit: str = "49990") -> int:
    """30 units typed at `costo_unit` from Oct 25, against 50 000 frozen."""
    return w.modo(engine, 950, "manual", OCT25, cantidad=30, costo_unit=costo_unit, costo_base_unit="50000")


def _recompute(engine: Engine):
    with sessionmaker(bind=engine, autoflush=False)() as db:
        result = get_costing().recompute(db, [950], isolate_failures=False)
        db.commit()
    return result


def _filas(engine: Engine) -> list[tuple]:
    """`(compra_item_id, modo_id, venta_ref, unidades, descuento_ars)` of every stored consumption."""
    with engine.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                text(
                    "SELECT compra_item_id, modo_id, venta_ref, unidades, descuento_ars FROM sell_in_consumos "
                    "ORDER BY venta_ref, compra_item_id NULLS FIRST"
                )
            )
        ]


def test_the_block_is_consumed_under_its_mode_row_and_earlier_sales_keep_fifo(engine: Engine) -> None:
    diez, _ = _dos_lotes(engine)
    antes = w.venta(engine, "fuera", 950, 50, OCT20)
    despues = w.venta(engine, "fuera", 950, 40, OCT30)
    modo_id = _manual(engine)

    _recompute(engine)

    assert _filas(engine) == [
        (diez, None, antes, 50, Decimal("500.00")),
        (None, modo_id, despues, 30, Decimal("300.00")),  # the other 10 units: the lots were replaced
    ]
    assert _recompute(engine).inserted == 0  # a re-run writes nothing


def test_a_typed_cost_above_the_frozen_one_is_stored_as_a_surcharge(engine: Engine) -> None:
    _dos_lotes(engine)
    venta = w.venta(engine, "fuera", 950, 3, OCT30)
    modo_id = _manual(engine, costo_unit="52000")

    _recompute(engine)

    assert _filas(engine) == [(None, modo_id, venta, 3, Decimal("-6000.00"))]


def test_the_next_sale_takes_the_block(engine: Engine) -> None:
    _dos_lotes(engine)
    w.venta(engine, "fuera", 950, 10, OCT30)
    modo_id = _manual(engine)
    _recompute(engine)

    with sessionmaker(bind=engine)() as db:
        vigente = get_costing().vigentes(db, [950], NOV1)[950]

    assert (vigente.compra_item_id, vigente.descuento_unit_ars, vigente.unidades_restantes, vigente.en_pool) == (
        -modo_id,
        Decimal("10.000000"),
        20,
        False,
    )


def test_the_viewer_lists_the_block_and_the_lots_it_replaced(engine: Engine) -> None:
    diez, ocho = _dos_lotes(engine)
    w.venta(engine, "fuera", 950, 50, OCT20)
    venta = w.venta(engine, "fuera", 950, 10, OCT30)
    modo_id = _manual(engine)
    _recompute(engine)

    with sessionmaker(bind=engine)() as db:
        visor = visor_lotes.lotes_de_producto(db, 950, NOV1)
        consumos, total = visor_lotes.consumos_de_lote(db, 950, -modo_id, page=1, page_size=20)

    filas = [(x.compra_item_id, x.manual, x.restantes, x.descuento_unit, x.estado) for x in visor.lotes]
    assert filas == [
        (diez, False, 50, Decimal("10.000000"), "reemplazado"),
        (ocho, False, 100, Decimal("8.000000"), "reemplazado"),
        (-modo_id, True, 20, Decimal("10.000000"), "vigente"),
    ]
    assert (visor.proxima.compra_item_id, visor.proxima.descuento_unit, visor.proxima.restantes) == (
        -modo_id,
        Decimal("10.000000"),
        20,
    )
    assert total == 1 and consumos[0].venta_ref == venta


def test_a_future_block_replaces_nothing_yet(engine: Engine) -> None:
    diez, _ = _dos_lotes(engine)
    modo_id = w.modo(engine, 950, "manual", NOV2, cantidad=30, costo_unit="49990", costo_base_unit="50000")

    with sessionmaker(bind=engine)() as db:
        visor = visor_lotes.lotes_de_producto(db, 950, NOV1)

    assert [(x.compra_item_id, x.estado) for x in visor.lotes] == [
        (diez, "vigente"),
        (visor.lotes[1].compra_item_id, "en_cola"),
        (-modo_id, "desde"),
    ]
