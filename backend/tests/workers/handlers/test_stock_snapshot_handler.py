"""`stock.snapshot` (auditoria-stock-rotacion L1): the existing ML worker (`pricing-worker-ml`) takes the day's stock
photo once a day and prunes what is older than 400 days on the same run. No cron."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta

from app.workers.context import WorkerContext
from app.workers.handlers import stock_snapshot as module
from app.workers.handlers.stock_snapshot import snapshot as handler
from app.workers import registry


def _ctx() -> WorkerContext:
    return WorkerContext(deadline=datetime.now(UTC) + timedelta(seconds=60), worker_name="w")


class FakeSession:
    def __init__(self, log: list) -> None:
        self.log = log

    def commit(self) -> None:
        self.log.append("commit")


def _wire(monkeypatch, log: list, *, fail: bool = False) -> None:
    @contextmanager
    def session():
        yield FakeSession(log)

    def take(db, day):
        if fail:
            raise RuntimeError("boom")
        log.append(("take", day))
        return 7

    monkeypatch.setattr(module, "get_background_db", session)
    monkeypatch.setattr(module.stock_snapshot, "take", take)
    monkeypatch.setattr(module.stock_snapshot, "prune", lambda db, day: log.append(("prune", day)) or 3)
    monkeypatch.setattr(module.board, "today_business", lambda: date(2026, 11, 18))


def test_it_runs_in_the_existing_worker_once_a_day() -> None:
    assert handler in registry.ML_PUBLICATIONS_REGISTRY
    assert handler not in registry.REGISTRY  # it reads the ML store: never in the sales worker (design D1)
    assert not getattr(handler, "own_thread", False)  # the drain pass honours its daily slot
    assert (handler.name, handler.channels, handler.interval) == ("stock.snapshot", (), None)
    assert isinstance(handler.run_at_local, time)


def test_it_takes_todays_photo_and_prunes_on_the_same_run(monkeypatch) -> None:
    log: list = []
    _wire(monkeypatch, log)
    result = handler.run(_ctx())
    assert result.success
    assert result.detail == {"fecha": "2026-11-18", "productos": 7, "borrados": 3}
    assert log == [("take", date(2026, 11, 18)), ("prune", date(2026, 11, 18)), "commit"]


def test_a_failure_is_reported_and_nothing_is_committed(monkeypatch) -> None:
    log: list = []
    _wire(monkeypatch, log, fail=True)
    result = handler.run(_ctx())
    assert not result.success and "boom" in result.error
    assert "commit" not in log
