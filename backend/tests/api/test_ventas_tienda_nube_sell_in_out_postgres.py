"""`GET /ventas-tienda-nube` shows each sale without and with sell in / sell out (sell-in-sell-out T14).
Owner: "Always show both: cost and cost with sell in; markup and totals without and with sell out."

The list reads the ERP (`get_ventas_tienda_nube_query`), so the test swaps that query for fixed rows
and keeps the real sell-in / sell-out tables (Postgres world from
`tests.services.test_sell_in_out_ventas_postgres`; `venta_ref` for `tn` is the sale's
`it_transaction`, the list's `id_operacion`). Its `markup` is price / cost - 1 (no TN commission)
while `ganancia` nets the commission out, so the "with" figures keep those same bases.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_current_user
from app.api.endpoints import ventas_tienda_nube
from app.core.database import get_db
from tests.services import test_sell_in_out_ventas_postgres as w

pytestmark = pytest.mark.postgres

NUEVOS = (
    "sell_in_ars",
    "sell_out_ars",
    "sell_out_estimado",
    "costo_con_sell_in",
    "ganancia_con_sell_in_out",
    "markup_con_sell_in_out",
)
VENDIDA, SIN_CONSUMOS = 9001, 9002


def _query() -> str:
    """Two sales of 1500 without VAT at a cost of 1000 (markup 50%), every other column null."""
    numericas = {"id_operacion", "precio_final_sin_iva", "costo_pesos_sin_iva", "markup"}
    otras = ", ".join(
        f"NULL AS {name}" for name in ventas_tienda_nube.VentaTiendaNubeResponse.model_fields if name not in numericas
    )
    return (
        "SELECT v.id_operacion, v.precio_final_sin_iva, v.costo_pesos_sin_iva, v.markup, "
        f"{otras} FROM (VALUES ({VENDIDA}, 1500.0, 1000.0, 0.5), ({SIN_CONSUMOS}, 1500.0, 1000.0, 0.5)) "
        "AS v(id_operacion, precio_final_sin_iva, costo_pesos_sin_iva, markup) "
        "WHERE CAST(:from_date AS text) IS NOT NULL AND CAST(:to_date AS text) IS NOT NULL"
    )


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("ventas_tn_sio") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


@pytest.fixture
def client(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(ventas_tienda_nube, "get_ventas_tienda_nube_query", _query)
    monkeypatch.setattr(ventas_tienda_nube, "get_comision_tienda_nube", lambda db, fecha=None: 10.0)
    app = FastAPI()
    app.include_router(ventas_tienda_nube.router, prefix="/api")
    factory = sessionmaker(bind=engine)

    def db() -> Iterator:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: {"id": 7}
    with TestClient(app) as c:
        yield c


def _ventas(client: TestClient) -> dict:
    response = client.get("/api/ventas-tienda-nube", params={"from_date": "2026-11-01", "to_date": "2026-11-30"})
    assert response.status_code == 200, response.text
    return {v["id_operacion"]: v for v in response.json()}


class TestVentasTiendaNubeSellInOut:
    def test_sell_in_and_sell_out_give_the_figures_with_them(self, engine: Engine, client: TestClient) -> None:
        w.sell_in(engine, w.compra_item(engine), VENDIDA, "200.00", canal="tn")
        w.sell_out(engine, w.campana(engine), VENDIDA, "100.00", canal="tn")

        venta = _ventas(client)[VENDIDA]

        # Commission 10%: 150; profit without = 1500 - 150 - 1000 = 350.
        assert (float(venta["costo_pesos_sin_iva"]), float(venta["ganancia"]), float(venta["markup"])) == (
            1000,
            350,
            0.5,
        )
        assert (venta["sell_in_ars"], venta["sell_out_ars"], venta["sell_out_estimado"]) == (200, 100, False)
        assert (venta["costo_con_sell_in"], venta["ganancia_con_sell_in_out"]) == (800, 650)
        # Same base as `markup` (price / cost - 1): (1500 - 800 + 100) / 800.
        assert venta["markup_con_sell_in_out"] == pytest.approx(1.0)

    def test_a_usd_sell_out_without_rate_leaves_profit_and_markup_unknown(
        self, engine: Engine, client: TestClient
    ) -> None:
        w.sell_in(engine, w.compra_item(engine), VENDIDA, "200.00", canal="tn")
        cid = w.campana(engine, moneda="USD", tc_modo="dia_venta", monto_unit="0.10")
        w.sell_out(engine, cid, VENDIDA, "0.20", canal="tn")

        venta = _ventas(client)[VENDIDA]

        assert (venta["sell_out_ars"], venta["sell_out_estimado"], venta["costo_con_sell_in"]) == (None, True, 800)
        assert (venta["ganancia_con_sell_in_out"], venta["markup_con_sell_in_out"]) == (None, None)

    def test_a_sale_without_consumptions_gets_nulls(self, engine: Engine, client: TestClient) -> None:
        w.sell_in(engine, w.compra_item(engine), VENDIDA, "200.00", canal="tn")

        venta = _ventas(client)[SIN_CONSUMOS]

        assert float(venta["ganancia"]) == 350
        assert {k: venta[k] for k in NUEVOS} == dict.fromkeys(NUEVOS)

    def test_another_channel_with_the_same_ref_is_not_read(self, engine: Engine, client: TestClient) -> None:
        w.sell_in(engine, w.compra_item(engine), VENDIDA, "200.00", canal="fuera")

        venta = _ventas(client)[VENDIDA]

        assert {k: venta[k] for k in NUEVOS} == dict.fromkeys(NUEVOS)
