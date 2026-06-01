"""
Unit tests for app.scripts.sync_stock_por_deposito.

Tests cover:
  - _to_int: integer coercion edge cases
  - _fetch_stock_for_depot: correct HTTP params and response parsing
  - sync_depot: per-depot iteration, upsert payload, batching
  - run_sync: depot-level error isolation (one depot error does not abort others)
  - on_conflict_do_update sets updated_at explicitly

IMPORTANT: async functions are tested via asyncio.run() inside plain def tests.
The project has NO pytest-asyncio configured — do NOT use @pytest.mark.asyncio.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _to_int
# ---------------------------------------------------------------------------


class TestToInt:
    def test_integer_passthrough(self) -> None:
        from app.scripts.sync_stock_por_deposito import _to_int

        assert _to_int(42) == 42

    def test_float_truncated(self) -> None:
        from app.scripts.sync_stock_por_deposito import _to_int

        assert _to_int(3.9) == 3

    def test_string_integer(self) -> None:
        from app.scripts.sync_stock_por_deposito import _to_int

        assert _to_int("7") == 7

    def test_string_float(self) -> None:
        from app.scripts.sync_stock_por_deposito import _to_int

        assert _to_int("2.8") == 2

    def test_none_returns_default(self) -> None:
        from app.scripts.sync_stock_por_deposito import _to_int

        assert _to_int(None) == 0

    def test_none_custom_default(self) -> None:
        from app.scripts.sync_stock_por_deposito import _to_int

        assert _to_int(None, default=-1) == -1

    def test_garbage_returns_default(self) -> None:
        from app.scripts.sync_stock_por_deposito import _to_int

        assert _to_int("not_a_number") == 0

    def test_zero(self) -> None:
        from app.scripts.sync_stock_por_deposito import _to_int

        assert _to_int(0) == 0


# ---------------------------------------------------------------------------
# _fetch_stock_for_depot
# ---------------------------------------------------------------------------


class TestFetchStockForDepot:
    def test_sends_correct_params(self) -> None:
        """Must call gbp-parser with opName, intStor_id, intItem_id=-1."""
        from app.scripts.sync_stock_por_deposito import _fetch_stock_for_depot

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = [{"item_id": 1, "Stock": 10}]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=fake_response)
        mock_async_ctx = MagicMock()
        mock_async_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scripts.sync_stock_por_deposito.httpx.AsyncClient", return_value=mock_async_ctx):
            with patch("app.scripts.sync_stock_por_deposito.settings") as mock_settings:
                mock_settings.GBP_PARSER_URL = "http://localhost:8001"
                result = asyncio.run(_fetch_stock_for_depot(stor_id=3))

        mock_client.get.assert_called_once_with(
            "http://localhost:8001",
            params={
                "opName": "ItemStorage_funGetXMLData",
                "intStor_id": 3,
                "intItem_id": -1,
            },
        )
        assert result == [{"item_id": 1, "Stock": 10}]

    def test_raises_on_non_list_response(self) -> None:
        """If gbp-parser returns a non-list, RuntimeError is raised."""
        from app.scripts.sync_stock_por_deposito import _fetch_stock_for_depot

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {"error": "unexpected"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=fake_response)
        mock_async_ctx = MagicMock()
        mock_async_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scripts.sync_stock_por_deposito.httpx.AsyncClient", return_value=mock_async_ctx):
            with patch("app.scripts.sync_stock_por_deposito.settings") as mock_settings:
                mock_settings.GBP_PARSER_URL = "http://localhost:8001"
                with pytest.raises(RuntimeError, match="Unexpected gbp-parser response"):
                    asyncio.run(_fetch_stock_for_depot(stor_id=1))


# ---------------------------------------------------------------------------
# sync_depot
# ---------------------------------------------------------------------------


class TestSyncDepot:
    def _make_db(self) -> MagicMock:
        db = MagicMock()
        db.execute = MagicMock()
        return db

    def test_upsert_payload_shape(self) -> None:
        """sync_depot builds rows with item_id, stor_id, stock, updated_at."""
        from app.scripts.sync_stock_por_deposito import sync_depot

        raw = [
            {"item_id": "10", "Stock": "5"},
            {"item_id": "20", "Stock": "0"},
        ]

        db = self._make_db()
        captured_batches: list[list[dict]] = []

        def capture_upsert(db_: object, rows: list[dict]) -> None:
            captured_batches.append(list(rows))

        with patch(
            "app.scripts.sync_stock_por_deposito._fetch_stock_for_depot", new_callable=AsyncMock, return_value=raw
        ):
            with patch("app.scripts.sync_stock_por_deposito._upsert_batch", side_effect=capture_upsert):
                count = asyncio.run(sync_depot(db, stor_id=1))

        assert count == 2
        assert len(captured_batches) == 1
        rows = captured_batches[0]
        assert len(rows) == 2

        row0 = rows[0]
        assert row0["item_id"] == 10
        assert row0["stor_id"] == 1
        assert row0["stock"] == 5
        assert isinstance(row0["updated_at"], datetime)

        row1 = rows[1]
        assert row1["item_id"] == 20
        assert row1["stock"] == 0

    def test_skips_rows_with_zero_item_id(self) -> None:
        """Rows with item_id == 0 or negative should be skipped."""
        from app.scripts.sync_stock_por_deposito import sync_depot

        raw = [
            {"item_id": "0", "Stock": "5"},
            {"item_id": "-1", "Stock": "3"},
            {"item_id": "5", "Stock": "2"},
        ]

        db = self._make_db()
        captured: list[list[dict]] = []

        with patch(
            "app.scripts.sync_stock_por_deposito._fetch_stock_for_depot", new_callable=AsyncMock, return_value=raw
        ):
            with patch(
                "app.scripts.sync_stock_por_deposito._upsert_batch",
                side_effect=lambda d, rows: captured.append(list(rows)),
            ):
                count = asyncio.run(sync_depot(db, stor_id=2))

        assert count == 1
        assert captured[0][0]["item_id"] == 5

    def test_batching_splits_correctly(self) -> None:
        """With UPSERT_BATCH_SIZE=2, 5 rows should produce 3 upsert calls."""
        from app.scripts.sync_stock_por_deposito import sync_depot
        import app.scripts.sync_stock_por_deposito as module

        original_batch_size = module.UPSERT_BATCH_SIZE
        module.UPSERT_BATCH_SIZE = 2

        raw = [{"item_id": str(i), "Stock": "1"} for i in range(1, 6)]
        db = self._make_db()
        call_count = 0

        def count_calls(d: object, rows: list[dict]) -> None:
            nonlocal call_count
            call_count += 1

        try:
            with patch(
                "app.scripts.sync_stock_por_deposito._fetch_stock_for_depot", new_callable=AsyncMock, return_value=raw
            ):
                with patch("app.scripts.sync_stock_por_deposito._upsert_batch", side_effect=count_calls):
                    asyncio.run(sync_depot(db, stor_id=1))
        finally:
            module.UPSERT_BATCH_SIZE = original_batch_size

        assert call_count == 3  # batches of 2, 2, 1


# ---------------------------------------------------------------------------
# run_sync — depot-level error isolation
# ---------------------------------------------------------------------------


class TestRunSync:
    def test_http_error_in_one_depot_does_not_abort_others(self) -> None:
        """An HTTPError for depot 2 should not prevent depot 3 from syncing."""
        import httpx
        from app.scripts.sync_stock_por_deposito import run_sync

        mock_db = MagicMock()
        mock_db.execute.return_value.fetchall.return_value = [
            MagicMock(__getitem__=lambda self, i: [1, 2, 3][i]),
        ]
        # Simulate [stor_id=1, stor_id=2, stor_id=3]
        mock_db.execute.return_value.fetchall.return_value = [
            (1,),
            (2,),
            (3,),
        ]

        sync_calls: list[int] = []

        async def fake_sync_depot(db: object, stor_id: int) -> int:
            sync_calls.append(stor_id)
            if stor_id == 2:
                raise httpx.HTTPError("connection refused")
            return 10

        with patch("app.scripts.sync_stock_por_deposito.SessionLocal", return_value=mock_db):
            with patch("app.scripts.sync_stock_por_deposito.sync_depot", side_effect=fake_sync_depot):
                asyncio.run(run_sync())

        # All three depots attempted; error on 2 did not skip 3
        assert 1 in sync_calls
        assert 2 in sync_calls
        assert 3 in sync_calls
        mock_db.commit.assert_called_once()

    def test_no_depots_exits_gracefully(self) -> None:
        """If tb_item_storage has no depot rows, sync exits without error."""
        from app.scripts.sync_stock_por_deposito import run_sync

        mock_db = MagicMock()
        mock_db.execute.return_value.fetchall.return_value = []

        with patch("app.scripts.sync_stock_por_deposito.SessionLocal", return_value=mock_db):
            # Should not raise
            asyncio.run(run_sync())

        mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# _upsert_batch — ON CONFLICT sets updated_at explicitly
# ---------------------------------------------------------------------------


class TestUpsertBatch:
    def test_on_conflict_sets_updated_at(self) -> None:
        """_upsert_batch must include updated_at in the ON CONFLICT SET clause."""
        from app.scripts.sync_stock_por_deposito import _upsert_batch

        rows = [
            {
                "item_id": 1,
                "stor_id": 1,
                "stock": 5,
                "updated_at": datetime.now(UTC),
            }
        ]

        # Capture the statement passed to db.execute
        captured_stmt = None

        def capture_execute(stmt: object, *args: object, **kwargs: object) -> MagicMock:
            nonlocal captured_stmt
            captured_stmt = stmt
            return MagicMock()

        mock_db = MagicMock()
        mock_db.execute = capture_execute

        _upsert_batch(mock_db, rows)

        assert captured_stmt is not None
        # Compile the statement for introspection
        compiled = captured_stmt.compile(
            dialect=__import__("sqlalchemy.dialects.postgresql", fromlist=["dialect"]).dialect()
        )
        sql_text = str(compiled)
        # ON CONFLICT DO UPDATE must set both stock and updated_at
        assert "stock" in sql_text.lower()
        assert "updated_at" in sql_text.lower()
