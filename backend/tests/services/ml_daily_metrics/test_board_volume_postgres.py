"""ODD `metricas-ml-tablero` (performance round): the board on a realistic
volume, on real Postgres.

Seeded with `generate_series` (seconds, not minutes): 2.000 products, 6.000
publications and 90 days of daily rollup rows for them (~216k rows). Pins:

- a FIXED number of SQL statements per board request, the same for a page
  of 10, 50 or 200 rows and for either grouping -- nothing per row;
- the rows the database hands back stay proportional to the PAGE, never to
  the catalogue (the publications table is joined, never loaded whole);
- the page statement is answerable without a sequential scan of the rollup
  (EXPLAIN with `enable_seqscan = off`: the indexes it needs exist).

Timing is printed (`-s`) and recorded in the ODD doc, never asserted: a wall
clock bound would be flaky on a shared CI box. The statement count and the
plan are what regress loudly.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event, inspect as sa_inspect, text
from sqlalchemy.orm import sessionmaker

from app.routers.ml_metricas import build_board_response
from app.services.ml_daily_metrics import board

TODAY = date(2026, 9, 30)
NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
PRODUCTS = 2000
PUBLICATIONS = 6000
DAYS = 90

_PRODUCTOS_MIN_DDL = """
CREATE TABLE productos_erp (
    item_id INTEGER PRIMARY KEY,
    codigo VARCHAR(100),
    descripcion VARCHAR(500),
    marca VARCHAR(100),
    categoria VARCHAR(100),
    subcategoria_id INTEGER
)
"""


@pytest.fixture(scope="module")
def volume_session():
    from tests.conftest import (
        POSTGRES_TEST_URL,
        _patch_pg_types_for_sqlite,
        _postgres_reachable,
        _restore_pristine_pg_types,
    )

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")

    from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
    from app.models.ml_daily_metrics import MlProductDailyMetrics
    from app.models.ml_group_metrics import MlGroupMetrics
    from app.models.ml_order_item_costo import MlOrderItemCosto
    from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps

    tables = [
        MlOrdersOps.__table__,
        MlOrderItemOps.__table__,
        MlOrderItemCosto.__table__,
        MlGroupMetrics.__table__,
        MercadoLibreItemPublicado.__table__,
        MlProductDailyMetrics.__table__,
    ]
    _restore_pristine_pg_types(tables)
    engine = create_engine(POSTGRES_TEST_URL)
    created = [t for t in tables if not sa_inspect(engine).has_table(t.name)]
    for table in created:
        table.create(engine)
    created_productos = not sa_inspect(engine).has_table("productos_erp")
    if created_productos:
        with engine.begin() as conn:
            conn.execute(text(_PRODUCTOS_MIN_DDL))
    # Hand the shared Column types back to the SQLite suite (ARRAY -> JSON):
    # leaving them pristine breaks every SQLite test that runs after this
    # module in the same process.
    _patch_pg_types_for_sqlite()

    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    session.execute(
        text(
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id) "
            "SELECT 800000 + i, 'SKU-' || i, 'Producto de volumen ' || i, "
            "(ARRAY['Epson','Lenovo','Samsung','Sony','BGH'])[1 + i % 5], 'Cat', 1 + i % 7 "
            "FROM generate_series(1, :n) AS i"
        ),
        {"n": PRODUCTS},
    )
    session.execute(
        text(
            "INSERT INTO tb_mercadolibre_items_publicados (mlp_id, mlp_publicationid, item_id, "
            "mlp_official_store_id, mlp_laststatusid, mlp_listing_type_id, mlp_catalog_listing, "
            "mlp_is4fulfillment, mlp_itemtitle, mlp_thumbnail, mlp_start_time) "
            "SELECT 8000000 + i, 'MLA77' || lpad(i::text, 6, '0'), 800001 + (i % :p), "
            "(ARRAY[57997, 2645, 144, 191942, NULL])[1 + i % 5], (ARRAY[153, 153, 154, 155])[1 + i % 4], "
            "CASE WHEN i % 2 = 0 THEN 'gold_special' ELSE 'gold_pro' END, i % 7 = 0, i % 3 = 0, "
            "'Publicación ' || i, 'https://http2.mlstatic.com/' || i || '.jpg', TIMESTAMP '2026-03-01' "
            "FROM generate_series(1, :n) AS i"
        ),
        {"n": PUBLICATIONS, "p": PRODUCTS},
    )
    # ~40% of the publication-days sell: ~216k rollup rows.
    session.execute(
        text(
            "INSERT INTO ml_product_daily_metrics (product_item_id, mla, day, units, gross_ars, total_gauss, "
            "costo, orders, unresolved_orders, last_sale_at, updated_at) "
            "SELECT 800001 + (i % :p), 'MLA77' || lpad(i::text, 6, '0'), CAST(:today AS DATE) - d, "
            "1 + (i + d) % 4, 1000 * (1 + (i + d) % 4), 150 + (i % 50) - d % 30, 800, 1, 0, "
            "CAST(:today AS DATE) - d + TIME '15:00', now() "
            "FROM generate_series(1, :n) AS i, generate_series(0, :days - 1) AS d "
            "WHERE (i * 7 + d) % 5 < 2"
        ),
        {"n": PUBLICATIONS, "p": PRODUCTS, "today": TODAY, "days": DAYS},
    )
    session.execute(text("ANALYZE ml_product_daily_metrics"))
    session.execute(text("ANALYZE tb_mercadolibre_items_publicados"))
    session.execute(text("ANALYZE productos_erp"))
    yield session
    session.close()
    transaction.rollback()
    connection.close()
    for table in reversed(created):
        table.drop(engine, checkfirst=True)
    if created_productos:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS productos_erp"))
    engine.dispose()


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


class _Recorder:
    def __init__(self) -> None:
        self.statements: list[tuple[str, object]] = []
        self.rows_returned = 0
        self.timings: list[tuple[float, str]] = []
        self._t0 = 0.0

    def before(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append((statement, parameters))
        self._t0 = time.perf_counter()

    def after(self, conn, cursor, statement, parameters, context, executemany):
        self.timings.append(((time.perf_counter() - self._t0) * 1000, statement[:60].replace("\n", " ")))
        if statement.lstrip().upper().startswith(("SELECT", "WITH")) and cursor.rowcount and cursor.rowcount > 0:
            self.rows_returned += cursor.rowcount


def _request(session, **filters):
    f = board.BoardFilter(
        date_from=TODAY - timedelta(days=29),
        date_to=TODAY,
        **{k: v for k, v in filters.items() if k != "limit"},
    )
    recorder = _Recorder()
    connection = session.connection()
    event.listen(connection, "before_cursor_execute", recorder.before)
    event.listen(connection, "after_cursor_execute", recorder.after)
    started = time.perf_counter()
    try:
        response = build_board_response(session, f, limit=filters.get("limit", 50), offset=0, can_see_margin=True)
    finally:
        event.remove(connection, "before_cursor_execute", recorder.before)
        event.remove(connection, "after_cursor_execute", recorder.after)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return response, recorder, elapsed_ms


@pytest.mark.postgres
class TestBoardOnVolume:
    def test_fixed_statement_count_whatever_the_page_size(self, volume_session) -> None:
        counts = {}
        for limit in (10, 50, 200):
            response, recorder, elapsed_ms = _request(volume_session, limit=limit)
            assert len(response.rows) == limit
            assert response.total == PRODUCTS
            counts[limit] = len(recorder.statements)
            print(f"\nboard product limit={limit}: {counts[limit]} statements, {elapsed_ms:.0f} ms")
            for ms, head in recorder.timings:
                print(f"   {ms:7.1f} ms  {head}")
        _response, recorder, elapsed_ms = _request(volume_session, limit=50, group_by="publication")
        print(f"board publication limit=50: {len(recorder.statements)} statements, {elapsed_ms:.0f} ms")
        response, filtered, elapsed_ms = _request(
            volume_session, limit=50, stores=("2645",), marcas=("Samsung",), pub_status=("active",), q="volumen"
        )
        print(f"board filtered limit=50: {len(filtered.statements)} statements, {elapsed_ms:.0f} ms")
        for ms, head in filtered.timings:
            print(f"   {ms:7.1f} ms  {head}")
        empty, emptied, elapsed_ms = _request(volume_session, limit=50, alerts=("sin_ventas_30d",))
        print(f"board empty page: {len(emptied.statements)} statements, {elapsed_ms:.0f} ms")

        assert counts[10] == counts[50] == counts[200] == len(recorder.statements)
        assert response.rows and len(filtered.statements) == counts[50]
        # An empty page skips the two per-page statements (details, series).
        assert not empty.rows and len(emptied.statements) == counts[50] - 2
        assert counts[50] <= 17

    def test_rows_fetched_follow_the_page_not_the_catalogue(self, volume_session) -> None:
        _response, recorder, _ms = _request(volume_session, limit=10)

        # 10 rows, their pairs (~30), 10 x 90 series points, 30 KPI series
        # points, a handful of chip buckets. The old in-Python board read all
        # 6.000 publications and every rollup row of the period.
        print(f"\nrows returned by the database for a page of 10: {recorder.rows_returned}")
        assert recorder.rows_returned < 1500

    def test_page_statements_reach_the_rollup_through_its_indexes(self, volume_session) -> None:
        """The two per-page statements (pair details with the last sale
        timestamp, and the 90-day series) touch only the page's pairs: with
        the planner's DEFAULT settings they must go through an index of the
        rollup, never a sequential scan of it. Explained while the request's
        materialized pair table still exists."""
        f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY)
        recorder = _Recorder()
        connection = volume_session.connection()
        with board.Board(volume_session, f) as b:
            event.listen(connection, "before_cursor_execute", recorder.before)
            try:
                b.page(50)
            finally:
                event.remove(connection, "before_cursor_execute", recorder.before)
            cursor = connection.connection.cursor()
            plans = {}
            for statement, params in recorder.statements:
                if "ml_product_daily_metrics" not in statement:
                    continue
                cursor.execute("EXPLAIN " + statement, params)
                plans[statement[:40]] = "\n".join(row[0] for row in cursor.fetchall())

        assert len(plans) == 2, list(plans)
        for head, plan in plans.items():
            assert "Seq Scan on ml_product_daily_metrics" not in plan, f"{head}\n{plan}"
            assert "Index" in plan and "ml_product_daily_metrics" in plan, f"{head}\n{plan}"

    def test_freshness_read_is_an_index_edge_not_a_scan(self, volume_session) -> None:
        _response, recorder, _ms = _request(volume_session, limit=10)
        statement, params = next(
            (s, p) for s, p in recorder.statements if "max(ml_product_daily_metrics.updated_at)" in s
        )
        cursor = volume_session.connection().connection.cursor()
        cursor.execute("EXPLAIN " + statement, params)
        plan = "\n".join(row[0] for row in cursor.fetchall())

        assert "ix_ml_product_daily_metrics_updated_at" in plan, plan
