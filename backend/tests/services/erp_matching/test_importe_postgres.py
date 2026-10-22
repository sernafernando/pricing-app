"""PostgreSQL: the invoiced-lines snapshot also keeps the net amount and its currency.

Spec sell-in-sell-out T3g-1 (M1). `importe_neto` is the sum of
`it_qty * it_price * sd_plusorminus` over the invoice and its credit notes, in
the lines' own currency (`tb_item_transactions.curr_id`: measured on the ERP
mirror, an ARS-header invoice can carry USD-priced lines); `it_price` is
already net of the line discounts. Mixed currencies → importe and moneda NULL;
a negative net clamps at 0.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.services.erp_matching_service import copiar_lineas_facturadas, reconciliar_lineas_facturadas
from tests.services.erp_matching._schema import USD, filas, lf_schema, linea, nota_credito, pedido_con_factura

pytestmark = pytest.mark.postgres


@pytest.fixture
def eng() -> Iterator[Engine]:
    with lf_schema() as engine:
        yield engine


def _reconciliar(eng: Engine, pedido_id=1) -> int:
    with Session(eng) as session:
        cambios = reconciliar_lineas_facturadas(session, pedido_id)
        session.commit()
    return cambios


def test_an_invoice_stores_its_net_amount_and_currency_per_item(eng):
    with eng.begin() as conn:
        pedido_con_factura(conn)
        linea(conn, 1, 100, 501, "3", "10.005", USD)
        linea(conn, 2, 100, 501, "2", "10", USD)
        linea(conn, 3, 100, 502, "7", "1.50", USD)

    _reconciliar(eng)

    # 3 x 10.005 + 2 x 10 = 50.015 → 50.02 (ROUND half away from zero on numeric).
    assert filas(eng) == [(1, 501, 5, "50.02", "USD"), (1, 502, 7, "10.50", "USD")]


def test_the_currency_is_the_lines_one_not_the_invoice_header(eng):
    # Measured on the mirror: ARS header (curr_id_transaction=1), USD-priced lines.
    with eng.begin() as conn:
        pedido_con_factura(conn, curr=1)
        linea(conn, 1, 100, 501, "2", "100", USD)

    _reconciliar(eng)

    assert filas(eng) == [(1, 501, 2, "200.00", "USD")]


def test_a_credit_note_in_the_same_currency_lowers_the_amount(eng):
    with eng.begin() as conn:
        pedido_con_factura(conn)
        nota_credito(conn)
        linea(conn, 1, 100, 501, "10", "100", 1)
        linea(conn, 2, 200, 501, "1", "100", 1)

    _reconciliar(eng)

    assert filas(eng) == [(1, 501, 9, "900.00", "ARS")]


def test_mixed_currencies_leave_amount_and_currency_null(eng):
    with eng.begin() as conn:
        pedido_con_factura(conn)
        nota_credito(conn)
        linea(conn, 1, 100, 501, "10", "100", 1)
        linea(conn, 2, 200, 501, "1", "0.07", USD)
        linea(conn, 3, 100, 502, "4", "5", USD)

    _reconciliar(eng)

    assert filas(eng) == [(1, 501, 9, None, None), (1, 502, 4, "20.00", "USD")]


@pytest.mark.parametrize(
    ("price", "curr"),
    [(None, USD), ("5", None), ("5", 3)],
    ids=["price-null", "currency-null", "currency-unknown"],
)
def test_a_line_without_price_or_known_currency_leaves_amount_and_currency_null(eng, price, curr):
    with eng.begin() as conn:
        pedido_con_factura(conn)
        linea(conn, 1, 100, 501, "2", "5", USD)
        linea(conn, 2, 100, 501, "1", price, curr)

    _reconciliar(eng)

    assert filas(eng) == [(1, 501, 3, None, None)]


def test_a_negative_net_amount_clamps_to_zero(eng):
    # 2 units at 10 invoiced, 1 returned at 30: one unit left, amount -10 → 0.
    with eng.begin() as conn:
        pedido_con_factura(conn)
        nota_credito(conn)
        linea(conn, 1, 100, 501, "2", "10", USD)
        linea(conn, 2, 200, 501, "1", "30", USD)

    _reconciliar(eng)

    assert filas(eng) == [(1, 501, 1, "0.00", "USD")]


def test_an_unchanged_reconcile_changes_nothing(eng):
    with eng.begin() as conn:
        pedido_con_factura(conn)
        linea(conn, 1, 100, 501, "2", "10", USD)
        linea(conn, 2, 100, 502, "1", "10", 1)
        linea(conn, 3, 100, 503, "1", None, USD)

    assert _reconciliar(eng) == 3
    assert _reconciliar(eng) == 0


@pytest.mark.parametrize(
    ("cambio", "esperado"),
    [
        ("UPDATE tb_item_transactions SET it_price = 12 WHERE it_transaction = 1", (1, 501, 2, "24.00", "USD")),
        ("UPDATE tb_item_transactions SET curr_id = 1 WHERE it_transaction = 1", (1, 501, 2, "20.00", "ARS")),
        ("UPDATE tb_item_transactions SET it_price = NULL WHERE it_transaction = 1", (1, 501, 2, None, None)),
    ],
    ids=["amount", "currency", "to-null"],
)
def test_a_reconcile_updates_amount_or_currency_when_only_they_changed(eng, cambio, esperado):
    with eng.begin() as conn:
        pedido_con_factura(conn)
        linea(conn, 1, 100, 501, "2", "10", USD)
    _reconciliar(eng)

    with eng.begin() as conn:
        conn.execute(text(cambio))

    assert _reconciliar(eng) == 1
    assert filas(eng) == [esperado]


def test_the_copy_to_a_corrected_clone_carries_amount_and_currency(eng):
    with eng.begin() as conn:
        pedido_con_factura(conn)
        linea(conn, 1, 100, 501, "2", "10", USD)
        linea(conn, 2, 100, 502, "1", None, USD)
        conn.execute(text("INSERT INTO pedidos_compra (id, ct_transaction_id, corregido_desde_id) VALUES (2, 100, 1)"))
    _reconciliar(eng)

    with Session(eng) as session:
        copiar_lineas_facturadas(session, origen_id=1, destino_id=2)
        session.commit()

    assert [f for f in filas(eng) if f[0] == 2] == [(2, 501, 2, "20.00", "USD"), (2, 502, 1, None, None)]
