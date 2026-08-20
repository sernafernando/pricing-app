"""Unit tests for the `sync_tn_category_embeddings` cron entry point (PR-1,
tn-publisher-module — design Decision 8).

Wiring only: `sync_category_embeddings()` itself is not touched here, only
mocked, mirroring `test_sync_item_transaction_serials.py`'s
`pytest.raises(SystemExit)` convention for asserting a cron script's exit
code.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.scripts import sync_tn_category_embeddings as module


class TestSyncTnCategoryEmbeddingsMain:
    def test_skipped_sync_exits_non_zero(self) -> None:
        fake_result = {"synced": 0, "skipped": True, "reason": "fetch_categories_failed"}
        with (
            patch.object(module, "SessionLocal", return_value=MagicMock()),
            patch.object(module, "sync_category_embeddings", return_value=fake_result) as mocked,
            pytest.raises(SystemExit) as exc,
        ):
            module.main()

        assert exc.value.code == 1
        mocked.assert_called_once()

    def test_successful_sync_exits_zero(self) -> None:
        fake_result = {"synced": 5, "skipped": False, "reason": None}
        with (
            patch.object(module, "SessionLocal", return_value=MagicMock()),
            patch.object(module, "sync_category_embeddings", return_value=fake_result),
        ):
            # Must NOT raise SystemExit on success — a cron wrapper treats
            # any exit as failure if this ever raises.
            module.main()
