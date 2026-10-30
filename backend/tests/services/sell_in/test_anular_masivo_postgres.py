"""Bulk void of purchases on a real Postgres: every purchase goes through the single void, and the per-product
advisory locks its recomputes take are taken up front, in item_id order, so a bulk void never deadlocks a drain or
another bulk void that touches the same products in another order."""

from __future__ import annotations

from typing import Iterator

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import sessionmaker

from app.models.sell_in import SellInCompra, SellInCompraItem
from app.services.sell_in import anular_masivo, compras
from tests.services.sell_in import _world as w

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_in_anular_masivo") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _compra_de(engine: Engine, lineas) -> int:
    (linea, *_) = w.compra(engine, lineas)
    with sessionmaker(bind=engine)() as db:
        return db.get(SellInCompraItem, linea).compra_id


def _anular(db, ids):
    return anular_masivo.anular_varios(
        db,
        ids,
        lambda compra_id: compras._anular_compra(db, compra_id, 7, None, es_masivo=True),
        ya_anulada=compras.SellInYaAnulada,
        rechazos=(compras.SellInGenerada,),
        no_existe=lambda compra_id: f"La compra {compra_id} no existe",
        preparar=lambda: compras.bloquear_productos_de(db, ids),
    )


def test_the_locks_of_every_product_are_taken_first_in_item_id_order(engine):
    # Purchase A holds the higher item, B the lower one: one recompute per purchase alone would lock 2964 then 950.
    a = _compra_de(engine, [(2964, 2, "100.00")])
    b = _compra_de(engine, [(950, 2, "100.00"), (2270, 1, "50.00")])
    locks = []
    with sessionmaker(bind=engine)() as db:
        conn = db.connection()

        @event.listens_for(conn, "before_cursor_execute")
        def _capturar(_conn, _cursor, statement, parameters, _context, _many):
            if "pg_advisory_xact_lock" in statement:
                locks.append(list(parameters["ids"]))

        assert _anular(db, [a, b]) == ([a, b], [])

    assert locks[0] == [950, 2270, 2964]
    with sessionmaker(bind=engine)() as db:
        assert {db.get(SellInCompra, x).estado for x in (a, b)} == {"anulada"}
