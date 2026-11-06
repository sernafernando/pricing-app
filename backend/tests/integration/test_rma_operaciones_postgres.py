"""RMA "Para borrar" grouped by ML operation (owner, 2026-11-06):

> si pueden traer el número de envío de la operación de última se puede matchear con los registros de las operaciones
> nuestras que tenemos, y cuando es un mismo pedido agruparlo juntos, no mostrar dos líneas, si bien son 2 RMA serían
> una misma operación

`resolver_operaciones` reads a case's `ml_id` (free text: usually the ML order id the trace copied, but a user may
type the pack or the shipment number instead) against the stored ML order tables, the same match the ML trace does
(`QUERY_MLO_CANDIDATES_BY_INPUT`), in one batch. The header rows copy the shape of the captured sale in
`test_traza_ml_sin_pedido_erp_postgres.py` (ids replaced, the repository is public).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.mercadolibre_order_header import MercadoLibreOrderHeader
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.services.rma_operaciones import OperacionML, resolver_operaciones
from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

pytestmark = pytest.mark.postgres

_TABLES = ("tb_mercadolibre_orders_header", "tb_mercadolibre_orders_shipping")

PACK = "2000000000000001"
ORDEN_A = "2000000000000002"  # first article of the cart
ORDEN_B = "2000000000000003"  # second article, same pack, same shipment
ORDEN_SOLA = "2000000000000004"  # an order outside any pack
ENVIO_PACK = "40000000001"
ENVIO_SOLA = "40000000002"


@pytest.fixture()
def db():
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    engine = create_engine(POSTGRES_TEST_URL)
    connection = engine.connect()
    transaction = connection.begin()
    tables = [Base.metadata.tables[name] for name in _TABLES]
    Base.metadata.create_all(bind=connection, tables=tables, checkfirst=True)
    session = sessionmaker(bind=connection, autoflush=False)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
    engine.dispose()


def _header(mlo_id: int, orden: str, pack: str | None, envio: str | None) -> MercadoLibreOrderHeader:
    return MercadoLibreOrderHeader(
        comp_id=1,
        mlo_id=mlo_id,
        mlorder_id=orden,
        ml_pack_id=pack,
        mlshippingid=envio,
        mlo_cd=datetime(2026, 10, 25, 10, 0),
        mlo_status="paid",
    )


@pytest.fixture()
def ventas(db):
    db.add_all(
        [
            # The cart: two orders, one pack. The shipment lives in the shipping table, not on the header.
            _header(900001, ORDEN_A, PACK, None),
            _header(900002, ORDEN_B, PACK, None),
            MercadoLibreOrderShipping(comp_id=1, mlm_id=800001, mlo_id=900001, mlshippingid=ENVIO_PACK),
            MercadoLibreOrderShipping(comp_id=1, mlm_id=800002, mlo_id=900002, mlshippingid=ENVIO_PACK),
            # A single order whose shipment is only on the header.
            _header(900003, ORDEN_SOLA, None, ENVIO_SOLA),
        ]
    )
    db.flush()


def test_orders_of_one_pack_are_one_operation_with_its_shipping_number(db, ventas):
    resueltas = resolver_operaciones(db, [ORDEN_A, ORDEN_B])

    assert resueltas == {
        ORDEN_A: OperacionML(operacion=PACK, numero_envio=ENVIO_PACK),
        ORDEN_B: OperacionML(operacion=PACK, numero_envio=ENVIO_PACK),
    }


def test_a_pack_or_a_shipment_number_typed_in_the_case_finds_the_same_operation(db, ventas):
    resueltas = resolver_operaciones(db, [PACK, ENVIO_PACK])

    assert resueltas[PACK] == OperacionML(operacion=PACK, numero_envio=ENVIO_PACK)
    assert resueltas[ENVIO_PACK] == OperacionML(operacion=PACK, numero_envio=ENVIO_PACK)


def test_an_order_outside_a_pack_is_its_own_operation_with_the_header_shipping(db, ventas):
    assert resolver_operaciones(db, [ORDEN_SOLA]) == {
        ORDEN_SOLA: OperacionML(operacion=ORDEN_SOLA, numero_envio=ENVIO_SOLA),
    }


def test_a_value_with_no_stored_sale_is_left_out(db, ventas):
    assert resolver_operaciones(db, ["ML-998877", ORDEN_SOLA]).keys() == {ORDEN_SOLA}
    assert resolver_operaciones(db, []) == {}


def test_the_whole_page_resolves_in_two_queries(db, ventas):
    statements: list[str] = []
    listener = lambda *args: statements.append(args[2])  # noqa: E731
    event.listen(db.get_bind(), "before_cursor_execute", listener)
    try:
        resolver_operaciones(db, [ORDEN_A, ORDEN_B, ORDEN_SOLA, PACK, "ML-998877"])
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", listener)

    assert len(statements) == 2
