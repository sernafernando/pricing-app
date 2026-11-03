"""Unit coverage for publicacion_repair worker handlers (gates + registry)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest

from app.core.config import settings
from app.workers.context import WorkerContext
from app.workers.handlers import publicacion_repair as handlers
from app.workers.handlers.ml_publications import disabled_outcome
from app.workers.registry import ML_PUBLICATIONS_REGISTRY


def _ctx(seconds: float = 30) -> WorkerContext:
    return WorkerContext(deadline=datetime.now(UTC) + timedelta(seconds=seconds), worker_name="test")


def test_envio_handler_respects_kill_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", True)
    monkeypatch.setattr(settings, "ML_ITEM_DATA_WRITE_ENABLED", True)
    result = handlers.EnvioRepairHandler(pacer=mock.Mock()).run(_ctx())
    assert result == disabled_outcome()


def test_sku_handler_respects_writes_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)
    monkeypatch.setattr(settings, "ML_ITEM_DATA_WRITE_ENABLED", False)
    result = handlers.SkuRepairHandler(pacer=mock.Mock()).run(_ctx())
    assert result == disabled_outcome()


def test_envio_handler_wires_pacer_and_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)
    monkeypatch.setattr(settings, "ML_ITEM_DATA_WRITE_ENABLED", True)
    pacer = mock.Mock()
    pacer.acquire.return_value = handlers.GRANTED

    async def fake_run(**kwargs):
        assert kwargs["pacing_seconds"] == 0
        assert kwargs["before_write"] is not None
        assert kwargs["on_rate_limited"] is not None
        assert kwargs["before_write"]() is True
        pacer.acquire.assert_called()
        return {"scanned": 0, "changed": 0, "skipped": 0, "errors": 0}

    monkeypatch.setattr(handlers, "run_envio_repair", fake_run)
    result = handlers.EnvioRepairHandler(pacer=pacer).run(_ctx())
    assert result.success is True
    assert result.detail["scanned"] == 0


def test_sku_handler_wires_pacer_on_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ML_PUB_KILL_SWITCH", False)
    monkeypatch.setattr(settings, "ML_ITEM_DATA_WRITE_ENABLED", True)
    pacer = mock.Mock()
    pacer.acquire.return_value = handlers.GRANTED

    async def fake_run(**kwargs):
        assert kwargs["on_rate_limited"] is not None
        kwargs["on_rate_limited"]("15")
        pacer.on_rate_limited.assert_called_once_with(handlers.PACER_FAMILY_SKU, "15")
        return {"scanned": 0, "changed": 0, "skipped": 0, "errors": 0}

    monkeypatch.setattr(handlers, "run_sku_repair", fake_run)
    result = handlers.SkuRepairHandler(pacer=pacer).run(_ctx())
    assert result.success is True


def test_handlers_registered_in_ml_publications_registry() -> None:
    names = {getattr(h, "name", None) for h in ML_PUBLICATIONS_REGISTRY}
    assert handlers.ENVIO_HANDLER in names
    assert handlers.SKU_HANDLER in names
