"""
RED/GREEN — the item syncs must persist the whole `scriptItem` row, not just
the 12 columns they used to pick by hand.

Once the ERP script returns every tbItem column, `tb_item` keeps:
  * the full row in `raw` (nothing the ERP sends is dropped),
  * typed copies of the dimensions and website images.

It also covers the update rule: an item whose only change is a field outside
the old hand-picked list (code, desc, cat, subcat, brand) must be updated.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.tb_item import TBItem
from app.services.tb_item_row import upsert_tb_item
from app.scripts.sync_erp_master_tables_full import sync_items_full
from app.scripts.sync_erp_master_tables_incremental import sync_items_incremental


def _erp_row(**overrides: object) -> dict:
    """A scriptItem row as returned by GBP (values come as strings)."""
    row = {
        "comp_id": "1",
        "item_id": "4198",
        "item_code": "7790001",
        "item_desc": "Heladera",
        "cat_id": "10",
        "subcat_id": "20",
        "brand_id": "30",
        "item_liquidation": "N",
        "item_expser": "1",
        "item_cd": "2024-01-02T10:00:00",
        "item_LastUpdate": "2026-10-20T10:00:00",
        "item_lastUpdate_byProcess": "2026-10-20T10:00:00",
        "item_weight": "12000.000000000",
        "item_volume": "0.000000000",
        "item_wide": "55.000000000",
        "item_large": "45.000000000",
        "item_higth": "25.000000000",
        "item_WebSite_url4Image1": "https://img.example/1.jpg",
        "item_WebSite_url4Image10": "https://img.example/10.jpg",
        "item_ML_title": "Heladera no frost",
    }
    row.update(overrides)
    return row


def _patched_client(module: str, payload: list[dict]):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=payload)
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return patch(f"{module}.httpx.AsyncClient", return_value=client)


FULL = "app.scripts.sync_erp_master_tables_full"
INCREMENTAL = "app.scripts.sync_erp_master_tables_incremental"


class TestSyncItemsFullStoresWholeRow:
    def test_new_item_keeps_raw_row_dimensions_and_images(self, db) -> None:
        row = _erp_row()
        with _patched_client(FULL, [row]):
            result = asyncio.run(sync_items_full(db))

        item = db.query(TBItem).filter(TBItem.item_id == 4198).one()
        assert result == {"nuevos": 1, "actualizados": 0}
        assert item.raw == row
        assert item.item_weight == Decimal("12000")
        assert item.item_wide == Decimal("55")
        assert item.item_large == Decimal("45")
        assert item.item_higth == Decimal("25")
        assert item.item_WebSite_url4Image1 == "https://img.example/1.jpg"
        assert item.item_WebSite_url4Image2 is None
        assert item.item_WebSite_url4Image10 == "https://img.example/10.jpg"
        assert item.item_expser is True

    def test_existing_item_is_updated_when_only_the_weight_changes(self, db) -> None:
        with _patched_client(FULL, [_erp_row()]):
            asyncio.run(sync_items_full(db))

        changed = _erp_row(item_weight="13000.000000000")
        with _patched_client(FULL, [changed]):
            result = asyncio.run(sync_items_full(db))

        item = db.query(TBItem).filter(TBItem.item_id == 4198).one()
        assert result == {"nuevos": 0, "actualizados": 1}
        assert item.item_weight == Decimal("13000")
        assert item.raw == changed

    def test_unchanged_row_is_not_counted_as_updated(self, db) -> None:
        with _patched_client(FULL, [_erp_row()]):
            asyncio.run(sync_items_full(db))
        with _patched_client(FULL, [_erp_row()]):
            result = asyncio.run(sync_items_full(db))

        assert result == {"nuevos": 0, "actualizados": 0}

    def test_code_change_still_updates_the_item(self, db) -> None:
        with _patched_client(FULL, [_erp_row()]):
            asyncio.run(sync_items_full(db))
        with _patched_client(FULL, [_erp_row(item_code="7790002")]):
            result = asyncio.run(sync_items_full(db))

        item = db.query(TBItem).filter(TBItem.item_id == 4198).one()
        assert result == {"nuevos": 0, "actualizados": 1}
        assert item.item_code == "7790002"


class TestSyncItemsIncrementalStoresWholeRow:
    def test_new_and_changed_items_keep_the_whole_row(self, db) -> None:
        with _patched_client(INCREMENTAL, [_erp_row()]):
            first = asyncio.run(sync_items_incremental(db))

        changed = _erp_row(item_WebSite_url4Image1="https://img.example/new.jpg")
        with _patched_client(INCREMENTAL, [changed]):
            second = asyncio.run(sync_items_incremental(db))

        item = db.query(TBItem).filter(TBItem.item_id == 4198).one()
        assert (first["nuevos"], first["actualizados"]) == (1, 0)
        assert (second["nuevos"], second["actualizados"]) == (0, 1)
        assert item.item_WebSite_url4Image1 == "https://img.example/new.jpg"
        assert item.raw == changed
        assert item.item_expser is True


class TestUpsertTbItemKeepsWhatTheRowDoesNotSend:
    def test_partial_row_does_not_wipe_stored_columns(self, db) -> None:
        upsert_tb_item(db, _erp_row(item_expser="0"))
        db.commit()

        partial = {key: _erp_row()[key] for key in ("comp_id", "item_id", "item_code", "item_desc")}
        partial["item_desc"] = "Heladera nueva"
        assert upsert_tb_item(db, partial) == "actualizado"
        db.commit()

        item = db.query(TBItem).filter(TBItem.item_id == 4198).one()
        assert item.item_desc == "Heladera nueva"
        assert item.item_expser is False
        assert item.item_weight == Decimal("12000")
        assert item.item_WebSite_url4Image1 == "https://img.example/1.jpg"
        assert item.raw["item_ML_title"] == "Heladera no frost"
        assert item.raw["item_desc"] == "Heladera nueva"

    def test_utc_suffixed_dates_do_not_count_as_a_change(self, db) -> None:
        row = _erp_row(item_LastUpdate="2026-10-20T10:00:00Z", item_cd="2024-01-02T10:00:00Z")
        upsert_tb_item(db, row)
        db.commit()

        assert upsert_tb_item(db, dict(row)) == "sin_cambios"

    def test_only_insert_leaves_an_existing_item_untouched(self, db) -> None:
        upsert_tb_item(db, _erp_row())
        db.commit()

        assert upsert_tb_item(db, _erp_row(item_desc="Otra"), only_insert=True) == "sin_cambios"
        db.commit()

        assert db.query(TBItem).filter(TBItem.item_id == 4198).one().item_desc == "Heladera"
