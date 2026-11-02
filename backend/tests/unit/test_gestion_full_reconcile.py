"""Unit tests for Gestión Full reconcile helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.gestion_full.reconcile import CLOSE_AFTER_IDLE, _op_from_ml_row


def test_op_from_ml_row_parses_inbound_reception() -> None:
    row = {
        "id": 99,
        "type": "INBOUND_RECEPTION",
        "date_created": "2026-10-30T12:00:00Z",
        "detail": {"available_quantity": 4},
        "external_references": [{"type": "inbound_id", "value": "81061502"}],
    }
    parsed = _op_from_ml_row(row, inventory_id="INV1")
    assert parsed is not None
    assert parsed["inbound_id"] == "81061502"
    assert parsed["operation_id"] == 99
    assert parsed["cantidad"] == 4
    assert parsed["inventory_id"] == "INV1"


def test_op_from_ml_row_skips_other_types() -> None:
    assert _op_from_ml_row({"type": "SALE", "id": 1}, inventory_id="X") is None


def test_close_after_idle_constant() -> None:
    assert CLOSE_AFTER_IDLE == timedelta(days=3)


def test_reconcile_handler_uses_inbound_id_strings_not_detached_orm() -> None:
    """Listing session closes before reconcile; must not read detached ORM attrs."""
    from app.workers.handlers.gestion_full_reconcile import GestionFullReconcileHandler

    class _DetachingEnvio:
        def __init__(self, inbound_id: str) -> None:
            self._inbound_id = inbound_id
            self._live = True

        @property
        def inbound_id(self) -> str:
            if not self._live:
                raise RuntimeError("DetachedInstanceError: inbound_id")
            return self._inbound_id

        def expire(self) -> None:
            self._live = False

    envio = _DetachingEnvio("INB-1")
    row = SimpleNamespace(inbound_id="INB-1")
    call_n = {"n": 0}

    class _SessionCM:
        def __init__(self) -> None:
            self.db = MagicMock()
            call_n["n"] += 1
            if call_n["n"] >= 2:
                self.db.get.return_value = row

        def __enter__(self) -> MagicMock:
            return self.db

        def __exit__(self, *args: object) -> None:
            envio.expire()

    reconcile = MagicMock(return_value={"inbound_id": "INB-1", "ok": True})
    handler = GestionFullReconcileHandler(
        client_factory=lambda _p: MagicMock(),
        session_factory=_SessionCM,
        now=lambda: datetime(2026, 10, 31, tzinfo=UTC),
    )
    ctx = SimpleNamespace(stop_requested=lambda: False)

    with (
        patch(
            "app.workers.handlers.gestion_full_reconcile.list_open_envios",
            return_value=[envio],
        ),
        patch("app.workers.handlers.gestion_full_reconcile.reconcile_envio", reconcile),
    ):
        result = handler.run(ctx)

    assert result.success is True
    assert result.detail["reconciled"] == 1
    reconcile.assert_called_once()
