"""Unit tests for Gestión Full inbound Target picker (no ML / no DB)."""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.gestion_full.inbound import pick_last_inbound


def test_pick_last_inbound_takes_newest_reception() -> None:
    results = [
        {
            "id": 1,
            "type": "INBOUND_RECEPTION",
            "date_created": "2020-06-10T10:00:00Z",
            "detail": {"available_quantity": 50},
            "external_references": [{"type": "inbound_id", "value": "old"}],
        },
        {
            "id": 306705012,
            "type": "INBOUND_RECEPTION",
            "date_created": "2020-06-18T17:55:42Z",
            "detail": {"available_quantity": 100},
            "external_references": [{"type": "inbound_id", "value": "0001"}],
        },
        {
            "id": 9,
            "type": "SALE_CONFIRMATION",
            "date_created": "2020-06-19T10:00:00Z",
            "detail": {"available_quantity": -3},
        },
    ]
    picked = pick_last_inbound(results)
    assert picked is not None
    assert picked["cantidad"] == 100
    assert picked["operation_id"] == 306705012
    assert picked["inbound_id"] == "0001"
    assert picked["occurred_at"] == datetime(2020, 6, 18, 17, 55, 42, tzinfo=UTC)


def test_pick_last_inbound_empty() -> None:
    assert pick_last_inbound([]) is None
    assert pick_last_inbound([{"type": "SALE_CONFIRMATION", "detail": {"available_quantity": 1}}]) is None
