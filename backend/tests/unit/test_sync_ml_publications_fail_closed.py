"""
Unit tests for the fail-closed total-failure signal in the ML publications
sync scripts (bug: 6772/6772 chunks failing used to print
"✓ ... completada: 0 nuevos, 0 actualizados, 6772 errores" as if it had
succeeded). `traer_detalles_batch` (incremental script) must now raise
`RuntimeError` when every chunk failed and nothing was saved/updated, and
must NOT raise on a partial failure (some successes alongside some errors).
"""

from __future__ import annotations

import asyncio

import pytest

from app.scripts import sync_ml_publications_incremental as sync_mod


class TestFailClosedTotalFailure:
    def test_raises_when_every_chunk_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_call_meli(endpoint: str, retry: bool = True):
            raise RuntimeError("No se pudo obtener access_token de mlwebhook DB")

        monkeypatch.setattr(sync_mod, "call_meli", fake_call_meli)

        ids = ["MLA1", "MLA2"]
        dummy_db = object()

        with pytest.raises(RuntimeError):
            asyncio.run(sync_mod.traer_detalles_batch(ids, dummy_db))

    def test_does_not_raise_on_partial_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """One chunk succeeds and is persisted, the other fails — this is a
        partial failure and must stay a warning, not an exception."""

        call_count = {"n": 0}

        async def fake_call_meli(endpoint: str, retry: bool = True):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [{"code": 200, "body": {"id": "MLA1", "sale_terms": [], "attributes": []}}]
            raise RuntimeError("transient ML error")

        monkeypatch.setattr(sync_mod, "call_meli", fake_call_meli)

        class _FakeQuery:
            def filter(self, *args, **kwargs):
                return self

            def first(self):
                return None

        class _FakeDB:
            def query(self, *args, **kwargs):
                return _FakeQuery()

            def add(self, *args, **kwargs):
                pass

            def commit(self):
                pass

            def rollback(self):
                pass

        # 21 ids -> chunk_size 20 forces two chunks: first succeeds, second errors.
        ids = [f"MLA{i}" for i in range(21)]

        total_saved, total_updated = asyncio.run(sync_mod.traer_detalles_batch(ids, _FakeDB()))

        assert total_saved == 1
        assert total_updated == 0
