"""Unit tests for `tn_category_embedding_service` (sub-slice 3b — embedder-
assisted TN category suggestion).

No `@pytest.mark.asyncio` — matches the house convention (`test_ml_bot_
embedding_client.py`, `test_tienda_nube_product_client.py`): async client and
embedder calls are driven via `asyncio.run()` or mocked directly, since
`sync_category_embeddings`/`suggest_category` are plain sync functions that
internally bridge coroutines the same way `tn_publish_service` does.

The real pgvector cosine-similarity query is NEVER executed here (test DB is
sqlite, no pgvector) — `_similarity_query` is monkeypatched/mocked in every
suggestion test, mirroring `ml_questions/context_builder.py`'s own test
convention.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from app.models.tn_category_embedding import TnCategoryEmbedding
from app.services.tn_category_embedding_service import (
    build_category_paths,
    suggest_category,
    sync_category_embeddings,
)


class TestBuildCategoryPaths:
    def test_top_level_category_has_no_prefix(self):
        categories = [{"id": 1, "name": {"es": "Electrónica"}, "parent": None}]
        paths = build_category_paths(categories)
        assert paths == {1: "Electrónica"}

    def test_nested_category_joins_ancestors_with_arrow(self):
        categories = [
            {"id": 1, "name": {"es": "Electrónica"}, "parent": None},
            {"id": 2, "name": {"es": "Celulares"}, "parent": 1},
        ]
        paths = build_category_paths(categories)
        assert paths == {1: "Electrónica", 2: "Electrónica > Celulares"}

    def test_deeply_nested_category_joins_all_ancestors(self):
        categories = [
            {"id": 1, "name": {"es": "Electrónica"}, "parent": None},
            {"id": 2, "name": {"es": "Celulares"}, "parent": 1},
            {"id": 3, "name": {"es": "Accesorios"}, "parent": 2},
        ]
        paths = build_category_paths(categories)
        assert paths[3] == "Electrónica > Celulares > Accesorios"

    def test_plain_string_name_is_used_as_is(self):
        categories = [{"id": 1, "name": "Electrónica", "parent": None}]
        paths = build_category_paths(categories)
        assert paths == {1: "Electrónica"}

    def test_missing_or_unresolvable_parent_falls_back_to_own_name(self):
        # parent references an id not present in the payload — degrade
        # gracefully rather than crash.
        categories = [{"id": 2, "name": {"es": "Celulares"}, "parent": 999}]
        paths = build_category_paths(categories)
        assert paths == {2: "Celulares"}

    def test_empty_category_list_returns_empty_dict(self):
        assert build_category_paths([]) == {}


class TestSyncCategoryEmbeddings:
    def test_client_fetch_failure_skips_sync_no_crash(self, db):
        fake_client = MagicMock()
        fake_client.fetch_categories = AsyncMock(return_value=None)
        result = sync_category_embeddings(db, client=fake_client)
        assert result == {"synced": 0, "skipped": True, "reason": "fetch_categories_failed"}
        assert db.query(TnCategoryEmbedding).count() == 0

    def test_embedder_failure_skips_sync_no_crash(self, db):
        fake_client = MagicMock()
        fake_client.fetch_categories = AsyncMock(
            return_value=[{"id": 1, "name": {"es": "Electrónica"}, "parent": None}]
        )
        with patch("app.services.tn_category_embedding_service.embed_passages", new=AsyncMock(return_value=None)):
            result = sync_category_embeddings(db, client=fake_client)
        assert result == {"synced": 0, "skipped": True, "reason": "embed_passages_failed"}
        assert db.query(TnCategoryEmbedding).count() == 0

    def test_empty_category_tree_is_a_no_op(self, db):
        fake_client = MagicMock()
        fake_client.fetch_categories = AsyncMock(return_value=[])
        result = sync_category_embeddings(db, client=fake_client)
        assert result == {"synced": 0, "skipped": False, "reason": None}

    def test_successful_sync_inserts_one_row_per_category(self, db):
        categories = [
            {"id": 1, "name": {"es": "Electrónica"}, "parent": None},
            {"id": 2, "name": {"es": "Celulares"}, "parent": 1},
        ]
        fake_client = MagicMock()
        fake_client.fetch_categories = AsyncMock(return_value=categories)
        fake_embeddings = [[0.1] * 384, [0.2] * 384]
        with patch(
            "app.services.tn_category_embedding_service.embed_passages",
            new=AsyncMock(return_value=fake_embeddings),
        ):
            result = sync_category_embeddings(db, client=fake_client)
        assert result == {"synced": 2, "skipped": False, "reason": None}
        rows = db.query(TnCategoryEmbedding).order_by(TnCategoryEmbedding.tn_category_id).all()
        assert [r.tn_category_id for r in rows] == [1, 2]
        assert rows[1].category_path_text == "Electrónica > Celulares"

    def test_rerunning_sync_upserts_instead_of_duplicating(self, db):
        categories = [{"id": 1, "name": {"es": "Electrónica"}, "parent": None}]
        fake_client = MagicMock()
        fake_client.fetch_categories = AsyncMock(return_value=categories)
        with patch(
            "app.services.tn_category_embedding_service.embed_passages",
            new=AsyncMock(return_value=[[0.1] * 384]),
        ):
            sync_category_embeddings(db, client=fake_client)
            sync_category_embeddings(db, client=fake_client)
        assert db.query(TnCategoryEmbedding).count() == 1


class TestSuggestCategory:
    def test_embedder_returning_none_yields_empty_suggestion(self, db):
        with patch("app.services.tn_category_embedding_service.embed_query", new=AsyncMock(return_value=None)):
            result = suggest_category(db, "Celulares y Smartphones")
        assert result == {"suggestions": [], "top": None}

    def test_similarity_query_failure_yields_empty_suggestion(self, db):
        with (
            patch("app.services.tn_category_embedding_service.embed_query", new=AsyncMock(return_value=[0.1] * 384)),
            patch(
                "app.services.tn_category_embedding_service._similarity_query",
                side_effect=Exception("no pgvector on sqlite"),
            ),
        ):
            result = suggest_category(db, "Celulares y Smartphones")
        assert result == {"suggestions": [], "top": None}

    def test_successful_suggestion_ranks_by_ascending_distance(self, db):
        row_a = TnCategoryEmbedding(tn_category_id=1, category_path_text="Electrónica", embedding=[0.1] * 384)
        row_b = TnCategoryEmbedding(
            tn_category_id=2, category_path_text="Electrónica > Celulares", embedding=[0.2] * 384
        )
        with (
            patch("app.services.tn_category_embedding_service.embed_query", new=AsyncMock(return_value=[0.15] * 384)),
            patch(
                "app.services.tn_category_embedding_service._similarity_query",
                return_value=[(row_b, 0.01), (row_a, 0.05)],
            ),
        ):
            result = suggest_category(db, "Celulares y Smartphones", top_n=2)
        assert result["top"]["tn_category_id"] == 2
        assert result["top"]["category_path_text"] == "Electrónica > Celulares"
        assert len(result["suggestions"]) == 2
        assert result["suggestions"][0]["tn_category_id"] == 2
        assert result["suggestions"][1]["tn_category_id"] == 1

    def test_no_rows_yields_empty_suggestion(self, db):
        with (
            patch("app.services.tn_category_embedding_service.embed_query", new=AsyncMock(return_value=[0.1] * 384)),
            patch("app.services.tn_category_embedding_service._similarity_query", return_value=[]),
        ):
            result = suggest_category(db, "algo sin match")
        assert result == {"suggestions": [], "top": None}
