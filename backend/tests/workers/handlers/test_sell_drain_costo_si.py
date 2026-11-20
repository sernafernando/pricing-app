"""`sell.drain` also drains the costo SI queue (sell-in-costo-si T2, S8), without ever calling Mercado Libre: it is
the sales worker (design D1); the Full operations it reads were fetched by `stock.snapshot` in the ML worker."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

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

    def drenar(factory, deadline, hoy, *, ml, is_transient):
        calls.append({"ml": ml, "hoy": hoy, "is_transient": is_transient})
        return Drenado(productos=3, cambiados=2, fallidos={9: "x"})

    monkeypatch.setattr(module, "get_background_db", session)
    monkeypatch.setattr(module.costo_si_queue, "hay_pendientes", lambda db: pendientes)
    monkeypatch.setattr(module.costo_si_queue, "drenar", drenar)
    monkeypatch.setattr("app.services.ml_daily_metrics.board.today_business", lambda: date(2026, 11, 20))


def test_it_drains_the_queued_products_without_an_ml_client(monkeypatch) -> None:
    calls: list = []
    _wire(monkeypatch, True, calls)

    assert module._drain_costo_si(_ctx()) == {"costo_si": 3, "costo_si_cambiados": 2, "costo_si_fallidos": 1}
    assert calls == [{"ml": None, "hoy": date(2026, 11, 20), "is_transient": module.is_transient}]


def test_an_empty_queue_costs_one_query_and_reports_nothing(monkeypatch) -> None:
    calls: list = []
    _wire(monkeypatch, False, calls)

    assert module._drain_costo_si(_ctx()) == {}
    assert calls == []
