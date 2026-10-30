"""The sell-in lot viewer of a product against real tables: its active purchase lines in the order `fifo.asignar`
consumes them, each with the units the stored consumptions took and a status that agrees with `costing.vigentes`;
and each line's consumptions, paginated."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.services.sell_in import visor_lotes
from app.services.sell_in.costing import get_costing
from tests.services.sell_in import _world as w

pytestmark = pytest.mark.postgres

HOY = date(2026, 10, 20)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_in_visor_lotes") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _mundo(engine: Engine) -> dict[str, int]:
    """Five lines of product 950, created out of FIFO order: a used-up one, the current one, two queued ones with
    different discounts (one in USD) and one counting from a future goods receipt; plus another product's line."""
    (futura,) = w.compra(
        engine, [(950, 5, "50.00")], date(2026, 10, 2), cuenta_desde="ingreso", fecha_ingreso=date(2026, 11, 3)
    )
    (en_cola,) = w.compra(engine, [(950, 4, "40.00")], date(2026, 10, 10))
    (vigente,) = w.compra(engine, [(950, 3, "100.00")], date(2026, 10, 5))
    (usd,) = w.compra(engine, [(950, 1, "10.00")], date(2026, 10, 8), moneda="USD", tipo_cambio="1000")
    (agotada,) = w.compra(engine, [(950, 2, "200.00")], date(2026, 10, 1))
    w.compra(engine, [(2964, 9, "90.00")], date(2026, 10, 1))
    # Three units sold on 10/06: the two of the 10/01 line, then one of the 10/05 line.
    w.venta(engine, "fuera", 950, 3, date(2026, 10, 6))
    with sessionmaker(bind=engine)() as db:
        get_costing().recompute(db, [950, 2964])
        db.commit()
    return {"agotada": agotada, "vigente": vigente, "usd": usd, "en_cola": en_cola, "futura": futura}


def test_the_lines_come_in_fifo_order_with_the_status_vigentes_agrees_with(engine: Engine) -> None:
    ids = _mundo(engine)

    with sessionmaker(bind=engine)() as db:
        visor = visor_lotes.lotes_de_producto(db, 950, HOY)
        vigente = get_costing().vigentes(db, [950], HOY)[950]

    filas = [(x.compra_item_id, x.estado, x.cantidad, x.consumidas, x.restantes) for x in visor.lotes]
    assert filas == [
        (ids["agotada"], "agotado", 2, 2, 0),
        (ids["vigente"], "vigente", 3, 1, 2),
        (ids["usd"], "en_cola", 1, 0, 1),
        (ids["en_cola"], "en_cola", 4, 0, 4),
        (ids["futura"], "desde", 5, 0, 5),
    ]
    assert [x.numero for x in visor.lotes] == [1, 2, 3, 4, 5]
    assert vigente.compra_item_id == ids["vigente"]
    # Rounded like `split.unit_discount` (6 decimals, half up); the USD line at its purchase's rate.
    assert [x.descuento_unit for x in visor.lotes] == [
        Decimal("100.000000"),
        Decimal("33.333333"),
        Decimal("10000.000000"),
        Decimal("10.000000"),
        Decimal("10.000000"),
    ]
    assert [x.fecha_desde for x in visor.lotes] == [
        date(2026, 10, 1),
        date(2026, 10, 5),
        date(2026, 10, 8),
        date(2026, 10, 10),
        date(2026, 11, 3),
    ]
    assert visor.lotes[2].moneda == "USD"


def test_the_next_sale_takes_the_current_line_then_the_next_one_with_units(engine: Engine) -> None:
    ids = _mundo(engine)

    with sessionmaker(bind=engine)() as db:
        proxima = visor_lotes.lotes_de_producto(db, 950, HOY).proxima

    assert (proxima.numero, proxima.compra_item_id) == (2, ids["vigente"])
    assert (proxima.descuento_unit, proxima.restantes) == (Decimal("33.333333"), 2)
    assert (proxima.siguiente.numero, proxima.siguiente.descuento_unit) == (3, Decimal("10000.000000"))


def test_a_product_with_every_line_used_up_has_no_next_sale_line(engine: Engine) -> None:
    w.compra(engine, [(950, 2, "200.00")], date(2026, 10, 1))
    w.venta(engine, "fuera", 950, 2, date(2026, 10, 6))
    with sessionmaker(bind=engine)() as db:
        get_costing().recompute(db, [950])
        db.commit()

    with sessionmaker(bind=engine)() as db:
        visor = visor_lotes.lotes_de_producto(db, 950, HOY)

    assert [x.estado for x in visor.lotes] == ["agotado"]
    assert visor.proxima is None


def test_a_voided_purchase_is_not_a_lot(engine: Engine) -> None:
    w.compra(engine, [(950, 2, "200.00")], date(2026, 10, 1), estado="anulada")

    with sessionmaker(bind=engine)() as db:
        visor = visor_lotes.lotes_de_producto(db, 950, HOY)

    assert (visor.lotes, visor.proxima) == ([], None)


def test_the_consumptions_of_a_line_are_paginated_oldest_sale_first(engine: Engine) -> None:
    (linea,) = w.compra(engine, [(950, 9, "90.00")], date(2026, 10, 1))
    refs = [w.venta(engine, "fuera", 950, 1, date(2026, 10, d)) for d in (4, 2, 3)]
    with sessionmaker(bind=engine)() as db:
        get_costing().recompute(db, [950])
        db.commit()

    with sessionmaker(bind=engine)() as db:
        primera, total = visor_lotes.consumos_de_lote(db, 950, linea, page=1, page_size=2)
        segunda, _ = visor_lotes.consumos_de_lote(db, 950, linea, page=2, page_size=2)
        ajena, ninguno = visor_lotes.consumos_de_lote(db, 2964, linea, page=1, page_size=2)

    assert total == 3
    assert [(c.canal, c.venta_ref, c.fecha_venta, c.unidades) for c in primera + segunda] == [
        ("fuera", refs[1], date(2026, 10, 2), 1),
        ("fuera", refs[2], date(2026, 10, 3), 1),
        ("fuera", refs[0], date(2026, 10, 4), 1),
    ]
    assert primera[0].descuento_ars == Decimal("10.00")
    # A line of another product answers nothing, never that line's sales.
    assert (ajena, ninguno) == ([], 0)


def test_each_line_names_its_purchase_supplier_and_invoices(engine: Engine) -> None:
    (linea,) = w.compra(engine, [(950, 2, "20.00")], date(2026, 10, 1))
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO proveedores (id, nombre) VALUES (31, 'Gauss SA')"))
        conn.execute(text("INSERT INTO pedidos_compra (id, numero, numero_factura) VALUES (71, 'OC-1', 'A-0001-1')"))
        conn.execute(text("INSERT INTO pedidos_compra (id, numero, numero_factura) VALUES (72, 'OC-2', NULL)"))
        compra_id = conn.execute(
            text("SELECT compra_id FROM sell_in_compra_items WHERE id = :l"), {"l": linea}
        ).scalar()
        conn.execute(text("UPDATE sell_in_compras SET proveedor_id = 31 WHERE id = :c"), {"c": compra_id})
        for pedido in (71, 72):
            conn.execute(
                text("INSERT INTO sell_in_compra_pedidos (compra_id, pedido_compra_id) VALUES (:c, :p)"),
                {"c": compra_id, "p": pedido},
            )

    with sessionmaker(bind=engine)() as db:
        (lote,) = visor_lotes.lotes_de_producto(db, 950, HOY).lotes

    assert (lote.compra_id, lote.proveedor, lote.facturas) == (compra_id, "Gauss SA", ["A-0001-1"])


def test_a_purchase_a_bonus_generated_names_the_invoice_of_its_operation(engine: Engine) -> None:
    (linea,) = w.compra(engine, [(950, 2, "20.00")], date(2026, 10, 1))
    with engine.begin() as conn:
        bono = conn.execute(
            text(
                "INSERT INTO sell_in_bonos_marca (marca, tipo, monto_unit, moneda, fecha_desde, fecha_hasta, usuario_id) "
                "VALUES ('MERCUSYS', 'por_unidad', 10, 'ARS', '2026-10-01', '2026-10-31', 7) RETURNING id"
            )
        ).scalar()
        conn.execute(text("INSERT INTO pedidos_compra (id, numero, numero_factura) VALUES (81, 'OC-9', 'B-0002-9')"))
        conn.execute(
            text(
                "UPDATE sell_in_compras SET origen = 'bono_marca', bono_id = :b, bono_pedido_id = 81 "
                "WHERE id = (SELECT compra_id FROM sell_in_compra_items WHERE id = :l)"
            ),
            {"b": bono, "l": linea},
        )
    try:
        with sessionmaker(bind=engine)() as db:
            (lote,) = visor_lotes.lotes_de_producto(db, 950, HOY).lotes

        assert lote.facturas == ["B-0002-9"]
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM sell_in_compras"))
            conn.execute(text("DELETE FROM sell_in_bonos_marca"))
            conn.execute(text("DELETE FROM pedidos_compra"))
