"""Round-trip tests for the ML publications store models (SQLite create_all).

The Postgres-only types (JSONB, ARRAY, UUID) are remapped by the `engine`
fixture in `tests/conftest.py`; the DDL itself is covered by the Postgres
migration test.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.models.ml_publications import (
    MlChangeLog,
    MlItem,
    MlItemEvent,
    MlItemVariation,
    MlPubIntakeCursor,
    MlPubJobRun,
    MlPubRefreshQueue,
    MlPubScanState,
    MlPubSetting,
)

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
FAMILY_ID = 7695306917964170


def test_item_round_trips_typed_columns(db) -> None:
    db.add(
        MlItem(
            item_id="MLA1",
            site_id="MLA",
            seller_id=123,
            title="Router",
            brand="TP-Link",
            family_id=FAMILY_ID,
            official_store_id=2645,
            status="active",
            sub_status=["x"],
            tags=["a", "b"],
            price=Decimal("1234.50"),
            health=Decimal("0.8123"),
            available_quantity=3,
            catalog_listing=True,
            raw={"id": "MLA1"},
            raw_hash=b"\x01\x02",
            never_existed=False,
        )
    )
    db.flush()
    db.expire_all()
    item = db.get(MlItem, "MLA1")
    assert item.family_id == FAMILY_ID
    assert item.price == Decimal("1234.50")
    assert item.raw == {"id": "MLA1"}
    assert item.raw_hash == b"\x01\x02"
    assert item.first_seen_at is not None
    assert item.never_existed is False


def test_variation_composite_key(db) -> None:
    db.add(MlItemVariation(item_id="MLA1", variation_id=99, raw={"k": 1}, raw_hash=b"h", fetched_at=NOW))
    db.flush()
    assert db.get(MlItemVariation, ("MLA1", 99)).raw == {"k": 1}


def test_change_log_and_event_link(db) -> None:
    log = MlChangeLog(
        resource_type="item",
        entity_id="MLA1",
        item_id="MLA1",
        observed_at=NOW,
        changed_paths=["price"],
        changes=[{"p": "price", "op": "set", "old": 1, "new": 2}],
    )
    db.add(log)
    db.flush()
    assert log.id is not None and log.kind == "change" and log.context == {}
    event = MlItemEvent(
        event_type="price_changed",
        item_id="MLA1",
        observed_at=NOW,
        change_log_id=log.id,
        dedupe_key=b"\xaa",
    )
    db.add(event)
    db.flush()
    assert event.id is not None and event.payload == {}


def test_settings_queue_cursor_scan_and_job_runs(db) -> None:
    db.add(MlPubSetting(key="refresh.enabled", value=True))
    db.add(
        MlPubRefreshQueue(kind="item", entity_id="MLA1", lane=1, resources=["bundle"], claim_token=str(uuid.uuid4()))
    )
    db.add(MlPubIntakeCursor(topic="items", rows_read=5))
    db.add(MlPubScanState(status="active", pages=2))
    db.add(MlPubJobRun(job="scan", started_at=NOW))
    db.flush()
    queue = db.get(MlPubRefreshQueue, ("item", "MLA1"))
    assert queue.attempts == 0 and queue.version == 1 and queue.resources == ["bundle"]
    assert db.get(MlPubSetting, "refresh.enabled").value is True
    assert db.get(MlPubScanState, "active").unsupported is False
    assert db.get(MlPubIntakeCursor, "items").rows_read == 5
    assert db.query(MlPubJobRun).one().counts == {}
