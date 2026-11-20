"""`sell.drain` also drains the costo SI queue (sell-in-costo-si T2, S8), without ever calling Mercado Libre: it is
the sales worker (design D1); costo SI's Full comes from the ML stock and sales the app already stores (owner L11)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from app.services.costo_si.queue import Drenado
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
        calls.append({"is_transient": is_transient})
        return Drenado(productos=3, cambiados=2, fallidos={9: "x"})

    monkeypatch.setattr(module, "get_background_db", session)
    monkeypatch.setattr(module.costo_si_queue, "hay_pendientes", lambda db: pendientes)
    monkeypatch.setattr(module.costo_si_queue, "drenar", drenar)


def test_it_drains_the_queued_products_without_an_ml_client(monkeypatch) -> None:
    calls: list = []
    _wire(monkeypatch, True, calls)

    assert module._drain_costo_si(_ctx()) == {
        "costo_si": 3,
        "costo_si_cambiados": 2,
        "costo_si_fallidos": 1,
    }
    assert calls == [{"is_transient": module.is_transient}]


def test_an_empty_queue_costs_one_query_and_reports_nothing(monkeypatch) -> None:
    calls: list = []
    _wire(monkeypatch, False, calls)

    assert module._drain_costo_si(_ctx()) == {}
    assert calls == []


def test_a_costo_si_failure_never_fails_the_sales_job(monkeypatch) -> None:
    """The sale lines already committed: a broken costo SI pass is reported, never raised."""
    calls: list = []
    _wire(monkeypatch, True, calls)

    def roto(db):
        raise RuntimeError("boom")

    monkeypatch.setattr(module.costo_si_queue, "hay_pendientes", roto)

    assert module._drain_costo_si(_ctx()) == {"costo_si_error": "RuntimeError: boom"}
