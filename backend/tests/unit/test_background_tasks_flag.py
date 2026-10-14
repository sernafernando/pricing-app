"""`BACKGROUND_TASKS_ENABLED`: lets an API instance that shares a database with production run without the
in-process background loops (ML bot ingest/draft/publish, order syncs, reconcilers...).

A staging copy of the API ran every one of them against the production database in parallel with production, which
risks double bot replies to customers. The per-host lock cannot see another host.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator

import pytest

from app import main
from app.core.config import settings

# Every task factory `lifespan` schedules. The first four are the ones the incident named.
TASK_FACTORIES = (
    "sync_pedidos_preparacion_task",
    "free_shipping_auto_fix_task",
    "sync_sale_orders_task",
    "ml_questions_ingest_task",
    "ml_questions_draft_task",
    "ml_questions_publish_task",
    "ml_messages_ingest_task",
    "ml_messages_draft_task",
    "vikunja_reconcile_task",
    "oc_match_reclaim_task",
)


@pytest.fixture()
def scheduled(monkeypatch, tmp_path) -> Iterator[list[str]]:
    """Replaces every task factory with a recording stub; the bg lock is always won."""
    started: list[str] = []

    def stub(name: str):
        async def run() -> None:
            started.append(name)

        return run

    for name in TASK_FACTORIES:
        monkeypatch.setattr(main, name, stub(name))
    lock_file = open(tmp_path / "bg.lock", "w")
    monkeypatch.setattr(main, "_try_acquire_bg_lock", lambda: lock_file)
    yield started
    lock_file.close()


def run_lifespan() -> None:
    async def go() -> None:
        async with main.lifespan(main.app):
            await asyncio.sleep(0)  # let the scheduled tasks start

    asyncio.run(go())


def test_the_list_above_is_every_task_factory_main_imports() -> None:
    """A task added to `lifespan` must be listed in TASK_FACTORIES, or the tests would start the real one."""
    imported = {name for name in vars(main) if name.endswith("_task") and callable(getattr(main, name))}
    assert imported == set(TASK_FACTORIES)


def test_the_flag_defaults_to_true() -> None:
    assert type(settings).model_fields["BACKGROUND_TASKS_ENABLED"].default is True


def test_with_the_flag_false_no_task_is_scheduled(scheduled, monkeypatch, caplog) -> None:
    monkeypatch.setattr(settings, "BACKGROUND_TASKS_ENABLED", False)
    with caplog.at_level(logging.INFO):
        run_lifespan()
    assert scheduled == []
    lines = [r.getMessage() for r in caplog.records if "BACKGROUND_TASKS_ENABLED" in r.getMessage()]
    assert len(lines) == 1 and "disabled" in lines[0].lower()


def test_with_the_flag_false_the_bg_lock_is_not_even_taken(monkeypatch) -> None:
    monkeypatch.setattr(settings, "BACKGROUND_TASKS_ENABLED", False)

    def lock_must_not_be_taken():
        raise AssertionError("the bg lock must not be acquired when background tasks are disabled")

    monkeypatch.setattr(main, "_try_acquire_bg_lock", lock_must_not_be_taken)
    run_lifespan()


def test_with_the_flag_true_the_current_set_is_scheduled(scheduled, monkeypatch) -> None:
    monkeypatch.setattr(settings, "BACKGROUND_TASKS_ENABLED", True)
    run_lifespan()
    assert sorted(scheduled) == sorted(TASK_FACTORIES)


def test_by_default_the_current_set_is_scheduled(scheduled) -> None:
    assert settings.BACKGROUND_TASKS_ENABLED is True
    run_lifespan()
    assert sorted(scheduled) == sorted(TASK_FACTORIES)


def test_a_worker_that_loses_the_lock_still_schedules_nothing(scheduled, monkeypatch) -> None:
    monkeypatch.setattr(main, "_try_acquire_bg_lock", lambda: None)
    run_lifespan()
    assert scheduled == []
