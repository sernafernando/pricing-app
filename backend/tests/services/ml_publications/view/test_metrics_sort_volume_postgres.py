"""The Métricas sorts of the Publicaciones list (`orden` facturado_30d...) on the board's volume seed: 2.000 products,
6.000 sold publications and 81.000 order groups over 18 months (`test_board_volume_postgres._seed`), inside a store of
25.000 publications (the 6.000 plus 19.000 that never sold).

Pins a FIXED number of statements whatever the page or its depth and that the ranking is total across pages;
prints the timings (`-s`) of page 1 and a deep page on both lines sources -- recorded in the PR, never asserted (a
wall-clock bound would be flaky on a shared CI box).
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.ml_daily_metrics import board
from app.services.ml_publications.view import listing
from app.services.ml_publications.view.filters import parse_filter
from tests.services.ml_daily_metrics import test_board_volume_postgres as volume
from tests.services.ml_daily_metrics.test_board_sale_lines_postgres import populate_sale_lines
from tests.services.ml_publications.conftest import module_env
from tests.services.ml_publications.view import seed

pytestmark = [pytest.mark.postgres, pytest.mark.volume]

STORE = 25_000


@pytest.fixture(scope="module")
def world():
    """Seeded once per module: every test only reads it, and `run` rolls the reader back after each request.
    `reader.get_bind()` is the engine of the schema."""
    from app.models.ml_sale_line import MlSaleLine

    with module_env() as env:
        seed.create_board_tables(env)
        MlSaleLine.__table__.create(bind=env)
        session = sessionmaker(bind=env)()
        started = time.perf_counter()
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(settings, "ML_USER_ID", 999)
            volume._seed(session)
            session.execute(
                text(
                    "INSERT INTO ml_items (item_id, title, status, last_trigger_received_at) "
                    "SELECT CASE WHEN i <= :sold THEN 'MLA77' || lpad(i::text, 6, '0') "
                    "ELSE 'MLA88' || lpad(i::text, 6, '0') "
                    "END, 'Publicacion ' || i, (ARRAY['active','active','paused'])[1 + i % 3], "
                    "now() - (i || ' s')::interval "
                    "FROM generate_series(1, :store) AS i"
                ),
                {"sold": volume.PUBLICATIONS, "store": STORE},
            )
            populate_sale_lines(session)
        session.commit()
        session.close()
        with env.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            for name in ("ml_items", "ml_sale_lines"):
                conn.execute(text(f"ANALYZE {name}"))
        print(f"\nvolume seeded in {time.perf_counter() - started:.1f} s")
        reader = sessionmaker(bind=env)()
        yield reader
        reader.rollback()
        reader.close()


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(board, "now_utc", lambda: volume.NOW)
    monkeypatch.setattr(settings, "ML_USER_ID", 999)


def run(db, orden: str, offset: int, limit: int = 50, **filters: str):
    recorder = volume._Recorder()
    connection = db.connection()
    event.listen(connection, "before_cursor_execute", recorder.before)
    event.listen(connection, "after_cursor_execute", recorder.after)
    started = time.perf_counter()
    try:
        page = listing.list_items(
            db,
            parse_filter(**filters),
            listing.parse_sort(orden, "desc"),
            limit,
            offset,
            events=False,
            can_see_margin=True,
        )
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
    for orden in ("facturado_30d", "unidades_7d", "markup_30d"):
        for offset in (0, 20_000):
            page, recorder, first_ms = run(world, orden, offset)
            best = min([first_ms] + [run(world, orden, offset)[2] for _ in range(2)])
            assert page.total == STORE and len(page.items) == 50
            counts.add(len(recorder.statements))
            volume._print(f"\n{orden} ({source}) offset={offset} best={best:.0f} ms", recorder, first_ms)
    filtered, recorder, ms = run(world, "facturado_30d", 0, estado="active")
    print(
        f"\nfacturado_30d ({source}) estado=active total={filtered.total}: {len(recorder.statements)} statements, {ms:.0f} ms"
    )
    assert len(counts) == 1, counts


def test_the_ranking_is_total_across_pages(world) -> None:
    pages = [run(world, "facturado_30d", offset, limit=100)[0] for offset in range(0, 6_100, 100)]
    seen = [item["item_id"] for page in pages for item in page.items]
    assert len(seen) == len(set(seen)) == 6_100
    # the 6.000 that sold lead (each sold in the 30 days on the seed or not), the never-sold follow by item_id
    assert seen[-100:] == sorted(seen[-100:])
