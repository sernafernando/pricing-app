"""Unit tests for Gestión Full reconcile helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

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
