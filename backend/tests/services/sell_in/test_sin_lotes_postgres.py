"""T5 (sell-in-costo-si) PR A: costo SI replaced the FIFO lots (S14), so loading, voiding or re-splitting a Compras
sell in no longer allocates sales to lots: the stored consumptions stay as they were (frozen for the archive)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.models.sell_in import SellInCompra
from app.schemas.sell_in import SellInCompraCreate, SellInLineaIn
from app.services.sell_in import compras
from app.services.sell_in.costing import get_costing
from tests.services.sell_in import _world as w

D = date


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_in_sin_lotes") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


@pytest.mark.postgres
def test_loading_a_purchase_allocates_no_sale_to_a_lot(engine: Engine) -> None:
    w.venta(engine, "fuera", 2964, 2, D(2026, 10, 3))
    data = SellInCompraCreate(
        moneda="ARS",
        monto_total=Decimal("100.00"),
        formula="por_unidad",
        fecha_compra=D(2026, 10, 1),
        lineas=[SellInLineaIn(item_id=2964, cantidad=4, costo_base_unit=Decimal("1000"))],
    )

    with sessionmaker(bind=engine)() as db:
        compras.crear_compra(db, data, usuario_id=7)

    assert w.consumos(engine) == []


@pytest.mark.postgres
def test_voiding_a_purchase_leaves_the_stored_consumptions_frozen(engine: Engine) -> None:
    [anulada] = w.compra(engine, [(2964, 2, "20.00")], D(2026, 10, 1))
    w.compra(engine, [(2964, 5, "500.00")], D(2026, 10, 2))
    ref = w.venta(engine, "fuera", 2964, 2, D(2026, 10, 3))
    with sessionmaker(bind=engine)() as db:  # what FIFO stored before T5
        get_costing().recompute(db, [2964])
        db.commit()
    antes = w.consumos(engine)
    assert [c[:3] for c in antes] == [(anulada, "fuera", ref)]

    with sessionmaker(bind=engine)() as db:
        compra_id = db.query(SellInCompra.id).order_by(SellInCompra.id).first()[0]
        compras.anular_compra(db, compra_id, usuario_id=7, motivo="error de carga")

    assert w.consumos(engine) == antes
