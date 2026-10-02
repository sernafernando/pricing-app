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
from app.services.ml_daily_metrics import board

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
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id) "
            "SELECT 800000 + i, 'SKU-' || i, 'Producto de volumen ' || i, "
            "(ARRAY['Epson','Lenovo','Samsung','Sony','BGH'])[1 + i % 5], 'Cat', 1 + i % 7 "
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
        empty, emptied, elapsed_ms = _request(volume_session, limit=50, q="no-existe-nada")
        print(f"board empty page: {len(emptied.statements)} statements, {elapsed_ms:.0f} ms")

        assert counts[10] == counts[50] == counts[200] == len(recorder.statements)
        assert response.rows and len(filtered.statements) == counts[50]
        # Exclusion rides the same filter CTE: no extra statements.
        assert excluded.rows and len(hidden.statements) == counts[50]
        # An empty page skips the two per-page statements (details, series).
        assert not empty.rows and len(emptied.statements) == counts[50] - 2
        assert counts[50] <= 19

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
