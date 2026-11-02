"""Unit tests for Gestión Full reconcile helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.gestion_full.reconcile import CLOSE_AFTER_IDLE, _op_from_ml_row, reconcile_envio

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ml_fulfillment" / "inbound_reception_probe_notes.json"


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


def test_op_from_ml_row_parses_captured_live_operation() -> None:
    """Fernando: load captured_live_operation from the probe fixture (not only synthetic rows)."""
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    row = payload["captured_live_operation"]
    inventory_id = str(row.get("inventory_id") or "ZLKG92545")
    parsed = _op_from_ml_row(row, inventory_id=inventory_id)
    assert parsed is not None
    assert parsed["inbound_id"] == "79909756"
    assert parsed["operation_id"] == 7604247737135372849
    assert parsed["cantidad"] == 12
    assert parsed["inventory_id"] == inventory_id


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


def test_ensure_envio_reopens_closed_row() -> None:
    from app.services.gestion_full.reconcile import ensure_envio

    closed = SimpleNamespace(
        inbound_id="SAME",
        package_id=1,
        week_monday=None,
        reception_closed_at=datetime(2026, 10, 30, tzinfo=UTC),
    )
    pkg = SimpleNamespace(id=1, week_monday=datetime(2026, 10, 26, tzinfo=UTC).date())
    db = MagicMock()
    db.get.return_value = closed

    out = ensure_envio(db, package=pkg, inbound_id="SAME", commit=False)
    assert out is closed
    assert closed.reception_closed_at is None
    db.flush.assert_called_once()
    db.add.assert_not_called()


def test_handler_fails_when_every_envio_errors() -> None:
    from app.workers.handlers.gestion_full_reconcile import GestionFullReconcileHandler

    class _SessionCM:
        def __enter__(self) -> MagicMock:
            db = MagicMock()
            db.get.return_value = SimpleNamespace(inbound_id="INB-1")
            return db

        def __exit__(self, *args: object) -> None:
            return None

    handler = GestionFullReconcileHandler(
        client_factory=lambda _p: MagicMock(),
        session_factory=_SessionCM,
        now=lambda: datetime(2026, 10, 31, tzinfo=UTC),
    )
    ctx = SimpleNamespace(stop_requested=lambda: False)
    with (
        patch(
            "app.workers.handlers.gestion_full_reconcile.list_open_envios",
            return_value=[SimpleNamespace(inbound_id="INB-1")],
        ),
        patch(
            "app.workers.handlers.gestion_full_reconcile.reconcile_envio",
            side_effect=RuntimeError("boom"),
        ),
    ):
        result = handler.run(ctx)
    assert result.success is False
    assert result.detail["results"][0]["error"] is True


def test_list_open_envios_orders_last_polled_nulls_first() -> None:
    from app.services.gestion_full.reconcile import list_open_envios

    db = MagicMock()
    filtered = db.query.return_value.filter.return_value
    filtered.order_by.return_value.all.return_value = []
    list_open_envios(db)
    assert filtered.order_by.called
    # SQLAlchemy ClauseList — stringify args to pin nullsfirst + created_at + inbound_id
    ordered = " ".join(str(a) for a in filtered.order_by.call_args[0])
    assert "last_polled_at" in ordered
    assert "created_at" in ordered


def test_reconcile_dedupes_inventory_ids() -> None:
    """Two package lines sharing inventory_id must not double-call ML (IntegrityError risk)."""
    db = MagicMock()
    db.query.return_value.filter_by.return_value.all.return_value = [
        SimpleNamespace(inventory_id="INV-DUP"),
        SimpleNamespace(inventory_id="INV-DUP"),
    ]
    client = MagicMock()
    client.get.return_value = SimpleNamespace(status=200, body={"results": []})
    envio = SimpleNamespace(
        inbound_id="INB-1",
        package_id=1,
        reception_closed_at=None,
        last_reception_at=None,
        last_polled_at=None,
    )
    now = datetime(2026, 11, 2, tzinfo=UTC)
    with patch("app.core.config.settings.ML_USER_ID", "1"):
        reconcile_envio(db, envio, client=client, now=now)
    assert client.get.call_count == 1
