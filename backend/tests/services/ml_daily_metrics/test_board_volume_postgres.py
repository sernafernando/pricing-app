"""ODD `metricas-ml-tablero` ("Sin tabla resumen" ST3): the board on a
realistic volume, on real Postgres, read straight from the orders.

Seeded with `generate_series` (seconds, not minutes): 2.000 products, 6.000
publications and 81.000 groups over 18 months -- every day of the last 90
has sales (20.000 groups, ~220 a day; ~135 a day before that) -- with packs (every 10th group, two orders), multi-item orders
(every 7th), cancellations, unresolved metrics and orders being recalculated.
Pins:

- a FIXED number of SQL statements per board request, the same for a page
  of 10, 50 or 200 rows and for either grouping -- nothing per row;
- the rows the database hands back stay proportional to the PAGE, never to
  the catalogue;
- the windows are nested on every row (24h <= 3d <= 7d <= 15d <= 30d) and
  the period's units equal an independent count over the orders;
- the request's lines are reached through the group-date index.

Timing is printed (`-s`) and recorded in the ODD doc, never asserted: a wall
clock bound would be flaky on a shared CI box. The statement count and the
plan are what regress loudly.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
import time
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.routers.ml_metricas import build_board_response
from app.services.ml_daily_metrics import board, groups

TODAY = date(2026, 9, 30)
NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
PRODUCTS = 2000
PUBLICATIONS = 6000
GROUPS = 81000
DENSE_GROUPS = 20000

# One row per order: `g` (its group), `order_id`, `k` (its MLA's index).
_MEMBERS = """
(SELECT g, 3000000000000000 + g AS order_id, (g * 7919) % 6000 + 1 AS k FROM generate_series(CAST(1 AS BIGINT), :groups) AS g
 UNION ALL
 SELECT g, 3500000000000000 + g, (g * 104729) % 6000 + 1 FROM generate_series(CAST(10 AS BIGINT), :groups, 10) AS g) AS m
"""
# One row per sold item: every order sells its MLA; every 7th group's orders
# sell a second one.
_ITEMS = f"""
(SELECT order_id, g, k, 1 + g % 3 AS qty, 1000 + (k % 50) * 10 AS price FROM {_MEMBERS}
 UNION ALL
 SELECT order_id, g, (k * 31) % 6000 + 1, 1, 500 FROM {_MEMBERS} WHERE g % 7 = 0) AS it
"""
_MLA = "'MLA77' || lpad(CAST(k AS TEXT), 6, '0')"


def _seed(session) -> None:
    p = {"groups": GROUPS, "dense": DENSE_GROUPS, "now": NOW, "n": PUBLICATIONS, "p": PRODUCTS}
    session.execute(
        text(
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id, stock) "
            "SELECT 800000 + i, 'SKU-' || i, 'Producto de volumen ' || i, "
            "(ARRAY['Epson','Lenovo','Samsung','Sony','BGH'])[1 + i % 5], 'Cat' || (i % 7 % 3), 1 + i % 7, "
            "CASE WHEN i % 11 = 0 THEN NULL ELSE i % 5 - 1 END "
            "FROM generate_series(1, :p) AS i"
        ),
        p,
    )
    session.execute(
        text(
            "INSERT INTO tb_mercadolibre_items_publicados (mlp_id, mlp_publicationid, item_id, "
            "mlp_official_store_id, mlp_laststatusid, mlp_listing_type_id, mlp_catalog_listing, "
            "mlp_is4fulfillment, mlp_itemtitle, mlp_thumbnail, mlp_start_time) "
            "SELECT 8000000 + i, 'MLA77' || lpad(i::text, 6, '0'), 800001 + (i % :p), "
            "(ARRAY[57997, 2645, 144, 191942, NULL])[1 + i % 5], (ARRAY[153, 153, 154, 155])[1 + i % 4], "
            "CASE WHEN i % 2 = 0 THEN 'gold_special' ELSE 'gold_pro' END, i % 7 = 0, i % 3 = 0, "
            "'Publicación ' || i, 'https://http2.mlstatic.com/' || i || '.jpg', TIMESTAMP '2025-01-01' "
            "FROM generate_series(1, :n) AS i"
        ),
        p,
    )
    session.execute(
        text(
            "INSERT INTO ml_group_metrics (group_key, gauss_status, member_order_ids, group_date, "
            "formula_version, computed_at) "
            "SELECT CASE WHEN g % 10 = 0 THEN 'p:' || (4000000000000000 + g) ELSE 'o:' || (3000000000000000 + g) END, "
            "'ok', CASE WHEN g % 10 = 0 THEN ARRAY[3000000000000000 + g, 3500000000000000 + g] "
            "ELSE ARRAY[3000000000000000 + g] END, "
            ":now - make_interval(days => CASE WHEN g <= :dense THEN g % 90 ELSE 90 + (g - :dense) % 450 END, "
            "secs => (g * 37) % 86400), 2, :now "
            "FROM generate_series(1, :groups) AS g"
        ),
        p,
    )
    session.execute(
        text(
            "INSERT INTO ml_orders_ops (order_id, pack_id, status, ml_last_updated, date_created, seller_id, "
            "currency_id) "
            "SELECT order_id, CASE WHEN g % 10 = 0 THEN 4000000000000000 + g END, "
            "CASE WHEN g % 40 = 0 THEN 'cancelled' ELSE 'paid' END, :now, :now, 999, 'ARS' "
            f"FROM {_MEMBERS}"
        ),
        p,
    )
    session.execute(
        text(
            "INSERT INTO ml_order_items_ops (order_id, item_id, quantity, unit_price) "
            f"SELECT order_id, {_MLA}, qty, price FROM {_ITEMS}"
        ),
        p,
    )
    session.execute(
        text(
            "INSERT INTO ml_order_item_costos (order_id, item_id, costo_origen, moneda, costo_unitario_ars, "
            "iva_pct, precio_unitario, fuente, producto_item_id) "
            f"SELECT order_id, {_MLA}, 600 + (k % 40) * 5, 'ARS', 600 + (k % 40) * 5, 21, price, 'vol', "
            f"800001 + (k % :p) FROM {_ITEMS}"
        ),
        p,
    )
    session.execute(
        text(
            "INSERT INTO ml_order_metrics (order_id, total_gauss, costo_mercaderia, gauss_status, "
            "formula_version, computed_at) "
            "SELECT order_id, CASE WHEN g % 50 = 0 THEN NULL ELSE 150 + g % 100 END, "
            "CASE WHEN g % 50 = 0 THEN NULL ELSE 800 END, "
            "CASE WHEN g % 50 = 0 THEN 'unresolved' ELSE 'ok' END, 2, :now "
            f"FROM {_MEMBERS}"
        ),
        p,
    )
    session.execute(
        text(
            "INSERT INTO ml_order_metrics_dirty (order_id, version, reason, attempts) "
            f"SELECT order_id, 1, 'vol', 0 FROM {_MEMBERS} WHERE g % 97 = 0"
        ),
        p,
    )
    for name in (
        "ml_group_metrics",
        "ml_orders_ops",
        "ml_order_items_ops",
        "ml_order_item_costos",
        "ml_order_metrics",
        "ml_order_metrics_dirty",
        "tb_mercadolibre_items_publicados",
        "productos_erp",
    ):
        session.execute(text(f"ANALYZE {name}"))


@pytest.fixture(scope="module")
def volume_session(board_pg_engine):
    connection = board_pg_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    started = time.perf_counter()
    _seed(session)
    print(f"\nvolume seeded in {(time.perf_counter() - started):.1f} s")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr(board, "now_utc", lambda: NOW)
    monkeypatch.setattr(settings, "ML_USER_ID", 999)


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


def _request(session, scope_pairs=None, **filters):
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
        response = build_board_response(
            session,
            f,
            limit=filters.get("limit", 50),
            offset=0,
            can_see_margin=True,
            scope_pairs=scope_pairs,
        )
    finally:
        event.remove(connection, "before_cursor_execute", recorder.before)
        event.remove(connection, "after_cursor_execute", recorder.after)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return response, recorder, elapsed_ms


def _print(label: str, recorder: _Recorder, elapsed_ms: float) -> None:
    print(f"{label}: {len(recorder.statements)} statements, {elapsed_ms:.0f} ms")
    for ms, head in recorder.timings:
        print(f"   {ms:7.1f} ms  {head}")


@pytest.mark.postgres
class TestBoardOnVolume:
    def test_fixed_statement_count_whatever_the_page_size(self, volume_session) -> None:
        counts = {}
        for limit in (10, 50, 200):
            response, recorder, elapsed_ms = _request(volume_session, limit=limit)
            assert len(response.rows) == limit
            assert response.total == PRODUCTS
            counts[limit] = len(recorder.statements)
            _print(f"\nboard product limit={limit}", recorder, elapsed_ms)
        _response, recorder, elapsed_ms = _request(volume_session, limit=50, group_by="publication")
        _print("board publication limit=50", recorder, elapsed_ms)
        response, filtered, elapsed_ms = _request(
            volume_session, limit=50, stores=("2645",), marcas=("Samsung",), pub_status=("active",), q="volumen"
        )
        _print("board filtered limit=50", filtered, elapsed_ms)
        excluded, hidden, elapsed_ms = _request(
            volume_session, limit=50, pub_status_exclude=("paused", "closed"), pub_type_exclude=("catalogo", "full")
        )
        print(f"board with exclusions limit=50: {len(hidden.statements)} statements, {elapsed_ms:.0f} ms")
        stocked, by_stock, elapsed_ms = _request(
            volume_session,
            limit=50,
            stock=("sin_stock",),
            stock_exclude=("sin_dato",),
            ageing=("up_to_30",),
            solo_con_ventas=True,
        )
        print(
            f"board by stock, ageing, solo con ventas limit=50: {len(by_stock.statements)} statements, {elapsed_ms:.0f} ms"
        )
        empty, emptied, elapsed_ms = _request(volume_session, limit=50, q="no-existe-nada")
        print(f"board empty page: {len(emptied.statements)} statements, {elapsed_ms:.0f} ms")

        assert counts[10] == counts[50] == counts[200] == len(recorder.statements)
        assert response.rows and len(filtered.statements) == counts[50]
        # Exclusion rides the same filter CTE: no extra statements.
        assert excluded.rows and len(hidden.statements) == counts[50]
        # The ROW filters (stock, ageing, "solo con ventas") ride the rows subquery
        # and the stock join is inside it: no extra statements either.
        assert stocked.rows and len(by_stock.statements) == counts[50]
        # An empty page skips the two per-page statements (details, series).
        assert not empty.rows and len(emptied.statements) == counts[50] - 2
        assert counts[50] <= 19

    def test_the_scope_filter_adds_no_statement(self, volume_session) -> None:
        """The PM scope rides the per-item base: a scoped (or empty-scoped) request
        costs exactly the statements of the unscoped one for the same page."""
        _plain, unscoped, _ms = _request(volume_session, limit=50)
        scoped_response, scoped, _ms = _request(volume_session, scope_pairs=[("EPSON", "CAT0")], limit=50)
        empty_response, emptied, _ms = _request(volume_session, scope_pairs=[], limit=50)

        assert scoped_response.rows and scoped_response.total < PRODUCTS
        assert len(scoped.statements) == len(unscoped.statements)
        # An empty page skips the two per-page statements (details, series).
        assert not empty_response.rows and empty_response.total == 0
        assert len(emptied.statements) == len(unscoped.statements) - 2

    def test_rows_fetched_follow_the_page_not_the_catalogue(self, volume_session) -> None:
        _response, recorder, _ms = _request(volume_session, limit=10)

        # 10 rows, their pairs (~30), 10 x 90 series points, 30 KPI series
        # points, a handful of chip buckets -- never the catalogue or the
        # orders: those stay inside the database.
        print(f"\nrows returned by the database for a page of 10: {recorder.rows_returned}")
        assert recorder.rows_returned < 1500

    def test_windows_are_nested_and_the_period_matches_the_orders(self, volume_session) -> None:
        f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY, group_by="publication")
        with board.Board(volume_session, f) as b:
            rows = b.page(None, with_series=False)

        for row in rows:
            w = row.windows
            assert row.units_24h <= w["3d"] <= w["7d"] <= w["15d"] <= w["30d"], row.key
        # Independent count: items of accredited groups in the period (Buenos
        # Aires days), minus cancellations ML did not cover.
        expected = volume_session.execute(
            text(
                "SELECT SUM(i.quantity) FROM ml_group_metrics g "
                "JOIN ml_orders_ops o ON (CASE WHEN o.pack_id IS NOT NULL THEN 'p:' || o.pack_id "
                "ELSE 'o:' || o.order_id END) = g.group_key "
                "JOIN ml_order_items_ops i ON i.order_id = o.order_id "
                "WHERE (g.group_date AT TIME ZONE 'America/Argentina/Buenos_Aires')::date "
                "BETWEEN :d_from AND :d_to AND o.status <> 'cancelled'"
            ),
            {"d_from": f.date_from, "d_to": f.date_to},
        ).scalar()
        assert sum(row.units for row in rows) == expected
        assert sum(row.windows["30d"] for row in rows) == expected
        assert any(row.units_24h for row in rows)

    def test_the_lines_are_reached_through_the_group_date_index(self, volume_session) -> None:
        f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY)
        b = board.Board(volume_session, f)
        source = b._lines_source()
        compiled = source.compile(
            dialect=volume_session.get_bind().dialect, compile_kwargs={"render_postcompile": True}
        )
        cursor = volume_session.connection().connection.cursor()
        cursor.execute("EXPLAIN " + str(compiled), compiled.params)
        plan = "\n".join(row[0] for row in cursor.fetchall())
        print("\n" + plan)

        assert "ix_ml_group_metrics_group_date" in plan, plan

    def test_a_products_publications_on_volume(self, volume_session) -> None:
        """The sub-rows endpoint's work: one product among 2.000, its
        publications only (ST2) -- printed for the ODD doc."""
        f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY, group_by="publication")
        with board.Board(volume_session, f, product_item_id=800001 + 7) as warm_up:
            # The first call of a statement shape pays SQLAlchemy's compile;
            # a running server has it cached.
            warm_up.page(limit=None, apply_alerts=False)
        recorder = _Recorder()
        connection = volume_session.connection()
        event.listen(connection, "before_cursor_execute", recorder.before)
        event.listen(connection, "after_cursor_execute", recorder.after)
        started = time.perf_counter()
        try:
            with board.Board(volume_session, f, product_item_id=800001 + 42) as b:
                rows = b.page(limit=None, apply_alerts=False)
        finally:
            event.remove(connection, "before_cursor_execute", recorder.before)
            event.remove(connection, "after_cursor_execute", recorder.after)
        _print("\nsub-rows of one product", recorder, (time.perf_counter() - started) * 1000)

        assert {row.key for row in rows} == {f"MLA77{i:06d}" for i in (42, 2042, 4042)}
        # SAVEPOINT, 2 x (CREATE + ANALYZE), page, details, series, ROLLBACK TO.
        assert len(recorder.statements) == 9

    def test_the_csv_exports_first_transaction_on_volume(self, volume_session) -> None:
        """The export's first short transaction: the ordered keys of every
        row and page 1 (500 rows, no series) -- printed for the ODD doc."""
        from app.routers.ml_metricas import EXPORT_MAX_ROWS, EXPORT_PAGE_SIZE

        f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY)
        recorder = _Recorder()
        connection = volume_session.connection()
        event.listen(connection, "before_cursor_execute", recorder.before)
        event.listen(connection, "after_cursor_execute", recorder.after)
        started = time.perf_counter()
        try:
            with board.Board(volume_session, f) as b:
                keys = b.ordered_keys(EXPORT_MAX_ROWS + 1)
                first = b.rows_for_keys(keys[:EXPORT_PAGE_SIZE])
        finally:
            event.remove(connection, "before_cursor_execute", recorder.before)
            event.remove(connection, "after_cursor_execute", recorder.after)
        _print("\nexport keys + first page", recorder, (time.perf_counter() - started) * 1000)

        assert len(keys) == PRODUCTS and len(first) == EXPORT_PAGE_SIZE
        # No sparkline series in the export. The marker is first proven to
        # match the series statement of a board page, so its absence here
        # cannot pass vacuously.
        series_marker = "GROUP BY fp.rk, board_lines.day"
        _response, page, _ms = _request(volume_session, limit=10)
        assert sum(series_marker in s for s, _p in page.statements) == 1
        assert not any(series_marker in s for s, _p in recorder.statements)

    def test_freshness_reads_the_sync_cursors(self, volume_session) -> None:
        _response, recorder, _ms = _request(volume_session, limit=10)

        assert any("ml_ops_sync_cursor" in s for s, _p in recorder.statements)


# ── Lifecycle of the request's temporary table (PgBouncer transaction mode) ──
#
# Production talks to Postgres through PgBouncer in TRANSACTION pooling: a
# server connection belongs to a client only for one transaction. The pair
# table must therefore live and die INSIDE one transaction: never survive it
# (the next client on that server connection would inherit it) and never be
# needed after a commit (later statements may land on another server
# connection, where it does not exist).


@pytest.fixture()
def plain_session(volume_session):
    """A fresh connection with NO outer test transaction, so commits and
    rollbacks are the real ones. The module's tables exist (committed DDL);
    its seed rows are invisible here (uncommitted elsewhere): an empty board
    is enough to exercise the lifecycle."""
    engine = volume_session.get_bind().engine
    session = sessionmaker(bind=engine)()
    yield session
    session.rollback()
    session.close()


def _pairs_table_exists(session) -> bool:
    return session.execute(text(f"SELECT to_regclass('pg_temp.{board.PAIRS_TABLE}') IS NOT NULL")).scalar()


def _filter():
    return board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY)


@pytest.mark.postgres
class TestPairsTableLifecycle:
    def test_gone_after_a_request(self, plain_session) -> None:
        build_board_response(plain_session, _filter(), limit=10, offset=0, can_see_margin=True)

        assert not _pairs_table_exists(plain_session)

    def test_gone_after_a_request_that_fails_midway_and_the_real_error_surfaces(
        self, plain_session, monkeypatch
    ) -> None:
        """A database error after the table exists aborts the transaction.
        The caller must see THAT error (not a secondary 'transaction is
        aborted' from cleanup), and the session must be usable again with no
        table left behind."""

        def boom(self):
            self.db.execute(text("SELECT 1 / 0"))

        monkeypatch.setattr(board.Board, "kpis", boom)
        from sqlalchemy.exc import DataError

        with pytest.raises(DataError, match="division by zero"):
            build_board_response(plain_session, _filter(), limit=10, offset=0, can_see_margin=True)

        assert not _pairs_table_exists(plain_session)

    def test_a_commit_midway_never_leaves_the_table_behind(self, plain_session) -> None:
        """Something committing inside the computation is a bug the board
        refuses loudly -- and even then the table must not outlive the commit
        (ON COMMIT DROP), or PgBouncer would hand it to another client."""
        with pytest.raises(RuntimeError, match="transaction"):
            with board.Board(plain_session, _filter()):
                plain_session.commit()
                assert not _pairs_table_exists(plain_session)

    def test_two_computations_back_to_back_on_one_connection(self, plain_session) -> None:
        first = build_board_response(plain_session, _filter(), limit=10, offset=0, can_see_margin=True)
        second = build_board_response(plain_session, _filter(), limit=10, offset=0, can_see_margin=True)

        assert first.total == second.total
        assert not _pairs_table_exists(plain_session)


@pytest.mark.postgres
class TestPagingIsStableUnderTies:
    """Most rows of the volume tie on `units_24h` (few sales in the last
    24h, many rows with 0 or 1-3 units). Paging must still hand out each row exactly once: the ORDER BY ends
    with the unique row key, or Postgres may reorder the ties between two
    LIMIT/OFFSET statements and pages repeat or skip rows."""

    @pytest.mark.parametrize("group_by, total", [("product", PRODUCTS), ("publication", PUBLICATIONS)])
    def test_pages_cover_every_row_exactly_once(self, volume_session, group_by, total) -> None:
        f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY, group_by=group_by, sort="units_24h")
        keys: list[str] = []
        with board.Board(volume_session, f) as b:
            for offset in range(0, total, 500):
                keys += [row.key for row in b.page(500, offset, with_series=False)]

        assert len(keys) == total
        assert len(set(keys)) == total

    def test_the_csv_export_holds_every_row_exactly_once(self, volume_session, monkeypatch) -> None:
        from app.routers import ml_metricas

        monkeypatch.setattr(ml_metricas, "EXPORT_PAGE_SIZE", 300)
        f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY, sort="units_24h")
        monkeypatch.setattr(ml_metricas, "_can_see_margin", lambda db, user: True)
        # A full-view caller: this test is about paging, not the PM scope.
        monkeypatch.setattr(ml_metricas, "_scope_pairs", lambda db, user: None)

        @contextmanager
        def page_session():
            # Each page's short session, on the module's seeded connection
            # (a real `SessionLocal` would point at the app's database).
            session = Session(bind=volume_session.connection())
            try:
                yield session
            finally:
                session.close()

        monkeypatch.setattr(ml_metricas, "get_background_db", page_session)
        request_session = SimpleNamespace(close=lambda: None)
        response = ml_metricas.export_board(f=f, current_user=None, db=request_session)

        async def collect(iterator) -> bytes:
            return b"".join([c if isinstance(c, bytes) else c.encode() async for c in iterator])

        body = asyncio.run(collect(response.body_iterator))
        lines = body.decode("utf-8-sig").strip().splitlines()[1:]

        assert len(lines) == PRODUCTS
        assert len(set(lines)) == PRODUCTS


def test_product_option_lists_cost_on_volume(volume_session) -> None:
    """ODD `metricas-ml-filtros-dinamicos`: the marca / categoría / subcategoría /
    PM option lists are ONE statement over the materialized pair table (distinct
    combinations + the lookups joined in). Measured here on the seeded volume
    (timings printed, never asserted): the statement alone and inside a whole
    board request, with the PM pair / subcategory lookups at production size."""
    from sqlalchemy import select

    from app.services.product_facets import product_combo_statement

    session = volume_session
    session.execute(
        text(
            "INSERT INTO usuarios (id, nombre) SELECT 8000 + i, 'PM ' || i FROM generate_series(1, 12) AS i;"
            "INSERT INTO marcas_pm (marca, categoria, usuario_id) "
            "SELECT 'Marca ' || i, 'Cat ' || (i % 30), 8000 + 1 + i % 12 FROM generate_series(1, 355) AS i;"
            "INSERT INTO subcategorias_grupos (subcat_id, grupo_id, nombre_subcategoria, nombre_categoria) "
            "SELECT i, 1, 'Sub ' || i, 'Cat ' || (i % 30) FROM generate_series(1, 400) AS i"
        )
    )
    for table in ("marcas_pm", "subcategorias_grupos", "usuarios"):
        session.execute(text(f"ANALYZE {table}"))
    f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY, marcas=("Epson",))
    with board.Board(session, f) as b:
        joined, fp = b._members(board.PRODUCT_AXIS)
        statement = product_combo_statement(
            select(fp.c.marca, fp.c.categoria, fp.c.subcategoria_id).select_from(joined)
        )
        compiled = str(statement.compile(session.get_bind(), compile_kwargs={"literal_binds": True}))
        plan = session.execute(text("EXPLAIN (ANALYZE, BUFFERS) " + compiled)).scalars().all()
        print("\n".join(plan))
        started = time.perf_counter()
        rows = session.execute(statement).all()
        print(f"product options statement: {len(rows)} rows, {(time.perf_counter() - started) * 1000:.0f} ms")
    response, recorder, elapsed_ms = _request(session, limit=50, marcas=("Epson",))
    print(f"whole board request (with options): {len(recorder.statements)} statements, {elapsed_ms:.0f} ms")
    assert response.facets.product.marcas


def test_ventas_product_option_lists_cost_on_volume(volume_session) -> None:
    """Same measurement for Ventas ML: the options read the items of the groups the
    listing shows (30 days, product facet cleared) -- one statement, plus the
    whole `build_scope` it hangs from (timings printed, never asserted)."""
    from dataclasses import replace

    from app.services.ml_sales_query.filters import (
        SalesFilter,
        build_scope,
        product_facet_source,
        sales_product_options,
        store_facet_counts,
    )
    from app.services.product_facets import product_combo_statement, product_combo_rows

    session = volume_session
    # Ventas ML days are the ACCREDITATION day: one approved payment per order, on its group's date.
    session.execute(
        text(
            "INSERT INTO ml_payments_ops (payment_id, order_id, status, date_approved) "
            "SELECT order_id * 10 + 1, order_id, 'approved', "
            ":now - make_interval(days => CAST(CASE WHEN g <= :dense THEN g % 90 ELSE 90 + (g - :dense) % 450 END AS INTEGER), "
            "secs => CAST((g * 37) % 86400 AS DOUBLE PRECISION)) "
            f"FROM {_MEMBERS}"
        ),
        {"groups": GROUPS, "dense": DENSE_GROUPS, "now": NOW},
    )
    session.execute(text("ANALYZE ml_payments_ops"))
    f = SalesFilter(
        date_range=(
            datetime.combine(TODAY - timedelta(days=29), datetime.min.time(), tzinfo=timezone.utc),
            datetime.combine(TODAY + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc),
        ),
        include_unknown=True,
        include_in_dispute=True,
        include_mixed=True,
        include_provisional=True,
    )

    def timed(label, fn, repeats=2):
        """Runs `fn` `repeats` times (the first warms the cache) and prints the last run."""
        result = None
        for _ in range(repeats):
            started = time.perf_counter()
            result = fn()
        print(f"{label}: {(time.perf_counter() - started) * 1000:.0f} ms")
        return result

    scope = build_scope(session, f)
    source = product_facet_source(scope)
    statement = product_combo_statement(source)
    compiled = str(statement.compile(session.get_bind(), compile_kwargs={"literal_binds": True}))
    plan = session.execute(text("EXPLAIN (ANALYZE, BUFFERS) " + compiled)).scalars().all()
    print("\n".join(plan[-4:]))

    # No product facet active: the scope IS the universe -- the options are this one statement.
    rows = timed(
        "ventas options, no facet active: the combos statement alone", lambda: product_combo_rows(session, source)
    )
    print(f"  -> {len(rows)} combinations")
    # Each piece on its own, for scale.
    timed("  build_scope alone", lambda: build_scope(session, f))
    timed("  existing store chip counts on the same scope", lambda: store_facet_counts(scope))

    # A product facet active: `sales_product_options` builds a SECOND scope (facets cleared), then runs the statement.
    active = replace(f, marcas=("Epson",))
    active_scope = build_scope(session, active)
    options = timed(
        "ventas options, facet active (marcas=Epson): second build_scope + the statement",
        lambda: sales_product_options(session, active, active_scope),
    )
    assert rows and options.marcas


# ── The "Agrupado" view (ODD `metricas-ml-vista-agrupada`) ─────────────────


@pytest.fixture()
def group_lookups(volume_session):
    """What the group names read, on the volume data: PMs for the 5 brands,
    the 7 subcategories, the official stores (two sharing a clave). Removed
    again: the module's other tests count rows of these tables."""
    session = volume_session
    session.execute(
        text(
            "INSERT INTO usuarios (id, nombre) VALUES (990001, 'PM Uno'), (990002, 'PM Dos');"
            "INSERT INTO marcas_pm (marca, categoria, usuario_id) "
            "SELECT m.marca, 'Cat' || c, m.pm FROM (VALUES ('Epson', 990001), ('Lenovo', 990001), "
            "('Samsung', 990002), ('Sony', 990002)) AS m(marca, pm) CROSS JOIN generate_series(0, 2) AS c;"
            "INSERT INTO subcategorias_grupos (subcat_id, grupo_id, nombre_subcategoria, nombre_categoria) "
            "SELECT s, 1, 'Subcategoría ' || s, 'Cat' || ((s - 1) % 3) FROM generate_series(1, 7) AS s;"
            "INSERT INTO ml_tiendas_oficiales (store_id, nombre, clave, orden, activa) VALUES "
            "(57997, 'Gauss', NULL, 1, true), (2645, 'TP-Link vieja', 'tplink', 2, false), "
            "(144, 'TP-Link', 'tplink', 3, true), (191942, 'Multimarca', NULL, 4, true)"
        )
    )
    yield
    session.execute(
        text(
            "DELETE FROM ml_tiendas_oficiales; DELETE FROM subcategorias_grupos; "
            "DELETE FROM marcas_pm WHERE usuario_id IN (990001, 990002); DELETE FROM usuarios WHERE id IN (990001, 990002)"
        )
    )


GROUP_DIMENSIONS = ("marca", "categoria", "subcategoria", "tienda", "pm")


@pytest.mark.postgres
class TestGroupedBoardOnVolume:
    def test_fixed_statement_count_for_every_dimension_and_page_size(self, volume_session, group_lookups) -> None:
        _response, product_recorder, _ms = _request(volume_session, limit=50)
        counts = {}
        for dimension in GROUP_DIMENSIONS:
            for limit in (10, 200):
                response, recorder, elapsed_ms = _request(
                    volume_session, limit=limit, group_by="group", dimension=dimension
                )
                counts[(dimension, limit)] = len(recorder.statements)
                if limit == 10:
                    _print(f"\ngrouped by {dimension}, limit=10 ({response.total} groups)", recorder, elapsed_ms)
                assert response.rows and len(response.rows) <= limit

        assert len(set(counts.values())) == 1, counts
        # Its own page, series and count -- never per group, never per product.
        assert counts[("marca", 10)] <= len(product_recorder.statements) + 3

    def test_an_empty_page_skips_the_series(self, volume_session, group_lookups) -> None:
        _full, full, _ = _request(volume_session, group_by="group", dimension="marca")
        empty_response, empty, _ = _request(volume_session, group_by="group", dimension="marca", q="no-existe-nada")

        assert not empty_response.rows and len(empty.statements) == len(full.statements) - 1

    @pytest.mark.parametrize("dimension", GROUP_DIMENSIONS)
    def test_the_groups_add_up_to_the_ungrouped_totals_on_volume(
        self, volume_session, group_lookups, dimension
    ) -> None:
        response, _recorder, _ms = _request(volume_session, limit=200, group_by="group", dimension=dimension)
        assert response.total <= 200  # one page holds every group of every dimension here

        kpis = response.kpis
        assert sum(r.units for r in response.rows) == kpis.units.value
        assert round(sum(r.gross for r in response.rows), 2) == kpis.gross.value
        # Total Gauss of a multi-item order is split in fractions of a cent
        # and each group rounds ITS sum once: within a cent per group.
        assert abs(sum(r.total_gauss for r in response.rows) - kpis.total_gauss.value) <= 0.01 * len(response.rows)

    def test_the_filters_narrow_the_groups_on_volume(self, volume_session, group_lookups) -> None:
        response, recorder, elapsed_ms = _request(
            volume_session,
            limit=50,
            group_by="group",
            dimension="tienda",
            marcas=("Samsung",),
            pub_status=("active",),
            solo_con_ventas=True,
        )
        _print("\ngrouped by tienda with filters", recorder, elapsed_ms)

        assert response.rows and response.total == len(response.rows)

    @pytest.mark.parametrize(
        "extra",
        [{}, {"stock": ("con_stock",), "ageing": ("up_to_30",), "solo_con_ventas": True}],
        ids=["plain", "row-filters"],
    )
    @pytest.mark.parametrize(
        "dimension, scope",
        [
            ("tienda", ()),
            ("tienda", ("c:tplink",)),
            ("tienda", ("c:tplink", "SAMSUNG")),
            ("tienda", ("c:tplink", "SAMSUNG", "CAT0")),
            ("tienda", ("c:tplink", "SAMSUNG", "CAT0", "1")),
            ("categoria", ("CAT0", "1")),
            ("subcategoria", ("1|CAT0",)),
            ("pm", ("990002", "SAMSUNG", "CAT0", "1")),
        ],
        ids=lambda v: "/".join(v) if isinstance(v, tuple) else None,
    )
    def test_opening_a_node_at_any_depth_on_volume(
        self, volume_session, group_lookups, dimension, scope, extra
    ) -> None:
        """One level page = ONE request's worth of SQL, whatever the depth: the
        same pair table, the node's keys as plain equality filters."""
        levels = groups.levels_of(dimension)
        leaf = len(scope) == len(levels) - 1
        f = board.BoardFilter(
            date_from=TODAY - timedelta(days=29),
            date_to=TODAY,
            group_by="product" if leaf else "group",
            dimension=dimension,
            **extra,
        )
        recorder = _Recorder()
        connection = volume_session.connection()
        event.listen(connection, "before_cursor_execute", recorder.before)
        event.listen(connection, "after_cursor_execute", recorder.after)
        started = time.perf_counter()
        try:
            with board.Board(volume_session, f, scope=scope) as b:
                if leaf:
                    total = b.product_count()
                    rows = b.page(100, 0)
                else:
                    total = b.group_counts()[0]
                    rows = b.group_page(100, 0)
        finally:
            event.remove(connection, "before_cursor_execute", recorder.before)
            event.remove(connection, "after_cursor_execute", recorder.after)
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(
            f"\nTREE {dimension} {'/'.join(scope) or '(top)'} {extra and 'row-filters' or 'plain'}: "
            f"{len(rows)} of {total} {levels[len(scope)]}, {len(recorder.statements)} statements, {elapsed_ms:.0f} ms"
        )
        for ms, head in sorted(recorder.timings, reverse=True)[:2]:
            print(f"      slowest: {ms:7.1f} ms  {head}")

        assert rows and len(rows) == min(100, total)  # a page, never the whole level
        # savepoint + 2 CREATE + 2 ANALYZE + count + page + (details +) series + rollback.
        assert len(recorder.statements) <= 12, len(recorder.statements)

    @pytest.mark.parametrize("dimension", ("marca", "tienda", "pm"))
    def test_every_level_adds_up_to_its_parent_on_volume(self, volume_session, group_lookups, dimension) -> None:
        """Walks ONE branch from the top to the products: at each step the
        children (every page) add up to the node they were opened from."""
        levels = groups.levels_of(dimension)
        scope: tuple = ()
        with board.Board(
            volume_session,
            board.BoardFilter(
                date_from=TODAY - timedelta(days=29), date_to=TODAY, group_by="group", dimension=dimension
            ),
        ) as b:
            node = max(b.group_page(None), key=lambda r: r.units)
        while True:
            scope = (*scope, node.key)
            leaf = len(scope) == len(levels) - 1
            f = board.BoardFilter(
                date_from=TODAY - timedelta(days=29),
                date_to=TODAY,
                group_by="product" if leaf else "group",
                dimension=dimension,
            )
            with board.Board(volume_session, f, scope=scope) as b:
                children = b.page(None, with_series=False) if leaf else b.group_page(None, with_series=False)
            assert sum(c.units for c in children) == node.units, scope
            assert sum(c.gross for c in children) == node.gross, scope
            # Gauss and cost of a multi-item order are split in fractions of a cent and each
            # node rounds ITS sum once: within a cent per child (units and billing are exact).
            assert abs(sum(c.costo for c in children) - node.costo) <= 0.01 * len(children), scope
            assert abs(sum(c.tg for c in children) - node.tg) <= 0.01 * len(children), scope
            if leaf:
                assert len(children) == node.products_count, scope
                break
            node = max(children, key=lambda r: r.units)
