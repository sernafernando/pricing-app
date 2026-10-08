"""P5.T7 + P6.T6: the list (and its markup) on a realistic volume, on real Postgres (25k publications, 18k links,
6k products).

Seeded with `generate_series` (seconds, not minutes) and the REAL index migration applied. Pins what regresses
loudly: a FIXED number of statements whatever the page size, and a default page that walks
`ix_ml_items_last_trigger` instead of sorting the table. Timings and EXPLAIN plans are printed (`-s`) and
recorded in the PR, never asserted: a wall-clock bound would be flaky on a shared CI box. The budget (list page
p95 < 500 ms) is measured on production data with `scripts/measure_pubml_p5.py`; the markup sort/filter (the
decision of P6b, p95 > 1 s) with `scripts/measure_pubml_p6.py`. Markup timings here use a hand-built pricing context
and no real shipping batch (its cost is the cross-database lookup, only measurable on production).
"""

from __future__ import annotations

import importlib.util
import statistics
import time
from pathlib import Path
from typing import Callable

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, text
from sqlalchemy.orm import Session, sessionmaker

from app.services.ml_publications.view import listing, markup_inputs, markup_service
from app.services.ml_publications.view.filters import MarkupFilter, build_base_select, parse_filter
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed as view_seed
from tests.services.ml_publications.view.test_listing_postgres import STORES_DDL
from tests.services.ml_publications.view.test_unit_markup import BASE_BY_GRUPO, make_ctx

pytestmark = pytest.mark.postgres

ITEMS = 25_000
LINKED = 18_000
PRODUCTS = 6_000
RUNS = 12
MIGRATION = Path(__file__).resolve().parents[4] / "alembic" / "versions" / "20261011_ml_items_last_trigger_index.py"


def _seed(conn) -> None:
    p = {"items": ITEMS, "linked": LINKED, "products": PRODUCTS}
    conn.execute(
        text(
            "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id) "
            "SELECT 800000 + i, '77900' || lpad(i::text, 8, '0'), 'Producto de volumen ' || i || "
            "CASE WHEN i % 40 = 0 THEN ' camara domo' ELSE '' END, "
            "(ARRAY['TP-Link','Hikvision','Tenda','Epson','Sony'])[1 + i % 5], 'Cat' || (i % 7 % 3), 1 + i % 7 "
            "FROM generate_series(1, :products) AS i"
        ),
        p,
    )
    # The markup inputs: a cost per product, the Productos list prices and the installments campaign of each item.
    conn.execute(
        text("UPDATE productos_erp SET costo = 400 + (item_id % 50) * 20, moneda_costo = 'ARS', iva = 21, envio = 0")
    )
    conn.execute(
        text(
            "INSERT INTO productos_pricing (item_id, precio_lista_ml, precio_3_cuotas, precio_6_cuotas, "
            "precio_9_cuotas, precio_12_cuotas) SELECT item_id, 1500, 1550, 1600, 1650, 1700 FROM productos_erp"
        )
    )
    conn.execute(
        text(
            "INSERT INTO ml_items (item_id, title, status, official_store_id, listing_type_id, catalog_listing, "
            "logistic_type, seller_sku, user_product_id, price, available_quantity, last_trigger_received_at, "
            "ml_last_updated, gone_at, family_id, last_checked_at, thumbnail, permalink, tags) "
            "SELECT 'MLA' || (1000000 + i), "
            "'Publicacion ' || i || ' ' || (ARRAY['router','switch','camara','cable','antena','fuente'])[1 + i % 6] "
            "|| ' modelo ' || (i * 7919 % 9973), "
            "(ARRAY['active','active','active','paused','closed','under_review'])[1 + i % 6], "
            "(ARRAY[57997, 2645, 144, 191942, NULL])[1 + i % 5], "
            "(ARRAY['gold_special','gold_pro','gold_pro'])[1 + i % 3], i % 9 = 0, "
            "CASE WHEN i % 4 = 0 THEN 'fulfillment' ELSE 'cross_docking' END, "
            "'SKU-' || (i % 9000), CASE WHEN i % 5 < 3 THEN 'MLAU' || i END, "
            "1000 + (i % 500) * 10, i % 7, "
            "CASE WHEN i % 20 = 0 THEN NULL ELSE now() - (i || ' seconds')::interval END, "
            "now() - (i * 3 || ' seconds')::interval, "
            "CASE WHEN i % 50 = 0 THEN now() END, i % 3000, now(), 'http://t/' || i, 'http://p/' || i, "
            "CASE WHEN i % 4 = 0 THEN ARRAY['3x_campaign'] WHEN i % 4 = 1 THEN ARRAY['9x_campaign'] "
            "ELSE ARRAY['good_quality_picture'] END "
            "FROM generate_series(1, :items) AS i"
        ),
        p,
    )
    conn.execute(
        text(
            "INSERT INTO ml_item_product_links (item_id, variation_id, source, match_status, producto_item_id, "
            "linked_at) SELECT 'MLA' || (1000000 + i), 0, "
            "(ARRAY['sku_auto','sku_auto','manual'])[1 + i % 3], 'linked', 800001 + (i % :products), now() "
            "FROM generate_series(1, :linked) AS i"
        ),
        p,
    )
    conn.execute(
        text(
            "INSERT INTO ml_item_sale_prices (item_id, amount, regular_amount, http_status) "
            "SELECT 'MLA' || (1000000 + i), 900 + (i % 400) * 10, 1000 + (i % 400) * 10, 200 "
            "FROM generate_series(1, :items) AS i WHERE i % 5 < 2"
        ),
        p,
    )
    conn.execute(
        text(
            "INSERT INTO ml_user_product_stock (user_product_id, full_quantity, own_quantity, total_quantity, "
            "ml_last_updated) SELECT 'MLAU' || i, i % 11, i % 4, i % 11 + i % 4, now() "
            "FROM generate_series(1, :items) AS i WHERE i % 5 < 3"
        ),
        p,
    )
    conn.execute(
        text(
            "INSERT INTO ml_item_variations (item_id, variation_id, seller_sku, raw, raw_hash, fetched_at) "
            "SELECT 'MLA' || (1000000 + i), v, 'VAR-' || i || '-' || v, '{}'::jsonb, '\\x00', now() "
            "FROM generate_series(1, 3000) AS i, generate_series(1, 2) AS v"
        )
    )
    conn.execute(
        text(
            "INSERT INTO ml_change_log (id, resource_type, entity_id, item_id, observed_at, changed_paths, changes) "
            "SELECT i, 'item', 'MLA' || (1000000 + i), 'MLA' || (1000000 + i), now() - (i || ' minutes')::interval, "
            "'{}', '[]'::jsonb FROM generate_series(1, 30000) AS i"
        )
    )
    conn.execute(
        text(
            "INSERT INTO ml_item_events (event_type, item_id, observed_at, change_log_id, dedupe_key) "
            "SELECT (ARRAY['price_changed','status_paused','stock_depleted'])[1 + i % 3], "
            "'MLA' || (1000000 + i), now() - (i || ' minutes')::interval, i, ('k' || i)::bytea "
            "FROM generate_series(1, 30000) AS i"
        )
    )
    conn.execute(text("INSERT INTO ml_tiendas_oficiales (store_id, nombre) VALUES (57997, 'A'), (2645, 'TP-Link')"))
    for table in (
        "productos_erp",
        "productos_pricing",
        "ml_items",
        "ml_item_product_links",
        "ml_item_sale_prices",
        "ml_user_product_stock",
        "ml_item_variations",
        "ml_item_events",
    ):
        conn.execute(text(f"ANALYZE {table}"))


@pytest.fixture()
def session(env):  # noqa: F811
    spec = importlib.util.spec_from_file_location("ml_items_last_trigger_index_volume", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    started = time.perf_counter()
    with env.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(STORES_DDL))
        conn.execute(text(view_seed.PRICING_DDL))
        _seed(conn)
    with env.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx), ctx.begin_transaction():
            migration.upgrade()
    with env.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("ANALYZE ml_items"))
    print(f"\nvolume seeded in {time.perf_counter() - started:.1f} s ({ITEMS} items, {LINKED} links)")
    session = sessionmaker(bind=env, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def timed(label: str, call: Callable[[], object], runs: int = RUNS) -> None:
    call()  # warm
    samples = []
    for _ in range(runs):
        started = time.perf_counter()
        call()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    p95 = samples[min(len(samples) - 1, int(len(samples) * 0.95))]
    print(f"{label:<44} p50 {statistics.median(samples):7.1f} ms  p95 {p95:7.1f} ms  max {samples[-1]:7.1f} ms")


def page(session: Session, limit: int = 50, offset: int = 0, **params):
    f = parse_filter(**{k: v for k, v in params.items() if k not in ("orden", "dir")})
    sort = listing.parse_sort(params.get("orden"), params.get("dir"))
    return listing.list_items(session, f, sort, limit, offset, events=True)


def explain(session: Session, statement, analyze: bool = True) -> str:
    """The plan of `statement` as the database runs it: bound parameters, through the DBAPI cursor."""
    compiled = statement.compile(dialect=session.get_bind().dialect)
    verb = "EXPLAIN (ANALYZE, BUFFERS)" if analyze else "EXPLAIN"
    cursor = session.connection().connection.cursor()
    try:
        cursor.execute(f"{verb} {compiled}", compiled.params)
        return "\n".join(row[0] for row in cursor.fetchall())
    finally:
        cursor.close()


def page_statement(f, limit: int = 50, **sort):
    """The page SELECT of `list_items` for `f` (all row columns, default ordering)."""
    return (
        build_base_select(f, *listing._row_columns())
        .order_by(*listing._order_by(listing.parse_sort(sort.get("orden"), sort.get("dir"))))
        .limit(limit)
    )


class TestVolume:
    def test_the_seed_is_what_it_says(self, session) -> None:
        counts = {
            "ml_items": ITEMS,
            "ml_item_product_links": LINKED,
            "productos_erp": PRODUCTS,
        }
        for table, expected in counts.items():
            assert session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == expected

    def test_the_statement_count_does_not_depend_on_the_page_size(self, session) -> None:
        recorded: list[str] = []

        def record(conn, cursor, statement, *rest) -> None:
            recorded.append(statement)

        engine = session.get_bind()
        counts = {}
        event.listen(engine, "before_cursor_execute", record)
        try:
            for limit in (10, 50, 100):
                recorded.clear()
                result = page(session, limit=limit)
                assert len(result.items) == limit
                counts[limit] = len(recorded)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        print(f"\nstatements per page: {counts}")
        assert len(set(counts.values())) == 1

    def test_the_default_page_walks_the_activity_index_instead_of_sorting(self, session) -> None:
        plan = explain(session, page_statement(parse_filter()))
        print("\n--- default page: EXPLAIN (ANALYZE, BUFFERS)\n" + plan)
        assert "ix_ml_items_last_trigger" in plan
        assert "Sort Method" not in plan  # the order comes from the index, nothing is sorted

    def test_what_the_index_buys_the_default_page(self, session) -> None:
        timed("default page WITH the index", lambda: page(session))
        session.rollback()
        with session.get_bind().connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("DROP INDEX ix_ml_items_last_trigger"))
        timed("default page WITHOUT the index", lambda: page(session))
        plan = explain(session, page_statement(parse_filter()))
        print("--- default page without the index\n" + "\n".join(plan.splitlines()[:4] + plan.splitlines()[-2:]))
        assert "ix_ml_items_last_trigger" not in plan and "Sort Method" in plan  # the control: it sorts the table

    def test_timings(self, session) -> None:
        print("\n--- list service timings (service only, no HTTP), 25k publications")
        timed("default page (limit 50)", lambda: page(session))
        timed("default page, page 200 (offset 10k)", lambda: page(session, offset=10_000))
        timed("default page + 6 facets", lambda: (page(session), listing.facets(session, parse_filter())))
        timed("search: title substring, common word", lambda: page(session, q="router"))
        timed("search: title substring, rare token", lambda: page(session, q="modelo 9972"))
        timed("search: linked product name", lambda: page(session, q="camara domo"))
        timed("search: MLA id (exact)", lambda: page(session, q="MLA1012345"))
        timed("search: EAN (digits, exact on codigo)", lambda: page(session, q="7790000000123"))
        timed("search: seller SKU", lambda: page(session, q="SKU-1234"))
        timed(
            "filter: estado+tienda, sort precio", lambda: page(session, estado="active", tiendas="2645", orden="precio")
        )
        timed("filter: vinculo=auto, sort titulo", lambda: page(session, vinculo="auto", orden="titulo"))
        timed("sort: stock_full", lambda: page(session, orden="stock_full"))
        timed("filter: evento=price_changed 7d", lambda: page(session, evento="price_changed", evento_desde="7d"))
        timed(
            "count only (no filter)", lambda: session.execute(build_base_select(parse_filter(), listing.func.count()))
        )

    def test_plans_of_the_search_and_the_count(self, session) -> None:
        rare = parse_filter(q="modelo 9972")
        print("\n--- search 'modelo 9972' (ILIKE on title/sku/product/variation sku): page")
        print(explain(session, page_statement(rare)))
        print("\n--- search 'modelo 9972': count")
        print(explain(session, build_base_select(rare, listing.func.count())))
        print("\n--- count of the unfiltered list")
        print(explain(session, build_base_select(parse_filter(), listing.func.count())))
        print("\n--- sort by stock_full")
        print(explain(session, page_statement(parse_filter(), orden="stock_full")))


PRICING_CTX = make_ctx(subcat_to_grupo={n: (1, 4, 6, 10)[n % 4] for n in range(1, 8)}, comision_base=BASE_BY_GRUPO)


@pytest.fixture()
def priced(monkeypatch):
    """The pricing context is hand-built and the shipping batch is stubbed: the database cost of the markup is
    what is measured here (the cross-database shipping lookup can only be measured on production)."""
    monkeypatch.setattr(markup_service, "build_pricing_context", lambda db: PRICING_CTX)
    monkeypatch.setattr(markup_service, "resolver_costos_envio_batch", lambda db, ids, **k: {})


def markup_page(session: Session, limit: int = 50, offset: int = 0, **params):
    f = parse_filter(**{k: v for k, v in params.items() if k not in ("orden", "dir", "negative")})
    sort = listing.parse_sort(params.get("orden"), params.get("dir"))
    query = markup_service.MarkupQuery(session, MarkupFilter(negative=params.get("negative", False)))
    return listing.list_items(session, f, sort, limit, offset, events=True, markup=query)


class TestMarkupVolume:
    def test_the_set_wide_markup_sort_prices_every_linked_publication(self, session, priced) -> None:
        result = markup_page(session, orden="markup")
        assert result.total == ITEMS - ITEMS // 50  # gone items are hidden
        stats = result.markup_stats
        unpriced = dict(stats.null_by_reason)
        print(f"\nmarkup stats at 25k: computed={stats.computed} ms={stats.ms} null_by_reason={unpriced}")
        assert stats.computed > 10_000  # the linked, priceable ones
        assert {"sin_vinculo"} <= set(stats.null_by_reason)
        worst = [row["markup"]["worst"] for row in result.items]
        assert worst == sorted(worst)  # the page is the lowest markups, ascending

    def test_the_statement_count_does_not_depend_on_the_page_size_with_markup(self, session, priced) -> None:
        recorded: list[str] = []

        def record(conn, cursor, statement, *rest) -> None:
            recorded.append(statement)

        engine = session.get_bind()
        counts: dict[tuple, int] = {}
        event.listen(engine, "before_cursor_execute", record)
        try:
            for label, params in (("page", {}), ("sort", {"orden": "markup"}), ("neg", {"negative": True})):
                for limit in (10, 100):
                    recorded.clear()
                    assert len(markup_page(session, limit=limit, **params).items) == limit
                    counts[(label, limit)] = len(recorded)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        print(f"\nstatements with markup: {counts}")
        for label in ("page", "sort", "neg"):
            assert counts[(label, 10)] == counts[(label, 100)]

    def test_markup_timings(self, session, priced) -> None:
        print("\n--- markup timings (service only, no HTTP, no shipping batch), 25k publications")
        timed("page of 50 + markup (default sort)", lambda: markup_page(session))
        timed("orden=markup, page 1 (set-wide)", lambda: markup_page(session, orden="markup"))
        timed("orden=markup, page 200 (offset 10k)", lambda: markup_page(session, orden="markup", offset=10_000))
        timed("markup_neg=true, sort titulo (set-wide)", lambda: markup_page(session, negative=True, orden="titulo"))
        timed(
            "orden=markup + estado=active + tienda 2645",
            lambda: markup_page(session, orden="markup", estado="active", tiendas="2645"),
        )
        f = parse_filter()
        timed("  stage: inputs of the whole set (3 statements)", lambda: markup_inputs.fetch_inputs(session, f=f))
        inputs = markup_inputs.fetch_inputs(session, f=f)
        timed(
            "  stage: pricing loop over the whole set",
            lambda: [markup_service.price_publication(PRICING_CTX, pub, {}) for pub in inputs.values()],
        )
