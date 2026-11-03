"""Unit tests for the weekend inbound drip handler (no ML / no DB)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.workers.context import WorkerContext
from app.workers.handlers.gestion_full_inbound import GestionFullInboundHandler

AR = ZoneInfo("America/Argentina/Buenos_Aires")


def _ctx(*, deadline_seconds: int = 30) -> WorkerContext:
    now = datetime.now(UTC)
    return WorkerContext(deadline=now + timedelta(seconds=deadline_seconds), held_tokens=None)


def test_weekday_skip_is_success() -> None:
    # Wednesday 2026-10-28 12:00 AR
    wednesday = datetime(2026, 10, 28, 12, 0, tzinfo=AR).astimezone(UTC)
    handler = GestionFullInboundHandler(now=lambda: wednesday)
    result = handler.run(_ctx())
    assert result.success is True
    assert result.detail["skipped"] == "weekday"


def test_weekend_claims_and_refreshes() -> None:
    # Saturday 2026-10-31 10:00 AR
    saturday = datetime(2026, 10, 31, 10, 0, tzinfo=AR).astimezone(UTC)
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    handler = GestionFullInboundHandler(
        now=lambda: saturday,
        session_factory=lambda: session,
        client_factory=lambda pacer: MagicMock(),
        pacer=MagicMock(),
    )
    with (
        patch(
            "app.workers.handlers.gestion_full_inbound.claim_inventory_ids_for_inbound_refresh",
            return_value=["INV1"],
        ) as claim,
        patch(
            "app.workers.handlers.gestion_full_inbound.refresh_last_inbound",
            return_value=MagicMock(),
        ) as refresh,
    ):
        result = handler.run(_ctx())
    assert result.success is True
    assert result.detail["refreshed"] == 1
    assert result.detail["attempted"] == ["INV1"]
    claim.assert_called_once()
    refresh.assert_called_once()


def test_failed_first_batch_still_refreshes_second_batch() -> None:
    """Fernando: chronic failures must not monopolize every drip tick."""
    saturday = datetime(2026, 10, 31, 10, 0, tzinfo=AR).astimezone(UTC)
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    handler = GestionFullInboundHandler(
        now=lambda: saturday,
        session_factory=lambda: session,
        client_factory=lambda pacer: MagicMock(),
        pacer=MagicMock(),
    )
    claims = [["BAD"], ["GOOD"]]

    def _claim(*_a: object, **_k: object) -> list[str]:
        return claims.pop(0)

    with (
        patch(
            "app.workers.handlers.gestion_full_inbound.claim_inventory_ids_for_inbound_refresh",
            side_effect=_claim,
        ),
        patch(
            "app.workers.handlers.gestion_full_inbound.refresh_last_inbound",
            side_effect=[RuntimeError("429"), MagicMock()],
        ) as refresh,
        patch(
            "app.workers.handlers.gestion_full_inbound.record_inbound_attempt",
        ) as record,
    ):
        first = handler.run(_ctx())
        second = handler.run(_ctx())

    assert first.detail["refreshed"] == 0
    assert first.detail["errors"]
    record.assert_called_once()
    assert record.call_args.args[1] == "BAD"
    assert second.detail["refreshed"] == 1
    assert second.detail["attempted"] == ["GOOD"]
    assert refresh.call_count == 2
