"""The Producto view on the board's volume seed (`test_metrics_sort_volume_postgres.world`: 2.000 products, 6.000 sold
publications, 81.000 order groups, a store of 25.000 publications), 90 % of the publications linked to a product and
the rest without one.

Pins a FIXED number of statements whatever the page or its depth, and that the product pages are total (no product
repeated or skipped). Prints (`-s`) the timings next to the list's Métricas sort over the same set -- the existing
whole-set Board read this view is compared with -- recorded in the PR, never asserted (a wall-clock bound would be
flaky on a shared CI box).
"""

# ruff: noqa: F811 -- the fixtures are imported and used by name

from __future__ import annotations

import time

import pytest
from sqlalchemy import event, text

from app.core.config import settings
from app.services.ml_publications.view import products
from app.services.ml_publications.view.filters import parse_filter
from tests.services.ml_daily_metrics import test_board_volume_postgres as volume
from tests.services.ml_publications.view.test_metrics_sort_volume_postgres import run as run_list
from tests.services.ml_publications.view.test_metrics_sort_volume_postgres import world as unlinked_world  # noqa: F401

pytestmark = [pytest.mark.postgres, pytest.mark.volume]


@pytest.fixture(scope="module")
def world(unlinked_world):  # noqa: F811
    """The volume seed with its publications linked: one in ten has no product, the rest spread over the 2.000.
    Once per module, like the seed it builds on (this module's own copy of it): every test only reads."""
    env = unlinked_world.get_bind()
    with env.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ml_item_product_links (item_id, variation_id, source, match_status, producto_item_id, "
                "linked_at) SELECT item_id, 0, 'sku_auto', 'linked', 800001 + n % 2000, now() "
                "FROM (SELECT item_id, row_number() OVER (ORDER BY item_id) AS n FROM ml_items) AS numbered "
                "WHERE n % 10 <> 0"
            )
        )
    with env.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("ANALYZE ml_item_product_links"))
    return unlinked_world


def run(db, orden: str, offset: int, limit: int = 50, **filters: str):
    recorder = volume._Recorder()
    connection = db.connection()
    event.listen(connection, "before_cursor_execute", recorder.before)
    event.listen(connection, "after_cursor_execute", recorder.after)
    started = time.perf_counter()
    try:
        page = products.list_products(db, parse_filter(**filters), orden, True, limit, offset)
    finally:
        event.remove(connection, "before_cursor_execute", recorder.before)
        event.remove(connection, "after_cursor_execute", recorder.after)
    db.rollback()  # each request ends its transaction, as the router does
    return page, recorder, (time.perf_counter() - started) * 1000


@pytest.mark.parametrize("persisted", [False, True], ids=["live", "persisted"])
def test_page_one_and_a_deep_page_cost_the_same_statements(world, monkeypatch, persisted) -> None:
    monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", persisted)
    source = "persisted" if persisted else "live"
    counts = set()
    for orden in ("facturado_30d", "markup_30d", "titulo"):
        for offset in (0, 1_750):
            page, recorder, first_ms = run(world, orden, offset)
            best = min([first_ms] + [run(world, orden, offset)[2] for _ in range(2)])
            assert page.mla_count == 25_000 and page.rows
            counts.add(len(recorder.statements))
            volume._print(f"\nproducts {orden} ({source}) offset={offset} best={best:.0f} ms", recorder, first_ms)
    baseline = min(run_list(world, "facturado_30d", 0)[2] for _ in range(3))
    print(f"\nbaseline: /items facturado_30d ({source}) page 1 best={baseline:.0f} ms")
    assert len(counts) == 1, counts


def test_the_product_pages_are_total(world) -> None:
    first = run(world, "facturado_30d", 0, limit=200)[0]
    pages = [first] + [run(world, "facturado_30d", offset, limit=200)[0] for offset in range(200, first.total, 200)]
    seen = [row.key for page in pages for row in page.rows]
    assert len(seen) == len(set(seen)) == first.total
