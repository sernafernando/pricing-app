"""marcas-sin-stock S2: the ONE shared visibility rule behind every brand option list
(`app.services.marcas_visibles`). A brand is offered iff it has a product in stock OR an
admin listed it as an exception; a selected brand (`keep`) and, on the sales screens, a
brand that sold in the viewed period (`sold`) stay too."""

from __future__ import annotations

import time
from typing import Iterator

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.models.marca_visible_excepcion import MarcaVisibleExcepcion
from app.models.producto import ProductoERP
from app.services.marcas_visibles import brand_visibility, filter_visible_brands
from tests.services.sell._schema import throwaway_schema


def _seed(db) -> None:
    db.add_all(
        [
            ProductoERP(item_id=1, codigo="A1", marca="Epson", stock=3),
            ProductoERP(item_id=2, codigo="A2", marca="Epson", stock=0),
            ProductoERP(item_id=3, codigo="B1", marca="Discontinuada", stock=0),
            ProductoERP(item_id=4, codigo="C1", marca="Excepcion", stock=0),
            ProductoERP(item_id=5, codigo="D1", marca="Agotada", stock=0),
        ]
    )
    db.add(MarcaVisibleExcepcion(marca="EXCEPCION"))
    db.flush()


def test_a_brand_with_stock_is_visible(db) -> None:
    _seed(db)
    assert filter_visible_brands(db, ["Epson"]) == ["Epson"]


def test_a_zero_stock_brand_is_hidden(db) -> None:
    _seed(db)
    assert filter_visible_brands(db, ["Discontinuada", "Epson"]) == ["Epson"]


def test_a_zero_stock_brand_in_the_exception_list_is_visible(db) -> None:
    _seed(db)
    # Compared case- and blank-insensitively, like the product facets.
    assert filter_visible_brands(db, ["Excepcion", " excepcion "]) == ["Excepcion", " excepcion "]


def test_a_selected_hidden_brand_stays_so_its_chip_shows(db) -> None:
    _seed(db)
    assert filter_visible_brands(db, ["Discontinuada", "Agotada"], keep=["DISCONTINUADA"]) == ["Discontinuada"]


def test_a_zero_stock_brand_that_sold_stays_only_where_sales_are_passed(db) -> None:
    _seed(db)
    assert filter_visible_brands(db, ["Agotada"], sold=["Agotada"]) == ["Agotada"]
    assert filter_visible_brands(db, ["Agotada"]) == []


def test_dict_options_read_the_brand_through_marca_of(db) -> None:
    _seed(db)
    rows = [{"marca": "Epson"}, {"marca": "Agotada"}, {"marca": None}]
    assert filter_visible_brands(db, rows, marca_of=lambda r: r["marca"]) == [{"marca": "Epson"}]


@pytest.fixture
def pg_volume() -> Iterator[Session]:
    tables = [ProductoERP.__table__, MarcaVisibleExcepcion.__table__]
    with throwaway_schema("marcas_visibles", tables, ["CREATE TABLE usuarios (id INTEGER PRIMARY KEY)"]) as engine:
        session = Session(bind=engine)
        try:
            yield session
        finally:
            session.close()


def test_the_rule_is_one_statement_over_a_realistic_volume(pg_volume: Session) -> None:
    """60.000 products of 1.500 brands (a third without stock) and 50 exceptions: one grouped statement."""
    pg_db = pg_volume
    pg_db.execute(
        text("""
            INSERT INTO productos_erp (item_id, codigo, marca, stock)
            SELECT g, 'P' || g, 'Marca ' || (g % 1500), CASE WHEN g % 1500 < 500 THEN 0 ELSE g % 7 END
            FROM generate_series(1, 60000) AS g
        """)
    )
    pg_db.execute(
        text("INSERT INTO marcas_visibles_excepciones (marca) SELECT 'Marca ' || g FROM generate_series(0, 49) g")
    )
    pg_db.commit()
    pg_db.execute(text("ANALYZE productos_erp"))
    statements = []

    def count(*_args, **_kwargs) -> None:
        statements.append(1)

    conn = pg_db.connection()
    event.listen(conn, "before_cursor_execute", count)
    try:
        started = time.perf_counter()
        visibility = brand_visibility(pg_db)
        elapsed = time.perf_counter() - started
    finally:
        event.remove(conn, "before_cursor_execute", count)

    print(f"\nbrand_visibility over 60k products / 1.5k brands: {elapsed * 1000:.1f} ms")
    assert len(statements) == 1
    # Brands 500-1499 have stock; 0-499 have none, 0-49 of them are exceptions.
    assert visibility.is_visible("Marca 1499")
    assert visibility.is_visible("Marca 10")
    assert not visibility.is_visible("Marca 499")
    assert elapsed < 1.0
