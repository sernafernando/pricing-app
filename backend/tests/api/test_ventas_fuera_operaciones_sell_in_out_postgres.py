"""`GET /ventas-fuera-ml/operaciones` shows each operation without and with sell in / sell out
(sell-in-sell-out T14). Owner: "Always show both: cost and cost with sell in; markup and totals
without and with sell out." Sell in lowers cost; sell out is a credit added to profit.

The existing figures (`costo_pesos_sin_iva`, `ganancia`, `markup`) stay as the "without" ones.
An operation with no consumptions gets null "with" figures, never a fallback. Postgres world
from `tests.services.test_sell_in_out_ventas_postgres`.
"""

from __future__ import annotations

from typing import Iterator, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_current_user
from app.api.endpoints import ventas_fuera_ml
from app.core.database import get_db
from tests.services import test_sell_in_out_ventas_postgres as w
from tests.services.sell_in._world import update_venta

pytestmark = pytest.mark.postgres

NUEVOS = (
    "sell_in_ars",
    "sell_out_ars",
    "sell_out_estimado",
    "costo_con_sell_in",
    "ganancia_con_sell_in_out",
    "markup_con_sell_in_out",
)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("ventas_fuera_sio") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(ventas_fuera_ml.router, prefix="/api")
    factory = sessionmaker(bind=engine)

    def db() -> Iterator:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: {"id": 7}
    with TestClient(app) as c:
        yield c


def _venta(engine: Engine, signo: int = 1) -> int:
    """Sold for 1500 without VAT at a cost of 1000: profit 500, markup 50%."""
    ref = w.venta(engine, signo=signo)
    update_venta(engine, "fuera", ref, monto_total=1500, costo_total=1000, ganancia=500, markup_porcentaje=50)
    return ref


def _operaciones(client: TestClient, **params) -> dict:
    response = client.get(
        "/api/ventas-fuera-ml/operaciones", params={"from_date": "2026-11-01", "to_date": "2026-11-30", **params}
    )
    assert response.status_code == 200, response.text
    return {op["id_operacion"]: op for op in response.json()}


class TestOperacionesSellInOut:
    def test_sell_in_lowers_cost_and_adds_to_profit(self, engine: Engine, client: TestClient) -> None:
        ref = _venta(engine)
        w.sell_in(engine, w.compra_item(engine), ref, "200.00")

        op = _operaciones(client)[ref]

        assert (op["costo_pesos_sin_iva"], op["ganancia"], op["markup"]) == (1000, 500, 0.5)
        assert (op["sell_in_ars"], op["sell_out_ars"], op["sell_out_estimado"]) == (200, None, None)
        assert (op["costo_con_sell_in"], op["ganancia_con_sell_in_out"]) == (800, 700)
        assert op["markup_con_sell_in_out"] == pytest.approx(0.875)  # 700 / 800

    def test_an_ars_sell_out_adds_to_profit_and_leaves_cost(self, engine: Engine, client: TestClient) -> None:
        ref = _venta(engine)
        w.sell_out(engine, w.campana(engine), ref, "100.00")

        op = _operaciones(client)[ref]

        assert (op["sell_in_ars"], op["sell_out_ars"], op["sell_out_estimado"]) == (None, 100, False)
        assert (op["costo_con_sell_in"], op["ganancia_con_sell_in_out"]) == (1000, 600)
        assert op["markup_con_sell_in_out"] == pytest.approx(0.6)

    def test_a_usd_sell_out_converts_at_its_rate(self, engine: Engine, client: TestClient) -> None:
        ref = _venta(engine)
        w.sell_in(engine, w.compra_item(engine), ref, "200.00")
        cid = w.campana(engine, moneda="USD", tc_modo="fijo", tipo_cambio="1000", monto_unit="0.10")
        w.sell_out(engine, cid, ref, "0.20", tc_venta="1000")

        op = _operaciones(client)[ref]

        assert (op["sell_out_ars"], op["sell_out_estimado"]) == (200, False)
        assert (op["costo_con_sell_in"], op["ganancia_con_sell_in_out"]) == (800, 900)
        assert op["markup_con_sell_in_out"] == pytest.approx(1.125)

    def test_a_usd_sell_out_without_rate_leaves_profit_and_markup_unknown(
        self, engine: Engine, client: TestClient
    ) -> None:
        ref = _venta(engine)
        w.sell_in(engine, w.compra_item(engine), ref, "200.00")
        w.sell_out(engine, w.campana(engine, moneda="USD", tc_modo="dia_venta", monto_unit="0.10"), ref, "0.20")

        op = _operaciones(client)[ref]

        assert (op["sell_in_ars"], op["sell_out_ars"], op["sell_out_estimado"]) == (200, None, True)
        assert op["costo_con_sell_in"] == 800
        assert (op["ganancia_con_sell_in_out"], op["markup_con_sell_in_out"]) == (None, None)

    def test_two_campaigns_on_one_sale_are_summed(self, engine: Engine, client: TestClient) -> None:
        ref = _venta(engine)
        w.sell_out(engine, w.campana(engine), ref, "100.00")
        w.sell_out(engine, w.campana(engine), ref, "50.00")

        op = _operaciones(client)[ref]

        assert (op["sell_out_ars"], op["ganancia_con_sell_in_out"]) == (150, 650)

    def test_an_operation_without_consumptions_keeps_its_figures_and_gets_nulls(
        self, engine: Engine, client: TestClient
    ) -> None:
        ref = _venta(engine)

        op = _operaciones(client)[ref]

        assert (op["costo_pesos_sin_iva"], op["ganancia"], op["markup"], op["signo"]) == (1000, 500, 0.5, 1)
        assert {k: op[k] for k in NUEVOS} == dict.fromkeys(NUEVOS)

    def test_a_return_is_unchanged(self, engine: Engine, client: TestClient) -> None:
        vendida = _venta(engine)
        w.sell_in(engine, w.compra_item(engine), vendida, "200.00")
        devuelta = _venta(engine, signo=-1)

        ops = _operaciones(client)
        op = ops[devuelta]

        assert (op["signo"], op["costo_pesos_sin_iva"], op["ganancia"], op["markup"]) == (-1, 1000, 500, 0.5)
        assert {k: op[k] for k in NUEVOS} == dict.fromkeys(NUEVOS)
        assert ops[vendida]["sell_in_ars"] == 200

    def test_a_page_reads_consumptions_with_a_fixed_number_of_queries(self, engine: Engine, client: TestClient) -> None:
        refs = [_venta(engine) for _ in range(5)]
        cid = w.campana(engine)
        for ref in refs:
            w.sell_out(engine, cid, ref, "1.00")
            w.sell_in(engine, w.compra_item(engine), ref, "1.00")

        def contar(limit: int) -> int:
            statements: List[str] = []

            def listener(conn, cursor, statement, *args) -> None:
                statements.append(statement)

            event.listen(engine, "before_cursor_execute", listener)
            try:
                assert len(_operaciones(client, limit=limit)) == limit
            finally:
                event.remove(engine, "before_cursor_execute", listener)
            return sum(1 for s in statements if "_consumos" in s)

        assert contar(1) == contar(5) == 2
