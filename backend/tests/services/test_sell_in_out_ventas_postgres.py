"""Sell in and sell out credited to each sale of a page (sell-in-sell-out T14).

`sell_in_out_ventas.montos_por_venta` reads what the allocators already wrote
(`sell_in_consumos`, `sell_out_consumos`) for the page's sales only. The
consumption rows are written directly here: which sale gets what is the
allocators' business, tested in `sell_in/` and `sell_out/`. Postgres only
(`round(numeric)`, grouping by a campaign's primary key).

`world`, `compra_item`, `campana`, `sell_in`, `sell_out` and `venta` are also
used by the endpoint tests in `tests/api/`.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Iterator, List, Optional

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import sessionmaker

from app.models.producto import ProductoERP
from app.models.sell_in import SellInBonoMarca, SellInCompra, SellInCompraItem, SellInCompraPedido, SellInConsumo
from app.models.sell_out import SellOutCampana, SellOutConsumo
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica
from app.services import sell_in_out_ventas
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in import _world as w_in
from tests.services.sell_out import _world as w_out

pytestmark = pytest.mark.postgres

DIA = date(2026, 11, 3)
STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "INSERT INTO usuarios VALUES (7)",
    "CREATE TABLE proveedores (id INTEGER PRIMARY KEY, nombre TEXT)",
    "CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY, numero TEXT)",
    "CREATE TABLE offsets_ganancia (id INTEGER PRIMARY KEY)",
    # What the fuera operations list joins besides the metrics table.
    "CREATE TABLE tb_customer (comp_id INTEGER, cust_id INTEGER, cust_name TEXT)",
    "CREATE TABLE ventas_fuera_ml_override (it_transaction BIGINT, cliente TEXT, marca TEXT, categoria TEXT, "
    "subcategoria TEXT, codigo TEXT, descripcion TEXT, cantidad NUMERIC, precio_unitario NUMERIC, "
    "costo_unitario NUMERIC)",
]
TABLES = [
    ProductoERP.__table__,
    SellInBonoMarca.__table__,
    SellInCompra.__table__,
    SellInCompraItem.__table__,
    SellInCompraPedido.__table__,
    SellInConsumo.__table__,
    SellOutCampana.__table__,
    SellOutConsumo.__table__,
    VentaFueraMLMetrica.__table__,
]


def _install(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO productos_erp (item_id, codigo, descripcion) VALUES (2964, 'C2964', 'Router')"))


@contextmanager
def world(prefix: str) -> Iterator[Engine]:
    with throwaway_schema(prefix, TABLES, STUBS, after=_install) as engine:
        yield engine


def clean(engine: Engine) -> None:
    with engine.begin() as conn:
        for table in ("ventas_fuera_ml_metricas", "sell_in_compras", "sell_out_campanas"):
            conn.execute(text(f"DELETE FROM {table}"))  # items and consumptions cascade


def venta(engine: Engine, *, signo: int = 1) -> int:
    """A fuera sale of 2 units of item 2964 (`tests.services.sell_in._world.venta`)."""
    return w_in.venta(engine, "fuera", 2964, 2, DIA, signo=signo)


def compra_item(engine: Engine) -> int:
    return w_in.compra(engine, [(2964, 10, "1000.00")])[0]


def campana(engine: Engine, **values) -> int:
    """An ARS campaign per unit, unless overridden (`tests.services.sell_out._world.campana`)."""
    return w_out.campana(engine, [], **values)


def sell_in(engine: Engine, compra_item_id: int, ref: int, descuento: str, canal: str = "fuera") -> None:
    w_out.execute(
        engine,
        "INSERT INTO sell_in_consumos (compra_item_id, canal, venta_ref, item_id, fecha_venta, unidades, "
        "descuento_ars) VALUES (:c, :canal, :r, 2964, :f, 1, :d)",
        c=compra_item_id,
        canal=canal,
        r=ref,
        f=DIA,
        d=descuento,
    )


def sell_out(
    engine: Engine, campana_id: int, ref: int, monto: str, tc_venta: Optional[str] = None, canal: str = "fuera"
) -> None:
    w_out.execute(
        engine,
        "INSERT INTO sell_out_consumos (campana_id, canal, venta_ref, item_id, fecha_venta, unidades, monto, "
        "tc_venta) VALUES (:c, :canal, :r, 2964, :f, 2, :m, :tc)",
        c=campana_id,
        canal=canal,
        r=ref,
        f=DIA,
        m=monto,
        tc=tc_venta,
    )


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with world("sell_in_out_ventas") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    clean(engine)


def _montos(engine: Engine, refs: List[int], canal: str = "fuera") -> dict:
    with sessionmaker(bind=engine)() as db:
        return sell_in_out_ventas.montos_por_venta(db, canal, refs)


class TestMontosPorVenta:
    def test_sell_in_only_sums_the_discounts_and_leaves_sell_out_empty(self, engine: Engine) -> None:
        ref = venta(engine)
        item = compra_item(engine)
        sell_in(engine, item, ref, "150.25")
        sell_in(engine, compra_item(engine), ref, "49.75")

        m = _montos(engine, [ref])[ref]

        assert (m.sell_in_ars, m.sell_out_ars, m.sell_out_estimado) == (Decimal("200.00"), None, None)
        assert m.credito_ars == Decimal("200.00")

    def test_an_ars_sell_out_is_its_amount(self, engine: Engine) -> None:
        ref = venta(engine)
        sell_out(engine, campana(engine), ref, "20.00")

        m = _montos(engine, [ref])[ref]

        assert (m.sell_in_ars, m.sell_out_ars, m.sell_out_estimado) == (None, Decimal("20.00"), False)
        assert m.credito_ars == Decimal("20.00")

    def test_a_usd_sell_out_converts_at_the_row_rate_rounded_to_cents(self, engine: Engine) -> None:
        ref = venta(engine)
        cid = campana(engine, moneda="USD", tc_modo="fijo", tipo_cambio="1000.123", monto_unit="5.00")
        sell_out(engine, cid, ref, "10.00", tc_venta="1000.12345")

        m = _montos(engine, [ref])[ref]

        assert (m.sell_out_ars, m.sell_out_estimado) == (Decimal("10001.23"), False)

    def test_a_usd_row_without_its_rate_leaves_the_sale_unknown_and_estimated(self, engine: Engine) -> None:
        ref = venta(engine)
        sell_in(engine, compra_item(engine), ref, "100.00")
        sell_out(engine, campana(engine), ref, "20.00")  # an ARS campaign: never a partial sum
        cid = campana(engine, moneda="USD", tc_modo="dia_venta", monto_unit="5.00")
        sell_out(engine, cid, ref, "10.00", tc_venta=None)

        m = _montos(engine, [ref])[ref]

        assert (m.sell_in_ars, m.sell_out_ars, m.sell_out_estimado) == (Decimal("100.00"), None, True)
        assert m.credito_ars is None

    def test_an_al_cobro_campaign_without_its_rate_is_estimated(self, engine: Engine) -> None:
        ref = venta(engine)
        cid = campana(engine, moneda="USD", tc_modo="al_cobro", tipo_cambio=None, monto_unit="5.00")
        sell_out(engine, cid, ref, "10.00", tc_venta="1200")

        m = _montos(engine, [ref])[ref]

        assert (m.sell_out_ars, m.sell_out_estimado) == (Decimal("12000.00"), True)

    def test_two_campaigns_on_one_sale_add_up(self, engine: Engine) -> None:
        ref = venta(engine)
        sell_out(engine, campana(engine), ref, "20.00")
        cid = campana(engine, moneda="USD", tc_modo="fijo", tipo_cambio="1000", monto_unit="5.00")
        sell_out(engine, cid, ref, "10.00", tc_venta="1000")

        m = _montos(engine, [ref])[ref]

        assert (m.sell_out_ars, m.sell_out_estimado) == (Decimal("10020.00"), False)

    def test_only_the_asked_sales_of_the_asked_channel_come_back(self, engine: Engine) -> None:
        ref, otra, sin_nada = venta(engine), venta(engine), venta(engine)
        cid = campana(engine)
        sell_out(engine, cid, ref, "20.00")
        sell_out(engine, cid, otra, "30.00")
        sell_in(engine, compra_item(engine), ref, "5.00", canal="tn")

        assert set(_montos(engine, [ref, sin_nada])) == {ref}
        assert _montos(engine, [ref], canal="tn")[ref].sell_out_ars is None
        assert _montos(engine, []) == {}

    def test_the_query_count_does_not_grow_with_the_page(self, engine: Engine) -> None:
        refs = [venta(engine) for _ in range(6)]
        cid = campana(engine)
        for ref in refs:
            sell_out(engine, cid, ref, "1.00")
            sell_in(engine, compra_item(engine), ref, "1.00")

        def contar(page: List[int]) -> int:
            statements: List[str] = []

            def listener(conn, cursor, statement, *args) -> None:
                statements.append(statement)

            event.listen(engine, "before_cursor_execute", listener)
            try:
                assert len(_montos(engine, page)) == len(page)
            finally:
                event.remove(engine, "before_cursor_execute", listener)
            return sum(1 for s in statements if "_consumos" in s)

        assert contar(refs[:1]) == contar(refs) == 2
