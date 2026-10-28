"""Métricas ML audit B8 -- the board's sales by shipping type ("Por tipo de envío").

Shipping type is a property of each SALE (its order's shipment), not of the product: every sold line takes its
order's logistic mode (`mode_resolution`'s cascade: the shipment's `logistic_type`, else "retiro" for an order
tagged `no_shipping`, else "desconocido"). Under the board's filters it sums the sold lines of the rows that survive
them, like the KPI strip. A pack whose orders ship differently counts as one operation in each of its modes.
"""

from __future__ import annotations

from itertools import product

import pytest
from sqlalchemy import BigInteger, Boolean, String, cast, column, select, text, values

from app.services.ml_daily_metrics import board
from app.services.ml_orders_ingestion.mode_resolution import modo_logistico_expr, resolve_modo_logistico
from tests.services.ml_daily_metrics import test_board_operaciones_postgres as operaciones
from tests.services.ml_daily_metrics.test_board_operaciones_postgres import PERIOD, _env  # noqa: F401

sales = operaciones.sales  # the same sold lines, live and persisted

pytestmark = pytest.mark.postgres


def _ship(db, order_id: int, shipment_id: int, logistic_type) -> None:
    db.execute(
        text("INSERT INTO ml_shipments_ops (shipment_id, order_id, logistic_type) VALUES (:s, :o, :t)"),
        {"s": shipment_id, "o": order_id, "t": logistic_type},
    )
    db.execute(text("UPDATE ml_orders_ops SET shipping_id = :s WHERE order_id = :o"), {"s": shipment_id, "o": order_id})


@pytest.fixture
def shipped(sales):
    """Order A (777 x2) ships Flex; order C (777 x7) has no shipment and is tagged `no_shipping`; pack P ships its
    order 914 (777 x1 + 778 x2) by Full and its order 915 (778 x1) by Colecta. Every unit is $100."""
    _ship(sales, 2000012345678911, 91, "self_service")
    sales.execute(text("UPDATE ml_orders_ops SET has_no_shipping_tag = true WHERE order_id = 2000012345678913"))
    _ship(sales, 2000012345678914, 94, "fulfillment")
    _ship(sales, 2000012345678915, 95, "cross_docking")
    sales.flush()
    return sales


def _by_shipping(db, **filters):
    with board.Board(db, board.BoardFilter(**PERIOD, **filters), scope_pairs=None) as b:
        return [(r.modo, r.operations, r.units, r.gross) for r in b.by_shipping()]


def test_each_sold_line_takes_its_orders_shipping_type(shipped) -> None:
    assert _by_shipping(shipped) == [
        ("retiro", 1, 7, 700),
        ("fulfillment", 1, 3, 300),
        ("self_service", 1, 2, 200),
        ("cross_docking", 1, 1, 100),
    ]


def test_a_filter_keeps_the_sales_of_the_rows_it_keeps(shipped) -> None:
    # Logi keeps 778: only pack P sells it, by Full (x2) and by Colecta (x1).
    assert _by_shipping(shipped, marcas=("Logi",)) == [("fulfillment", 1, 2, 200), ("cross_docking", 1, 1, 100)]


def test_a_sold_line_without_its_order_row_still_counts_as_unknown(shipped) -> None:
    # A sold line whose order row is gone (the persisted lines outlive it) stays in the breakdown, like it stays
    # in the KPI strip: the panel never sums less than Facturado.
    shipped.execute(text("DELETE FROM ml_orders_ops WHERE order_id = 2000012345678913"))
    shipped.flush()

    with board.Board(shipped, board.BoardFilter(**PERIOD), scope_pairs=None) as b:
        gross = b.kpis().gross
    rows = _by_shipping(shipped)

    assert sum(r[3] for r in rows) == gross
    assert set(rows) <= {
        ("desconocido", 1, 7, 700),
        ("fulfillment", 1, 3, 300),
        ("self_service", 1, 2, 200),
        ("cross_docking", 1, 1, 100),
    }


@pytest.mark.parametrize(
    ("has_shipment", "logistic_type", "tagged"),
    list(product([True, False], ["self_service", "drop_off", None, ""], [True, False, None])),
)
def test_the_sql_rule_is_the_resolvers(board_pg, has_shipment, logistic_type, tagged) -> None:
    row = values(
        column("shipment_id", BigInteger),
        column("logistic_type", String),
        column("tagged", Boolean),
        name="o",
    ).data([(1 if has_shipment else None, logistic_type, tagged)])
    sql = board_pg.execute(
        select(modo_logistico_expr(row.c.shipment_id, row.c.logistic_type, cast(row.c.tagged, Boolean)))
    ).scalar()

    expected = resolve_modo_logistico(
        shipment_logistic_type=logistic_type, has_shipment=has_shipment, tagged_no_shipping=bool(tagged)
    )
    assert sql == expected
