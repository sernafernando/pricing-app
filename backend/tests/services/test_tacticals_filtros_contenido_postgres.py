"""Tacticals list filters by what the tactical holds (SISO S1, S2) on Postgres.

Owner, 2026-11-11 (S1): "Sell in / Sell out: Filtro que pueda permita elegir entre cosas que tengan adentro cargado,
factura,producto, categoría, etc."
Owner, 2026-11-11 (S2): "Filtro de productos, ponés un producto en el buscador y que te traiga todas las campañás que
lo tengan dentro (incluído si es solo por marca)"
Orchestrator L3: `contiene` is the kind of line (productos | marca | categoria | factura); the product search is a text
box (código or descripción, contains) and an invoice line holds the products on that invoice.
"""

from __future__ import annotations

from datetime import date
from typing import Iterator, Optional

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.services import tacticals as service
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in import _bono_world as bw
from tests.services.test_tacticals_postgres import STUBS, TABLES, USUARIO, _install, _tactical

pytestmark = pytest.mark.postgres

TODOS = ["sell_in", "sell_out"]
MERCUSYS = bw.MERCUSYS
TPLINK = bw.TPLINK


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("tacticals_contenido", TABLES, STUBS, after=_install) as e:
        yield e


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        with engine.begin() as conn:
            for table in ("sell_out_campanas", "offset_grupos", "auditoria", "sell_in_bono_consumos"):
                conn.execute(text(f"DELETE FROM {table}"))
            for table in ("tactical_cobranzas", "tactical_tiendas", "tactical_marcas"):
                conn.execute(text(f"DELETE FROM {table}"))
        bw.clean(engine)
        with engine.begin() as conn:
            conn.execute(text("UPDATE productos_erp SET categoria = 'Routers', iva = 21"))
            conn.execute(text("DELETE FROM tacticals"))


def _ids(db: Session, contiene: Optional[str] = None, producto: Optional[str] = None) -> set[int]:
    db.expire_all()
    filtros = service.Filtros(tipos=TODOS, contiene=contiene, producto=producto)
    total, filas = service.listar(db, filtros, 1, 50)
    assert total == len(filas)
    return {t.id for t in filas}


def _crear(db: Session, tipo: str, lineas: list[dict], marca: str = TPLINK) -> int:
    datos = _tactical(tipo, lineas, marca=marca)
    return service.crear(db, datos, USUARIO).id


def _linea(alcance: str, **campos) -> dict:
    return {"alcance": alcance, "modo_monto": "por_unidad", "valor": "10", **campos}


def _factura(engine: Engine, items: dict[int, int], total: bool = False) -> dict:
    """An invoice line over a new invoice with `items` invoiced: a percentage bonus, or (`total`) an invoice total."""
    pedido = bw.pedido(engine, items, date(2026, 11, 10), moneda="ARS")  # USD costs: its rate
    if total:
        return {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "monto_total", "valor": "15000"}
    return {"alcance": "factura", "pedido_compra_id": pedido, "modo_monto": "porcentaje", "valor": "5"}


class TestContiene:
    """S1: tacticals with at least one line of the chosen kind, sell in and sell out alike."""

    @pytest.fixture
    def creados(self, db: Session, engine: Engine) -> dict[str, int]:
        bw.set_categoria(engine, 950, "Switches")
        return {
            "out_productos": _crear(db, "sell_out", [_linea("productos", item_ids=[2964])]),
            "out_marca": _crear(db, "sell_out", [_linea("marca", marca=TPLINK)]),
            "out_categoria": _crear(db, "sell_out", [_linea("categoria", categoria="Routers")]),
            "in_productos": _crear(db, "sell_in", [_linea("productos", item_ids=[2270])]),
            "in_marca": _crear(db, "sell_in", [_linea("marca", marca=TPLINK)]),
            "in_categoria": _crear(db, "sell_in", [_linea("categoria", categoria="Switches")]),
            "in_factura": _crear(db, "sell_in", [_factura(engine, {2964: 10})]),
            "in_factura_total": _crear(db, "sell_in", [_factura(engine, {2964: 10}, total=True)]),
        }

    @pytest.mark.parametrize(
        ("contiene", "esperados"),
        [
            ("productos", {"out_productos", "in_productos"}),
            ("marca", {"out_marca", "in_marca"}),
            ("categoria", {"out_categoria", "in_categoria"}),
            ("factura", {"in_factura", "in_factura_total"}),
        ],
    )
    def test_only_tacticals_with_a_line_of_that_kind(self, db, creados, contiene, esperados) -> None:
        assert _ids(db, contiene=contiene) == {creados[k] for k in esperados}

    def test_without_the_filter_every_tactical_is_listed(self, db, creados) -> None:
        assert _ids(db) == set(creados.values())

    def test_a_tactical_with_lines_of_two_kinds_matches_both(self, db, engine) -> None:
        mixto = _crear(db, "sell_in", [_linea("marca", marca=TPLINK), _factura(engine, {2270: 3})])

        assert (_ids(db, contiene="marca"), _ids(db, contiene="factura"), _ids(db, contiene="productos")) == (
            {mixto}, {mixto}, set(),
        )  # fmt: skip

    def test_the_kpis_count_only_the_filtered_tacticals(self, db, creados) -> None:
        kpis = service.kpis(db, service.Filtros(tipos=TODOS, contiene="factura"))

        assert kpis["pendientes"]["cantidad"] + kpis["cobrados"]["cantidad"] == 2


class TestProducto:
    """S2: every tactical one of whose lines reaches a product matching the search, however the line reaches it."""

    def test_a_brand_line_reaches_the_products_of_its_brand(self, db) -> None:
        mercusys = _crear(db, "sell_out", [_linea("marca", marca=MERCUSYS)], marca=MERCUSYS)
        _crear(db, "sell_out", [_linea("marca", marca=TPLINK)])

        assert _ids(db, producto="C950") == {mercusys}

    def test_a_sell_in_brand_line_reaches_them_too(self, db) -> None:
        mercusys = _crear(db, "sell_in", [_linea("marca", marca=MERCUSYS)], marca=MERCUSYS)
        _crear(db, "sell_in", [_linea("marca", marca=TPLINK)])

        assert _ids(db, producto="C950") == {mercusys}

    def test_a_category_line_reaches_the_products_of_its_category(self, db, engine) -> None:
        bw.set_categoria(engine, 950, "Switches")
        switches_out = _crear(db, "sell_out", [_linea("categoria", categoria="Switches")])
        switches_in = _crear(db, "sell_in", [_linea("categoria", categoria="Switches")])
        _crear(db, "sell_out", [_linea("categoria", categoria="Routers")])

        assert _ids(db, producto="C950") == {switches_out, switches_in}

    def test_a_products_line_reaches_only_its_products(self, db) -> None:
        con_out = _crear(db, "sell_out", [_linea("productos", item_ids=[950])])
        con_in = _crear(db, "sell_in", [_linea("productos", item_ids=[2270, 950])])
        _crear(db, "sell_out", [_linea("productos", item_ids=[2964])])
        _crear(db, "sell_in", [_linea("productos", item_ids=[2270])])

        assert _ids(db, producto="C950") == {con_out, con_in}

    def test_an_invoice_line_reaches_the_products_on_its_invoice(self, db, engine) -> None:
        bono = _crear(db, "sell_in", [_factura(engine, {950: 2, 2964: 1})])
        total = _crear(db, "sell_in", [_factura(engine, {950: 4}, total=True)])
        _crear(db, "sell_in", [_factura(engine, {2964: 1})])
        _crear(db, "sell_in", [_factura(engine, {2964: 1}, total=True)])

        assert _ids(db, producto="C950") == {bono, total}

    def test_the_search_matches_code_or_description_ignoring_case(self, db, engine) -> None:
        with engine.begin() as conn:
            conn.execute(text("UPDATE productos_erp SET descripcion = 'Range Extender RE200' WHERE item_id = 950"))
        mercusys = _crear(db, "sell_out", [_linea("marca", marca=MERCUSYS)], marca=MERCUSYS)
        _crear(db, "sell_out", [_linea("productos", item_ids=[2964])])

        assert (_ids(db, producto="re200"), _ids(db, producto="c95")) == ({mercusys}, {mercusys})

    def test_a_search_matching_several_products_lists_the_tacticals_of_any(self, db) -> None:
        a = _crear(db, "sell_out", [_linea("productos", item_ids=[2964])])
        b = _crear(db, "sell_out", [_linea("marca", marca=MERCUSYS)], marca=MERCUSYS)

        assert _ids(db, producto="C") == {a, b}

    def test_no_product_matches_no_tactical(self, db) -> None:
        _crear(db, "sell_out", [_linea("marca", marca=TPLINK)])

        assert _ids(db, producto="no existe") == set()

    def test_it_combines_with_contiene(self, db) -> None:
        marca = _crear(db, "sell_out", [_linea("marca", marca=MERCUSYS)], marca=MERCUSYS)
        _crear(db, "sell_out", [_linea("productos", item_ids=[950])])

        assert _ids(db, contiene="marca", producto="C950") == {marca}
