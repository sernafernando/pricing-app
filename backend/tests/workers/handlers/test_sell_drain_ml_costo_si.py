"""`sell.drain` re-freezes the ML sales a costo SI change re-costs (`ml_costo_si_dirty`, sell-in-costo-si T3 PR 7,
L15) after the costo SI pass, in bounded passes, and that step never fails the sales job."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from app.services.ml_orders_ingestion.recongelar_costo_si import Drenado
from app.workers.context import WorkerContext
from app.workers.handlers import sell_drain as module


def _ctx() -> WorkerContext:
    return WorkerContext(deadline=datetime.now(UTC) + timedelta(seconds=60), worker_name="w")


class _Db:
    def get_bind(self):
        return type("B", (), {"dialect": type("D", (), {"name": "postgresql"})()})()


def _wire(monkeypatch, pendientes: bool, calls: list) -> None:
    @contextmanager
    def session():
        yield _Db()

    def drenar(factory, deadline, *, is_transient):
        calls.append({"is_transient": is_transient, "deadline": deadline})
        return Drenado(productos=2, filas=7, fallidos={9: "x"})

    monkeypatch.setattr(module, "get_background_db", session)
    monkeypatch.setattr(module.recongelar_costo_si, "hay_pendientes", lambda db: pendientes)
    monkeypatch.setattr(module.recongelar_costo_si, "drenar", drenar)


def test_it_refreezes_the_queued_products_within_the_jobs_deadline(monkeypatch) -> None:
    calls: list = []
    _wire(monkeypatch, True, calls)
    ctx = _ctx()

    assert module._drain_ml_costo_si(ctx) == {"ml_costo_si": 2, "ml_costo_si_filas": 7, "ml_costo_si_fallidos": 1}
    assert calls == [{"is_transient": module.is_transient, "deadline": ctx.deadline}]


def test_an_empty_queue_reports_nothing(monkeypatch) -> None:
    calls: list = []
    _wire(monkeypatch, False, calls)

    assert module._drain_ml_costo_si(_ctx()) == {}
    assert calls == []


def test_a_failure_never_fails_the_sales_job(monkeypatch) -> None:
    calls: list = []
    _wire(monkeypatch, True, calls)

    def roto(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(module.recongelar_costo_si, "drenar", roto)

    assert module._drain_ml_costo_si(_ctx()) == {"ml_costo_si_error": "RuntimeError: boom"}


def test_the_run_drains_it_after_the_costo_si_pass(monkeypatch) -> None:
    orden: list = []
    monkeypatch.setattr(module, "_drain_costo_si", lambda ctx: orden.append("costo_si") or {"costo_si": 1})
    monkeypatch.setattr(module, "_drain_ml_costo_si", lambda ctx: orden.append("ml") or {"ml_costo_si": 1})

    @contextmanager
    def session():
        yield type(
            "Db", (), {"get_bind": lambda self: type("B", (), {"dialect": type("D", (), {"name": "sqlite"})()})()}
        )()

    monkeypatch.setattr(module, "get_background_db", session)

    result = module.drain.run(_ctx())

    assert orden == ["costo_si", "ml"]
    assert result.success and result.detail["ml_costo_si"] == 1
