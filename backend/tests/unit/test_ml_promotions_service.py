"""
Unit tests for ml_promotions_service — cross-DB reads (ml_promotions,
ml_item_promotions) from the mlwebhook database.

TDD: all tests written BEFORE the implementation.

Spec coverage:
  REQ-1 — fetch_promotions() returns list of dicts from ml_promotions
  REQ-2 — fetch_item_promotions(mla_id, active_only=False) returns list of
          dicts from ml_item_promotions, status normalized to
          candidate|started|finished; active_only=True adds a
          status IN ('candidate', 'started') filter for the display path
  REQ-3 — fetch_promotion_items(promotion_id, promotion_type) returns items
          of a specific promotion from ml_item_promotions
  REQ-4 — empty result sets return [] (not None), no exception raised
  REQ-5 — DB unreachable (ML_WEBHOOK_DB_URL unset) raises RuntimeError,
          the caller (router) is responsible for mapping it to HTTP 503

Design note: get_mlwebhook_engine is ALWAYS mocked in these tests because
the mlwebhook DB is NOT reachable from the test environment.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


def _make_promotion_row(
    promotion_id: str = "SELLER_CAMPAIGN",
    promotion_type: str = "SELLER_CAMPAIGN",
    sub_type: str = None,
    status: str = "started",
    name: str = "Campaña Vendedor",
    start_date: datetime = None,
    finish_date: datetime = None,
    deadline_date: datetime = None,
    payload: dict = None,
    updated_at: datetime = None,
):
    return (
        promotion_id,
        promotion_type,
        sub_type,
        status,
        name,
        start_date,
        finish_date,
        deadline_date,
        payload or {},
        updated_at,
    )


def _make_item_promotion_row(
    mla: str = "MLA123456789",
    promotion_id: str = "DEAL-1",
    promotion_type: str = "DEAL",
    sub_type: str = None,
    status: str = "candidate",
    original_price: float = 1000.0,
    price: float = 900.0,
    min_discounted_price: float = 850.0,
    max_discounted_price: float = 950.0,
    suggested_discounted_price: float = 900.0,
    payload: dict = None,
    updated_at: datetime = None,
):
    return (
        mla,
        promotion_id,
        promotion_type,
        sub_type,
        status,
        original_price,
        price,
        min_discounted_price,
        max_discounted_price,
        suggested_discounted_price,
        payload or {},
        updated_at,
    )


class TestFetchPromotions:
    """REQ-1, REQ-4: fetch_promotions() reads ml_promotions."""

    def test_returns_list_of_dicts(self) -> None:
        from app.services.ml_promotions_service import fetch_promotions

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            _make_promotion_row(promotion_id="SELLER_CAMPAIGN", status="started"),
        ]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_promotions()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["promotion_id"] == "SELLER_CAMPAIGN"
        assert result[0]["status"] == "started"

    def test_empty_result_returns_empty_list(self) -> None:
        from app.services.ml_promotions_service import fetch_promotions

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_promotions()

        assert result == []

    def test_db_unavailable_raises_runtime_error(self) -> None:
        """REQ-5: caller (router) maps RuntimeError to HTTP 503."""
        from app.services.ml_promotions_service import fetch_promotions

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine") as mock_engine_fn:
            mock_engine_fn.side_effect = RuntimeError("ML_WEBHOOK_DB_URL no configurada")

            with pytest.raises(RuntimeError):
                fetch_promotions()


class TestFetchItemPromotions:
    """REQ-2, REQ-4: fetch_item_promotions(mla_id) reads ml_item_promotions."""

    def test_returns_list_with_status_mapped(self) -> None:
        from app.services.ml_promotions_service import fetch_item_promotions

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            _make_item_promotion_row(mla="MLA123456789", status="candidate"),
        ]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_item_promotions("MLA123456789")

        assert len(result) == 1
        assert result[0]["mla"] == "MLA123456789"
        assert result[0]["status"] == "candidate"

    def test_status_normalized_to_known_values(self) -> None:
        from app.services.ml_promotions_service import fetch_item_promotions

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            _make_item_promotion_row(status="started"),
            _make_item_promotion_row(status="finished"),
        ]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_item_promotions("MLA123456789")

        statuses = {row["status"] for row in result}
        assert statuses <= {"candidate", "started", "finished"}

    def test_empty_result_returns_empty_list(self) -> None:
        from app.services.ml_promotions_service import fetch_item_promotions

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_item_promotions("MLA000000000")

        assert result == []

    def test_db_unavailable_raises_runtime_error(self) -> None:
        from app.services.ml_promotions_service import fetch_item_promotions

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine") as mock_engine_fn:
            mock_engine_fn.side_effect = RuntimeError("ML_WEBHOOK_DB_URL no configurada")

            with pytest.raises(RuntimeError):
                fetch_item_promotions("MLA123456789")

    def test_active_only_true_adds_status_filter(self) -> None:
        """active_only=True must filter to candidate|started in the SQL.

        ml_item_promotions is backfilled and upsert-only (no stale cleanup),
        so a finished promo can linger with its last status until a webhook
        marks it 'finished'. The display endpoint relies on this filter to
        avoid showing terminated promotions.
        """
        from app.services.ml_promotions_service import fetch_item_promotions

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            fetch_item_promotions("MLA123456789", active_only=True)

        executed_query = str(mock_conn.execute.call_args[0][0])
        assert "AND status IN ('candidate', 'started')" in executed_query

    def test_active_only_false_omits_status_filter(self) -> None:
        """active_only=False (default) must NOT filter by status.

        Regression guard: the reconciliation path needs the raw read
        (including finished promos) to detect stale rows.
        """
        from app.services.ml_promotions_service import fetch_item_promotions

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            fetch_item_promotions("MLA123456789")

        executed_query = str(mock_conn.execute.call_args[0][0])
        assert "status IN" not in executed_query


class TestFetchPromotionItems:
    """REQ-3, REQ-4: fetch_promotion_items(promotion_id, promotion_type) reads
    ml_item_promotions filtered by a specific promotion."""

    def test_returns_items_of_promotion(self) -> None:
        from app.services.ml_promotions_service import fetch_promotion_items

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            _make_item_promotion_row(mla="MLA111", promotion_id="DEAL-1", promotion_type="DEAL"),
            _make_item_promotion_row(mla="MLA222", promotion_id="DEAL-1", promotion_type="DEAL"),
        ]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_promotion_items("DEAL-1", "DEAL")

        assert len(result) == 2
        assert {row["mla"] for row in result} == {"MLA111", "MLA222"}

    def test_empty_result_returns_empty_list(self) -> None:
        from app.services.ml_promotions_service import fetch_promotion_items

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_promotion_items("DEAL-1", "DEAL")

        assert result == []

    def test_db_unavailable_raises_runtime_error(self) -> None:
        from app.services.ml_promotions_service import fetch_promotion_items

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine") as mock_engine_fn:
            mock_engine_fn.side_effect = RuntimeError("ML_WEBHOOK_DB_URL no configurada")

            with pytest.raises(RuntimeError):
                fetch_promotion_items("DEAL-1", "DEAL")
