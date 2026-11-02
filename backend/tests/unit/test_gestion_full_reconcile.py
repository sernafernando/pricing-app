"""Unit tests for Gestión Full reconcile helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.gestion_full.reconcile import CLOSE_AFTER_IDLE, _op_from_ml_row, reconcile_envio


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


def _envio(*, created_days_ago: int = 5, last_reception_days_ago: int | None = None) -> SimpleNamespace:
    now = datetime(2026, 11, 2, tzinfo=UTC)
    last = None
    if last_reception_days_ago is not None:
        last = now - timedelta(days=last_reception_days_ago)
    return SimpleNamespace(
        inbound_id="INB-1",
        package_id=1,
        reception_closed_at=None,
        last_reception_at=last,
        created_at=now - timedelta(days=created_days_ago),
    )


def test_reconcile_does_not_close_without_reception_even_if_old() -> None:
    """Idle clock must not use created_at — never-received envíos stay open."""
    db = MagicMock()
    db.query.return_value.filter_by.return_value.all.return_value = [SimpleNamespace(inventory_id="INV1")]
    client = MagicMock()
    client.get.return_value = SimpleNamespace(status=200, body={"results": []})
    envio = _envio(created_days_ago=10, last_reception_days_ago=None)
    now = datetime(2026, 11, 2, tzinfo=UTC)

    with patch("app.core.config.settings.ML_USER_ID", "1"):
        out = reconcile_envio(db, envio, client=client, now=now)

    assert out["closed"] is False
    assert envio.reception_closed_at is None


def test_reconcile_does_not_close_when_ml_fails() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.all.return_value = [SimpleNamespace(inventory_id="INV1")]
    client = MagicMock()
    client.get.return_value = SimpleNamespace(status=429, body={"message": "rate"})
    envio = _envio(created_days_ago=10, last_reception_days_ago=5)
    now = datetime(2026, 11, 2, tzinfo=UTC)

    with patch("app.core.config.settings.ML_USER_ID", "1"):
        out = reconcile_envio(db, envio, client=client, now=now)

    assert out["closed"] is False
    assert out["ml_fail"] == 1
    assert envio.reception_closed_at is None


def test_reconcile_closes_after_idle_from_last_reception() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.all.return_value = [SimpleNamespace(inventory_id="INV1")]
    client = MagicMock()
    client.get.return_value = SimpleNamespace(status=200, body={"results": []})
    envio = _envio(created_days_ago=10, last_reception_days_ago=4)
    now = datetime(2026, 11, 2, tzinfo=UTC)

    with patch("app.core.config.settings.ML_USER_ID", "1"):
        out = reconcile_envio(db, envio, client=client, now=now)

    assert out["closed"] is True
    assert envio.reception_closed_at == now
