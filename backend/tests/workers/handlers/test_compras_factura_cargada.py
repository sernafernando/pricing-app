"""`compras.factura_cargada_alerts`: minute sweep on the main worker (no cron)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.workers.context import WorkerContext
from app.workers.handlers.compras_factura_cargada import (
    HANDLER_NAME,
    ComprasFacturaCargadaAlertsHandler,
    factura_cargada_alerts,
)
from app.workers.registry import REGISTRY


class _Sessions:
    def __init__(self, db) -> None:
        self.db = db
        self.opened = 0

    @contextmanager
    def __call__(self):
        self.opened += 1
        yield self.db


def test_handler_registered_on_main_registry() -> None:
    assert factura_cargada_alerts in REGISTRY
    assert factura_cargada_alerts.name == HANDLER_NAME
    assert factura_cargada_alerts.interval == timedelta(minutes=1)
    assert factura_cargada_alerts.channels == ()
    assert factura_cargada_alerts.run_at_local is None


def test_run_calls_sweep_and_reports_fired(db) -> None:
    sessions = _Sessions(db)
    handler = ComprasFacturaCargadaAlertsHandler()
    ctx = WorkerContext(deadline=datetime.now(UTC) + timedelta(seconds=30))
    with (
        patch("app.workers.handlers.compras_factura_cargada.get_background_db", sessions),
        patch(
            "app.workers.handlers.compras_factura_cargada.compras_alertas_service.disparar_alertas_factura_pendientes",
            return_value=2,
        ) as sweep,
    ):
        result = handler.run(ctx)
    assert sessions.opened == 1
    sweep.assert_called_once_with(db)
    assert result.success is True
    assert result.detail == {"fired": 2}
    assert result.error is None


def test_run_failure_is_job_result_not_raise(db) -> None:
    sessions = _Sessions(db)
    handler = ComprasFacturaCargadaAlertsHandler()
    ctx = WorkerContext(deadline=datetime.now(UTC) + timedelta(seconds=30))
    with (
        patch("app.workers.handlers.compras_factura_cargada.get_background_db", sessions),
        patch(
            "app.workers.handlers.compras_factura_cargada.compras_alertas_service.disparar_alertas_factura_pendientes",
            side_effect=RuntimeError("db down"),
        ),
    ):
        result = handler.run(ctx)
    assert result.success is False
    assert result.error is not None
    assert "RuntimeError" in result.error
