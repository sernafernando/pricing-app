"""Costo SI reads no load waiting for approval (tacticals approval S2/S6): a pending brand bonus or Compras sell in is
not a sell in of the product, and approving it queues the product from its date (the existing triggers on any
UPDATE), so the drain recomputes it with its backup. Invented data."""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.services.costo_si import fuentes
from tests.services.costo_si import _world as w

pytestmark = pytest.mark.postgres

P = 5101


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("costo_si_aprob") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _leer(engine: Engine):
    with sessionmaker(bind=engine)() as db:
        return [b.id for b in fuentes.bonos_de(db, P)], [s.id for s in fuentes.sell_ins_compras(db, P)]


def test_a_pending_bonus_or_purchase_is_no_sell_in_until_approved(engine: Engine) -> None:
    w.producto(engine, P)
    w.factura(engine, P, date(2026, 10, 5), datetime(2026, 10, 6), 10, "100", previo=0, supp_id=14, pedido=9)
    bono = w.bono_marca(engine, "3.6", date(2026, 10, 1), date(2026, 12, 31))
    compra = w.sell_in_compra(engine, P, 9, "5", date(2026, 10, 5))
    w.run(engine, "UPDATE sell_in_bonos_marca SET estado = 'pendiente' WHERE id = :b", b=bono)
    w.run(engine, "UPDATE sell_in_compras SET estado = 'pendiente' WHERE id = :c", c=compra)
    w.run(engine, "DELETE FROM costo_si_dirty")

    assert _leer(engine) == ([], [])

    w.run(engine, "UPDATE sell_in_bonos_marca SET estado = 'activa' WHERE id = :b", b=bono)
    w.run(engine, "UPDATE sell_in_compras SET estado = 'activa' WHERE id = :c", c=compra)

    assert _leer(engine) == ([bono], [compra])
    assert w.encolados(engine) == [(P, date(2026, 10, 1))]  # queued from the earliest date the approval moves
