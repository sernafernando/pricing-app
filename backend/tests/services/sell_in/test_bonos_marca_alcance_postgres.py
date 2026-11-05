"""The bonus list's Marca filter (`marcas`) by scope, on Postgres (campanas-sistema S4, orchestrator 2026-11-02:
"when a brand is picked, return every bono whose scope reaches that brand (marca, categoria, modelos, operacion),
reusing the existing scope logic").

A bonus reaches a brand when its scope (`bonos_alcance.del_alcance`'s rule) reaches a product of that brand:
- a 'marca' bonus, its own brand;
- a 'categoria' bonus, a catalog product of its category and that brand;
- a 'modelos' bonus, one of its models of that brand;
- a 'factura' bonus, a product of that brand on its operation, invoiced or received.

A 'factura' bonus whose operation has no invoiced or received line yet (or no operation) cannot be resolved to a
brand from its stored data: it stays in the list whatever brand is picked.
"""

from __future__ import annotations


import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.sell_in import bonos_crud
from tests.services.sell_in._bonos_schema import bonos_schema

pytestmark = pytest.mark.postgres

_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY, numero VARCHAR(32) NOT NULL)",
    "CREATE TABLE productos_erp (item_id INTEGER PRIMARY KEY, marca VARCHAR(100), categoria VARCHAR(100))",
    "CREATE TABLE pedido_compra_lineas_facturadas (id BIGSERIAL PRIMARY KEY, pedido_id BIGINT, item_id INTEGER)",
    "CREATE TABLE pedido_compra_ingresos (id BIGSERIAL PRIMARY KEY, pedido_id BIGINT, item_id INTEGER)",
    "INSERT INTO usuarios VALUES (7)",
    "INSERT INTO productos_erp VALUES (2964, 'TP-LINK', 'Routers'), (950, 'MERCUSYS', 'Routers'),"
    " (3100, 'EPSON', 'Impresoras')",
    "INSERT INTO pedidos_compra VALUES (501, 'OC-501'), (502, 'OC-502'), (503, 'OC-503')",
    "INSERT INTO pedido_compra_lineas_facturadas (pedido_id, item_id) VALUES (501, 2964)",
    "INSERT INTO pedido_compra_ingresos (pedido_id, item_id) VALUES (502, 3100)",
]


def _schema():
    return bonos_schema("sell_in_bm", ["tacticals", "sell_in_bonos_marca", "sell_in_bono_items"], _STUBS)


def _bono(conn, alcance: str, *, marca=None, categoria=None, pedido_id=None, modelos=()) -> int:
    bono_id = conn.execute(
        text(
            "INSERT INTO sell_in_bonos_marca (alcance, marca, categoria, pedido_id, tipo, monto_unit, moneda,"
            " fecha_desde, fecha_hasta, base, incluye_iva, acumulable, descripcion, estado, usuario_id)"
            " VALUES (:alcance, :marca, :categoria, :pedido_id, 'por_unidad', 1, 'USD', DATE '2026-10-01',"
            " DATE '2026-12-31', 'factura', false, true, :alcance, 'activa', 7) RETURNING id"
        ),
        {"alcance": alcance, "marca": marca, "categoria": categoria, "pedido_id": pedido_id},
    ).scalar_one()
    for item_id in modelos:
        conn.execute(
            text("INSERT INTO sell_in_bono_items (bono_id, item_id) VALUES (:b, :i)"), {"b": bono_id, "i": item_id}
        )
    return bono_id


@pytest.fixture(scope="module")
def pg():
    with _schema() as eng:
        with eng.begin() as conn:
            ids = {
                "marca": _bono(conn, "marca", marca="TP-LINK"),
                "categoria": _bono(conn, "categoria", categoria="Routers"),
                "modelos": _bono(conn, "modelos", modelos=(950,)),
                "factura_facturada": _bono(conn, "factura", pedido_id=501),
                "factura_recibida": _bono(conn, "factura", pedido_id=502),
                "factura_sin_lineas": _bono(conn, "factura", pedido_id=503),
            }
        yield eng, ids


def _listar(eng, **filtros) -> set[int]:
    with Session(bind=eng, autoflush=False) as db:
        bonos, total = bonos_crud.listar_bonos(db, bonos_crud.FiltrosBonos(**filtros))
    assert total == len(bonos)
    return {b.id for b in bonos}


def _de(ids, *keys) -> set[int]:
    return {ids[k] for k in keys}


def test_a_brand_bonus_reaches_its_own_brand(pg):
    eng, ids = pg
    assert ids["marca"] in _listar(eng, marcas=["TP-LINK"])
    assert ids["marca"] not in _listar(eng, marcas=["EPSON"])


def test_a_category_bonus_reaches_the_brands_of_its_category_products(pg):
    eng, ids = pg
    assert ids["categoria"] in _listar(eng, marcas=["TP-LINK"])
    assert ids["categoria"] in _listar(eng, marcas=["MERCUSYS"])
    assert ids["categoria"] not in _listar(eng, marcas=["EPSON"])


def test_a_models_bonus_reaches_the_brands_of_its_models(pg):
    eng, ids = pg
    assert ids["modelos"] in _listar(eng, marcas=["MERCUSYS"])
    assert ids["modelos"] not in _listar(eng, marcas=["TP-LINK"])


def test_an_operation_bonus_reaches_the_brands_invoiced_on_its_operation(pg):
    eng, ids = pg
    assert ids["factura_facturada"] in _listar(eng, marcas=["TP-LINK"])
    assert ids["factura_facturada"] not in _listar(eng, marcas=["EPSON"])


def test_an_operation_bonus_not_invoiced_yet_reaches_the_brands_received(pg):
    eng, ids = pg
    assert ids["factura_recibida"] in _listar(eng, marcas=["EPSON"])
    assert ids["factura_recibida"] not in _listar(eng, marcas=["TP-LINK"])


def test_an_operation_bonus_with_no_lines_cannot_be_resolved_and_stays_under_any_brand(pg):
    eng, ids = pg
    assert ids["factura_sin_lineas"] in _listar(eng, marcas=["TP-LINK"])
    assert ids["factura_sin_lineas"] in _listar(eng, marcas=["SAMSUNG"])


def test_the_whole_answer_per_brand_and_several_brands_add_up(pg):
    eng, ids = pg
    assert _listar(eng, marcas=["EPSON"]) == _de(ids, "factura_recibida", "factura_sin_lineas")
    assert _listar(eng, marcas=["TP-LINK", "EPSON"]) == _de(
        ids, "marca", "categoria", "factura_facturada", "factura_recibida", "factura_sin_lineas"
    )
    # The exact `marca` param keeps matching only the bonus's own brand, as before.
    assert _listar(eng, marca="TP-LINK") == _de(ids, "marca")
