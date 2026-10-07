"""ODD `metricas-ml-tablero`, "Sin tabla resumen" ST2: a product's
publication sub-rows read ONLY that product's sales and publications.

Production symptom: opening a product's publications took seconds, because
the sub-row endpoint rebuilt the WHOLE board aggregate (every product) to
show one. Proof here, on real Postgres, with the same product before and
after 300 other products (900 publications, thousands of sales) appear:

- the same number of statements, and the request's temp tables hold the
  same rows -- the other products never enter the computation;
- every source table hands the plan only this product's rows (EXPLAIN
  ANALYZE with sequential scans off, i.e. along the index path): the
  product is reached through `ml_order_item_costos.producto_item_id` and
  its publications through `item_id`/`mlp_publicationid`, never by reading
  everybody's and filtering.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import event, text

from app.core.config import settings
from app.services.ml_daily_metrics import board

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 30)
PRODUCT = 500001
SOURCE_TABLES = (
    "ml_group_metrics",
    "ml_orders_ops",
    "ml_order_items_ops",
    "ml_order_item_costos",
    "tb_mercadolibre_items_publicados",
)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


def _seed_products(db, first: int, count: int, sales_per_mla: int, days_ago: int = 0) -> None:
    """`count` products from `first`, 3 publications each, and
    `sales_per_mla` lone-order sales per publication over 120 days ending
    `days_ago` days back."""
    db.execute(
        text(
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id) "
            "SELECT :first + p, 'SKU-' || (:first + p), 'Producto ' || (:first + p), 'Marca', 'Cat', 1 "
            "FROM generate_series(0, :count - 1) AS p"
        ),
        {"first": first, "count": count},
    )
    db.execute(
        text(
            "INSERT INTO tb_mercadolibre_items_publicados (mlp_id, mlp_publicationid, item_id, "
            "mlp_official_store_id, mlp_laststatusid, mlp_listing_type_id, mlp_itemtitle, mlp_start_time) "
            "SELECT (:first + p) * 10 + m, 'MLA' || ((:first + p) * 10 + m), :first + p, 57997, 153, "
            "'gold_special', 'Pub ' || ((:first + p) * 10 + m), TIMESTAMP '2026-01-01' "
            "FROM generate_series(0, :count - 1) AS p, generate_series(1, 3) AS m"
        ),
        {"first": first, "count": count},
    )
    sales = "FROM generate_series(0, :count - 1) AS p, generate_series(1, 3) AS m, generate_series(1, :n) AS s"
    order_id = "(7000000000000000 + ((CAST(:first AS BIGINT) + p) * 10 + m) * 1000 + s)"
    params = {"first": first, "count": count, "n": sales_per_mla, "now": NOW, "ago": days_ago}
    db.execute(
        text(
            "INSERT INTO ml_orders_ops (order_id, status, ml_last_updated, date_created, seller_id, currency_id) "
            f"SELECT {order_id}, 'paid', :now, :now, 999, 'ARS' {sales}"
        ),
        params,
    )
    db.execute(
        text(
            "INSERT INTO ml_order_items_ops (order_id, item_id, quantity, unit_price) "
            f"SELECT {order_id}, 'MLA' || ((:first + p) * 10 + m), 1 + s % 3, 100 {sales}"
        ),
        params,
    )
    db.execute(
        text(
            "INSERT INTO ml_order_item_costos (order_id, item_id, costo_origen, moneda, costo_unitario_ars, "
            "iva_pct, precio_unitario, fuente, producto_item_id) "
            f"SELECT {order_id}, 'MLA' || ((:first + p) * 10 + m), 50, 'ARS', 50, 21, 100, 't', :first + p {sales}"
        ),
        params,
    )
    db.execute(
        text(
            "INSERT INTO ml_order_metrics (order_id, total_gauss, costo_mercaderia, gauss_status, "
            "formula_version, computed_at) "
            f"SELECT {order_id}, 20, 50, 'ok', 2, :now {sales}"
        ),
        params,
    )
    db.execute(
        text(
            "INSERT INTO ml_group_metrics (group_key, gauss_status, member_order_ids, group_date, "
            "formula_version, computed_at) "
            f"SELECT 'o:' || {order_id}, 'ok', ARRAY[{order_id}]::BIGINT[], "
            f":now - make_interval(days => :ago + (s * 7 + m) % 120, hours => s % 20), 2, :now {sales}"
        ),
        params,
    )
    for name in SOURCE_TABLES + ("productos_erp", "ml_order_metrics"):
        db.execute(text(f"ANALYZE {name}"))


def _rows_read(node: dict, read: Counter) -> None:
    """Rows each SOURCE table handed to the plan (actual rows x loops of
    every scan node on it)."""
    if node.get("Relation Name") in SOURCE_TABLES:
        read[node["Relation Name"]] += node["Actual Rows"] * node["Actual Loops"]
    for child in node.get("Plans", ()):
        _rows_read(child, read)


def _subrows(db, product: int = PRODUCT):
    """What `GET /board/products/{id}/publications` runs, recorded: every
    statement, the rows each temp table got, and (inside the Board, while
    the temp tables exist) the plan of each source read."""
    f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY)
    by_pub = replace(f, group_by="publication", alerts=())
    statements, created = [], {}
    connection = db.connection()

    def after(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))
        if statement.startswith("CREATE TEMPORARY TABLE"):
            created[statement.split()[3]] = cursor.rowcount

    event.listen(connection, "after_cursor_execute", after)
    started = time.perf_counter()
    try:
        with board.Board(db, by_pub, product_item_id=product, scope_pairs=None) as b:
            rows = b.page(limit=None, apply_alerts=False)
            elapsed_ms = (time.perf_counter() - started) * 1000
            event.remove(connection, "after_cursor_execute", after)
            read: Counter = Counter()
            cursor = connection.connection.cursor()
            # On a few hundred rows a sequential scan is the planner's
            # cheapest choice; production tables are far bigger. Seq scans
            # off proves the NARROW path exists: reading only this product.
            cursor.execute("SET LOCAL enable_seqscan = off")
            for statement, params in statements:
                if statement.startswith("CREATE TEMPORARY TABLE"):
                    cursor.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + statement.split(" AS ", 1)[1], params)
                    _rows_read(cursor.fetchone()[0][0]["Plan"], read)
            cursor.execute("SET LOCAL enable_seqscan = on")
    finally:
        if event.contains(connection, "after_cursor_execute", after):
            event.remove(connection, "after_cursor_execute", after)
    return rows, statements, created, read, elapsed_ms


@pytest.mark.postgres
def test_subrows_cost_does_not_depend_on_other_products(board_pg) -> None:
    db = board_pg
    _seed_products(db, PRODUCT, 1, sales_per_mla=4)
    alone_rows, alone_statements, alone_created, alone_read, alone_ms = _subrows(db)

    _seed_products(db, PRODUCT + 1, 300, sales_per_mla=12)
    rows, statements, created, read, ms = _subrows(db)

    print(f"\nsub-rows alone: {len(alone_statements)} statements, {alone_created}, {alone_ms:.0f} ms, {alone_read}")
    print(f"sub-rows among 300 products: {len(statements)} statements, {created}, {ms:.0f} ms, {read}")
    assert [(r.key, r.units, r.tg) for r in rows] == [(r.key, r.units, r.tg) for r in alone_rows]
    assert {r.key for r in rows} == {f"MLA{PRODUCT * 10 + m}" for m in (1, 2, 3)}
    assert len(statements) == len(alone_statements)
    assert created == alone_created
    # The other products' rows are never read: they hold 900 publications
    # and 10.800 orders; this product, 3 and 12. Index nested loops may
    # visit a row more than once, so the bound is loose but far from a scan.
    assert all(n < 200 for n in read.values()), read


def _seed_unpriced_sales(db) -> None:
    """Six recent sales of two MLAs whose items never got a frozen cost: the
    "sin producto" (product 0) row."""
    for n in range(6):
        order_id = 7900000000000000 + n
        mla = f"MLA79000000{n % 2}"
        db.execute(
            text(
                "INSERT INTO ml_orders_ops (order_id, status, ml_last_updated, date_created, seller_id, currency_id) "
                "VALUES (:o, 'paid', :now, :now, 999, 'ARS')"
            ),
            {"o": order_id, "now": NOW},
        )
        db.execute(
            text("INSERT INTO ml_order_items_ops (order_id, item_id, quantity, unit_price) VALUES (:o, :mla, 1, 100)"),
            {"o": order_id, "mla": mla},
        )
        db.execute(
            text(
                "INSERT INTO ml_group_metrics (group_key, gauss_status, member_order_ids, group_date, "
                "formula_version, computed_at) VALUES ('o:' || CAST(:o AS TEXT), 'ok', ARRAY[CAST(:o AS BIGINT)], "
                ":gd, 2, :now)"
            ),
            {"o": order_id, "gd": NOW - timedelta(days=n + 1), "now": NOW},
        )


@pytest.mark.postgres
def test_product_zero_subrows_never_read_other_products_history(board_pg) -> None:
    """Product 0 ("sin producto": items with no frozen cost row) has no
    product index to go through. Its sub-rows read only the request's
    accreditation window (period, comparison, 90-day series, 24h), never the
    whole history -- 300 other products' older sales are never read."""
    db = board_pg
    _seed_unpriced_sales(db)
    alone_rows, alone_statements, alone_created, alone_read, alone_ms = _subrows(db, product=0)

    _seed_products(db, PRODUCT + 1, 300, sales_per_mla=12, days_ago=200)
    rows, statements, created, read, ms = _subrows(db, product=0)

    print(
        f"\nproduct-0 sub-rows alone: {len(alone_statements)} statements, {alone_created}, {alone_ms:.0f} ms, {alone_read}"
    )
    print(f"product-0 sub-rows among 300 products: {len(statements)} statements, {created}, {ms:.0f} ms, {read}")
    assert {r.key for r in rows} == {"MLA790000000", "MLA790000001"}
    assert [(r.key, r.units) for r in rows] == [(r.key, r.units) for r in alone_rows]
    assert len(statements) == len(alone_statements)
    assert created == alone_created
    assert all(n < 200 for n in read.values()), read
