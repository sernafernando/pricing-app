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
    monkeypatch.setattr(module, "_costo_si", lambda ctx, day: log.append(("costo_si", day)) or {})


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
    assert log == [
        ("take", date(2026, 11, 18)),
        ("prune", date(2026, 11, 18)),
        "commit",
        ("costo_si", date(2026, 11, 18)),  # costo SI only after the Auditoría's photo committed
    ]


def test_a_failure_is_reported_and_nothing_is_committed(monkeypatch) -> None:
    log: list = []
    _wire(monkeypatch, log, fail=True)
    result = handler.run(_ctx())
    assert not result.success and "boom" in result.error
    assert "commit" not in log


def _wire_costo_si(monkeypatch, log: list, *, falla: bool = False) -> None:
    """The costo SI part with its pieces replaced: what runs and in which order."""

    @contextmanager
    def session():
        yield FakeSession(log)

    def tomar(db, day, ahora, deadline):
        if falla:
            raise RuntimeError("photo broke")
        log.append(("foto", day))
        return 2

    monkeypatch.setattr(module, "get_background_db", session)
    monkeypatch.setattr(module.costo_si_foto, "tomar", tomar)
    monkeypatch.setattr(module.costo_si_queue, "encolar_vigentes", lambda db: log.append("encolar") or 2)


def test_costo_si_photographs_then_queues_without_calling_ml(monkeypatch) -> None:
    """sell-in-costo-si (S3, owner L11): the Full comes from the ML stock and sales the app already stores, so the
    costo SI part only takes the day's photo and re-queues; no Mercado Libre client exists here any more."""
    log: list = []
    _wire_costo_si(monkeypatch, log)

    detail = module._costo_si(_ctx(), date(2026, 11, 18))

    assert detail == {"costo_si_foto": 2, "costo_si_encolados": 2}
    assert log == [("foto", date(2026, 11, 18)), "encolar", "commit"]
    assert not hasattr(module, "nuevo_cliente_ml")


def test_a_costo_si_failure_never_fails_the_job(monkeypatch) -> None:
    _wire_costo_si(monkeypatch, [], falla=True)
    monkeypatch.setattr(module.stock_snapshot, "take", lambda db, day: 7)
    monkeypatch.setattr(module.stock_snapshot, "prune", lambda db, day: 3)
    monkeypatch.setattr(module.board, "today_business", lambda: date(2026, 11, 18))

    result = handler.run(_ctx())

    assert result.success
    assert result.detail == {
        "fecha": "2026-11-18",
        "productos": 7,
        "borrados": 3,
        "costo_si_error": "RuntimeError: photo broke",
    }
