"""The Publicaciones page's Métricas figures (`row_metrics.metrics_by_mla`) on the board's volume seed: 2.000
products, 6.000 publications, 81.000 groups over 18 months (`test_board_volume_postgres._seed`).

Pins that the page's ONE Board costs a fixed number of statements whatever the page size, and that it hands back
rows proportional to the page, never to the store. Timing is printed (`-s`) and recorded in the PR, never asserted:
a wall-clock bound would be flaky on a shared CI box.
"""

# ruff: noqa: F811 -- `board_pg_engine` is the board's fixture, imported and used by name

from __future__ import annotations

import time

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.services.ml_daily_metrics import board
from app.services.ml_publications.view import row_metrics
from tests.services.ml_daily_metrics import test_board_volume_postgres as volume
from tests.services.ml_daily_metrics.conftest import board_pg_engine  # noqa: F401
from tests.services.ml_daily_metrics.test_board_sale_lines_postgres import populate_sale_lines

pytestmark = [pytest.mark.postgres, pytest.mark.volume]


@pytest.fixture(scope="module")
def world(board_pg_engine):
    connection = board_pg_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    volume._seed(session)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "ML_USER_ID", 999)
        populate_sale_lines(session)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr(board, "now_utc", lambda: volume.NOW)
    monkeypatch.setattr(settings, "ML_USER_ID", 999)


def page_of(size: int) -> list[str]:
    """`size` MLAs spread over the catalogue, as a page of the list would be."""
    step = volume.PUBLICATIONS // size
    return [f"MLA77{i:06d}" for i in range(1, volume.PUBLICATIONS + 1, step)][:size]


def measure(session, mlas: list[str]):
    recorder = volume._Recorder()
    connection = session.connection()
    event.listen(connection, "before_cursor_execute", recorder.before)
    event.listen(connection, "after_cursor_execute", recorder.after)
    started = time.perf_counter()
    try:
        got = row_metrics.metrics_by_mla(session, mlas)
    finally:
        event.remove(connection, "before_cursor_execute", recorder.before)
        event.remove(connection, "after_cursor_execute", recorder.after)
    return got, recorder, (time.perf_counter() - started) * 1000


@pytest.mark.parametrize("persisted", [False, True], ids=["live", "persisted"])
def test_one_board_per_page_whatever_its_size(world, monkeypatch, persisted) -> None:
    monkeypatch.setattr(settings, "METRICAS_SALE_LINES_ENABLED", persisted)
    counts = {}
    for size in (10, 50, 100):
        mlas = page_of(size)
        got, recorder, elapsed_ms = measure(world, mlas)
        best = elapsed_ms
        for _ in range(2):  # warm: the first run pays the plan cache
            best = min(best, measure(world, mlas)[2])
        assert set(got) == set(mlas)
        counts[size] = len(recorder.statements)
        volume._print(
            f"\nrow metrics ({'persisted' if persisted else 'live'}) page={size} best={best:.0f} ms",
            recorder,
            elapsed_ms,
        )
        # the page's rows, their pairs and 90 series points each: proportional to the page, never the store
        assert recorder.rows_returned < size * 100 + 50
    assert counts[10] == counts[50] == counts[100]
