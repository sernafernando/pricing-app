"""Consultas > Ranking values the stock at costo SI (sell-in-costo-si T3 PR 10, unit B; owner L4.7: "El promedio es el
que se va a mostrar y usar en todos los cálculos donde se use costo"). `/consultas/ranking`, `/ranking/resumen` and
`/ranking/kpis` read the current cost through the reader (`services/costo_si/lote.sql_actual_fila`, as `lote.actuales`
reads it), at the page's own USD rate; a stocked product without any cost is "Sin costo": its valuation stays null, it is never summed as 0 and every total
counts it apart (`productos_sin_costo`). Runs the real SQL on a throwaway Postgres schema. Invented data only."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.combo_componente import ComboComponente
from app.models.commercial_transaction import CommercialTransaction
from app.models.costo_si import CostoSiPaso
from app.models.cur_exch_history import CurExchHistory
from app.models.item_cost_list_history import ItemCostListHistory
from app.models.item_transaction import ItemTransaction
from app.models.marca_pm import MarcaPM
from app.models.producto import ProductoERP
from app.models.producto_ageing import ProductoAgeing
from app.models.stock_por_deposito import StockPorDeposito
from app.models.tb_item import TBItem
from app.models.tb_price_list_items import TbPriceListItems
from app.models.tipo_cambio import TipoCambio
from app.routers import consultas
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

URL = "/api/consultas/ranking"
MARCA = "MARCA DEMO"
CON_COSTO, SIN_COSTO, EN_PESOS = 6101, 6102, 6103

STUBS = ["CREATE TABLE usuarios (id INTEGER PRIMARY KEY, nombre TEXT)"]
TABLES = [
    ProductoERP.__table__,
    TBItem.__table__,
    ComboComponente.__table__,
    ItemCostListHistory.__table__,
    CostoSiPaso.__table__,
    TipoCambio.__table__,
    CurExchHistory.__table__,  # the reader falls back to the ERP rate history
    CommercialTransaction.__table__,
    ItemTransaction.__table__,
    StockPorDeposito.__table__,
    TbPriceListItems.__table__,
    MarcaPM.__table__,
    ProductoAgeing.__table__,
]


@pytest.fixture(scope="module")
def pg() -> Iterator[Engine]:
    with throwaway_schema("consultas_costo_si", TABLES, STUBS) as pg:
        yield pg


def _run(pg: Engine, sql: str, **params) -> None:
    with pg.begin() as conn:
        conn.execute(text(sql), params)


@pytest.fixture(autouse=True)
def _clean(pg: Engine) -> Iterator[None]:
    yield
    for table in ("productos_erp", "tb_item", "costo_si_pasos", "tipo_cambio", "stock_por_deposito"):
        _run(pg, f"DELETE FROM {table}")


@pytest.fixture
def client(pg: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(consultas.router, prefix="/api")
    factory = sessionmaker(bind=pg)

    def db() -> Iterator:
        with factory() as session:
            yield session

    user = SimpleNamespace(id=7)
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: user
    for route in consultas.router.routes:  # the permission gates: this file tests the valuation, not the access
        for dependency in getattr(route, "dependencies", []):
            app.dependency_overrides[dependency.dependency] = lambda: user
    monkeypatch.setattr(consultas, "_scope_user_id", lambda current_user, db: None)  # full access
    with TestClient(app) as c:
        yield c


def _producto(pg: Engine, item_id: int, stock: int, moneda: str = "USD", costo: float | None = None) -> None:
    """An active product with list cost `costo` in `moneda` and `stock` units in depot 1."""
    _run(
        pg,
        "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, moneda_costo, costo, activo)"
        " VALUES (:i, :c, 'Producto', :m, 'CAMARAS', :mon, :costo, TRUE)",
        i=item_id,
        c=f"C{item_id}",
        m=MARCA,
        mon=moneda,
        costo=costo,
    )
    _run(pg, "INSERT INTO tb_item (comp_id, item_id, item_code, cat_id) VALUES (1, :i, :c, 3)", i=item_id, c="x")
    _run(pg, "INSERT INTO stock_por_deposito (item_id, stor_id, stock) VALUES (:i, 1, :s)", i=item_id, s=stock)


def _costo_si(pg: Engine, item_id: int, promedio: str, moneda: str = "USD") -> None:
    _run(
        pg,
        "INSERT INTO costo_si_pasos (item_id, orden, tipo, fecha, cantidad, stock_antes, stock_base, stock_despues,"
        " promedio_usd, moneda) VALUES (:i, 0, 'inicio', :f, 0, 0, 0, 0, :p, :m)",
        i=item_id,
        f=date(2026, 10, 1),
        p=promedio,
        m=moneda,
    )


def _dolar(pg: Engine, venta: float) -> None:
    _run(
        pg,
        "INSERT INTO tipo_cambio (fecha, moneda, compra, venta) VALUES (:f, 'USD', :v, :v)",
        f=date(2026, 10, 1),
        v=venta,
    )


def _get(client: TestClient, path: str = "", **params) -> dict:
    response = client.get(f"{URL}{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _fila(client: TestClient, item_id: int) -> dict:
    return next(row for row in _get(client)["items"] if row["item_id"] == item_id)


def test_the_stock_is_valued_at_costo_si_not_at_the_list_cost(pg: Engine, client: TestClient) -> None:
    """B1: 10 units, list USD 30, costo SI USD 20, USD 1000 -> 200 / 200000 everywhere (the list cost gave 300000)."""
    _producto(pg, CON_COSTO, stock=10, costo=30)
    _costo_si(pg, CON_COSTO, "20.00000")
    _dolar(pg, 1000)

    fila = _fila(client, CON_COSTO)
    assert (fila["valor_costo_ars"], fila["valor_costo_usd"], fila["moneda_costo"]) == (200000, 200, "USD")

    kpis = _get(client, "/kpis")
    assert (kpis["capital_costo_ars"], kpis["capital_costo_usd"], kpis["productos_sin_costo"]) == (200000, 200, 0)

    resumen = _get(client, "/resumen")
    (grupo,) = resumen["items"]
    assert (grupo["grupo"], grupo["valor_costo_ars"], grupo["valor_costo_usd"]) == (MARCA, 200000, 200)
    assert (resumen["totales"]["valor_costo_ars"], resumen["totales"]["valor_costo_usd"]) == (200000, 200)
    assert grupo["productos_sin_costo"] == resumen["totales"]["productos_sin_costo"] == 0


def test_without_costo_si_the_current_list_cost_stands_in_not_the_list_history(pg: Engine, client: TestClient) -> None:
    """Q1 like every screen (`lote.actuales`): no costo SI, list USD 30 today, an older list history row of 25 -> the
    valuation uses 30 (300 / 300000), never the history the dated reader falls back to."""
    _producto(pg, CON_COSTO, stock=10, costo=30)
    _run(
        pg,
        "INSERT INTO tb_item_cost_list_history (comp_id, iclh_id, item_id, coslis_id, iclh_price, curr_id, iclh_cd)"
        " VALUES (1, 1, :i, 1, 25, 2, :f)",
        i=CON_COSTO,
        f=date(2026, 10, 1),
    )
    _dolar(pg, 1000)

    fila = _fila(client, CON_COSTO)
    assert (fila["valor_costo_ars"], fila["valor_costo_usd"]) == (300000, 300)
    assert _get(client, "/kpis")["capital_costo_usd"] == 300


def test_a_stocked_product_without_any_cost_is_counted_apart_never_summed_as_zero(
    pg: Engine, client: TestClient
) -> None:
    """B2: the costed product as in B1 plus one with 5 units and no cost at all (no list cost, no costo SI)."""
    _producto(pg, CON_COSTO, stock=10, costo=30)
    _costo_si(pg, CON_COSTO, "20.00000")
    _producto(pg, SIN_COSTO, stock=5)
    _dolar(pg, 1000)

    fila = _fila(client, SIN_COSTO)
    assert (fila["valor_costo_ars"], fila["valor_costo_usd"], fila["total_stock"]) == (None, None, 5)

    kpis = _get(client, "/kpis")
    assert (kpis["capital_costo_ars"], kpis["capital_costo_usd"], kpis["productos_sin_costo"]) == (200000, 200, 1)
    assert kpis["total_productos"] == 2

    resumen = _get(client, "/resumen")
    (grupo,) = resumen["items"]
    assert (grupo["valor_costo_ars"], grupo["productos_sin_costo"], grupo["num_productos"]) == (200000, 1, 2)
    assert (resumen["totales"]["valor_costo_ars"], resumen["totales"]["productos_sin_costo"]) == (200000, 1)


def test_a_peso_costo_si_converts_to_dollars_at_the_page_rate(pg: Engine, client: TestClient) -> None:
    """An ARS product: costo SI ARS 15000 (list 14000), 2 units, USD 1000 -> 30000 pesos, 30 dollars."""
    _producto(pg, EN_PESOS, stock=2, moneda="ARS", costo=14000)
    _costo_si(pg, EN_PESOS, "15000.00000", moneda="ARS")
    _dolar(pg, 1000)

    fila = _fila(client, EN_PESOS)
    assert (fila["valor_costo_ars"], fila["valor_costo_usd"], fila["moneda_costo"]) == (30000, 30, "ARS")


def test_the_valuation_still_sorts_with_the_unknown_last(pg: Engine, client: TestClient) -> None:
    """Sorting by valor costo keeps working on the new expression: costed products first, "Sin costo" last."""
    _producto(pg, CON_COSTO, stock=10, costo=30)
    _costo_si(pg, CON_COSTO, "20.00000")
    _producto(pg, SIN_COSTO, stock=5)
    _producto(pg, EN_PESOS, stock=2, moneda="ARS", costo=14000)
    _dolar(pg, 1000)

    for direccion in ("asc", "desc"):
        body = _get(client, orden_campos="valor_costo_ars", orden_direcciones=direccion)
        ids = [row["item_id"] for row in body["items"]]
        assert ids[-1] == SIN_COSTO, (direccion, ids)
        assert set(ids[:2]) == {CON_COSTO, EN_PESOS}
