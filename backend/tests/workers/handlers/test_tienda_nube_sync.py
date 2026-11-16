"""`tienda_nube.sync` (abm-productos L12): the Tienda Nube catalog sync moves from cron (every 15 minutes, 06-21 h) to a
worker handler with the same cadence. Outside those hours it does nothing; a failed fetch writes nothing."""

# ruff: noqa: F811 -- the fixture is imported and used by name

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.workers.context import WorkerContext
from app.workers.handlers import tienda_nube_sync
from app.workers.handlers.tienda_nube_sync import sync as handler
from app.workers.registry import REGISTRY
from app.workers.scheduling import ARGENTINA_TZ
from tests.services.tienda_nube_pg import erp, links, tn_pg, tn_product  # noqa: F401


def ctx() -> WorkerContext:
    return WorkerContext(deadline=datetime.now(UTC) + timedelta(seconds=60))


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 16, hour, minute, tzinfo=ARGENTINA_TZ)


def test_it_is_registered_every_15_minutes_and_schedule_only() -> None:
    assert handler in REGISTRY
    assert handler.name == "tienda_nube.sync"
    assert handler.interval == timedelta(minutes=15)
    assert handler.channels == ()
    assert handler.run_at_local is None


@pytest.mark.parametrize(("hour", "minute", "inside"), [(5, 59, False), (6, 0, True), (21, 45, True), (22, 0, False)])
def test_business_hours_are_the_old_cron_ones(hour: int, minute: int, inside: bool) -> None:
    assert tienda_nube_sync.en_horario(at(hour, minute)) is inside


def test_outside_business_hours_it_fetches_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tienda_nube_sync, "_now", lambda: at(23))
    monkeypatch.setattr(tienda_nube_sync, "fetch_productos", lambda **_: pytest.fail("fetched outside hours"))

    result = handler.run(ctx())

    assert result.success is True
    assert result.detail == {"skipped": "fuera de horario"}


@pytest.mark.postgres
def test_inside_business_hours_it_syncs_the_fetched_catalog(tn_pg, monkeypatch: pytest.MonkeyPatch) -> None:
    with tn_pg.begin() as conn:
        erp(conn, 10, "7790001", "NB")
    monkeypatch.setattr(tienda_nube_sync, "_now", lambda: at(10))
    monkeypatch.setattr(
        tienda_nube_sync,
        "fetch_productos",
        lambda **_: ([tn_product(1, "NB", ["7790001"], description="<p>d</p>")], True),
    )

    result = handler.run(ctx())

    assert result.success is True
    assert result.detail["con_erp"] == 1
    with tn_pg.connect() as conn:
        assert links(conn) == {1: 10}
        assert conn.execute(text("SELECT descripcion_texto FROM tienda_nube_producto_textos")).scalar_one() == "d"


@pytest.mark.postgres
def test_a_failed_or_empty_fetch_writes_nothing(tn_pg, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tienda_nube_sync, "_now", lambda: at(10))

    def boom(**_):
        raise RuntimeError("TN 503")

    monkeypatch.setattr(tienda_nube_sync, "fetch_productos", boom)
    failed = handler.run(ctx())
    monkeypatch.setattr(tienda_nube_sync, "fetch_productos", lambda **_: ([], False))
    empty = handler.run(ctx())

    assert failed.success is False and "TN 503" in failed.error
    assert empty.success is False
    with tn_pg.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM tienda_nube_productos")).scalar_one() == 0
