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
    catalog_name: str = None,
    catalog_start_date: datetime = None,
    catalog_finish_date: datetime = None,
):
    # Trailing catalog_name/catalog_start_date/catalog_finish_date mirror the
    # ml_promotions LEFT JOIN columns (row[12]/row[13]/row[14]) that
    # fetch_item_promotions selects; fetch_promotion_items ignores them.
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
        catalog_name,
        catalog_start_date,
        catalog_finish_date,
    )


class TestValidateItemStatus:
    """REQ-1: `pending` is a known, non-warning item status."""

    def test_pending_is_known_status_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        from app.services.ml_promotions_service import _KNOWN_ITEM_STATUSES, _validate_item_status

        assert "pending" in _KNOWN_ITEM_STATUSES

        with caplog.at_level("WARNING"):
            result = _validate_item_status("pending")

        assert result == "pending"
        assert not any("Unexpected" in record.message for record in caplog.records)


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
        assert "AND ip.status IN ('candidate', 'started', 'pending')" in executed_query

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

    def test_name_prefers_catalog_over_empty_payload(self) -> None:
        """The authoritative promo name is ml_promotions.name (catalog),
        joined in. SELLER_CAMPAIGN/DEAL have payload.name == "" — only the
        catalog carries the real name (e.g. "PREMIUM JULIO"), so the catalog
        must win instead of falling back to the cryptic promotion_type."""
        from app.services.ml_promotions_service import fetch_item_promotions

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            _make_item_promotion_row(
                promotion_type="SELLER_CAMPAIGN",
                payload={"id": "SC-1", "name": "", "type": "SELLER_CAMPAIGN"},
                catalog_name="PREMIUM JULIO",
            ),
        ]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_item_promotions("MLA123456789")

        assert result[0]["name"] == "PREMIUM JULIO"

        executed_query = str(mock_conn.execute.call_args[0][0])
        assert "ml_promotions" in executed_query
        assert "LEFT JOIN" in executed_query

    def test_name_falls_back_to_payload_when_no_catalog(self) -> None:
        """When the catalog has no name (SMART fills payload.name instead),
        payload.name is used."""
        from app.services.ml_promotions_service import fetch_item_promotions

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            _make_item_promotion_row(
                promotion_type="SMART",
                payload={"id": "SM-1", "name": "SMART JULIO"},
                catalog_name=None,
            ),
        ]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_item_promotions("MLA123456789")

        assert result[0]["name"] == "SMART JULIO"

    def test_name_none_when_neither_catalog_nor_payload_name(self) -> None:
        """PRICE_DISCOUNT has no catalog name and payload.name == "" -> name
        stays None so the FE can fall back to promotion_type. Empty-string
        catalog name is treated as absent too."""
        from app.services.ml_promotions_service import fetch_item_promotions

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            _make_item_promotion_row(payload={"id": "PRICE_DISCOUNT", "name": ""}, catalog_name=""),
            _make_item_promotion_row(payload={"id": "DEAL-1"}, catalog_name=None),
        ]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_item_promotions("MLA123456789")

        assert result[0]["name"] is None
        assert result[1]["name"] is None

    def test_active_only_true_status_filter_includes_pending(self) -> None:
        """REQ-2: display query must also return `pending` rows."""
        from app.services.ml_promotions_service import fetch_item_promotions

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            _make_item_promotion_row(status="pending"),
        ]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_item_promotions("MLA123456789", active_only=True)

        executed_query = str(mock_conn.execute.call_args[0][0])
        assert "'pending'" in executed_query
        assert result[0]["status"] == "pending"

    def test_catalog_start_finish_date_win_over_empty_payload_serialized_iso(self) -> None:
        """ADD-2: catalog start_date/finish_date (timestamptz -> datetime)
        win over an empty payload and must be serialized to ISO strings."""
        from app.services.ml_promotions_service import fetch_item_promotions

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            _make_item_promotion_row(
                promotion_type="SMART",
                payload={"id": "SM-1"},
                catalog_start_date=datetime(2026, 7, 1, 0, 0, 0),
                catalog_finish_date=datetime(2026, 7, 31, 23, 59, 59),
            ),
        ]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_item_promotions("MLA123456789")

        assert result[0]["start_date"] == "2026-07-01T00:00:00"
        assert result[0]["finish_date"] == "2026-07-31T23:59:59"

    def test_catalog_and_payload_dates_both_empty_is_none(self) -> None:
        from app.services.ml_promotions_service import fetch_item_promotions

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            _make_item_promotion_row(promotion_type="LIGHTNING", payload={"id": "L-1"}),
        ]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_item_promotions("MLA123456789")

        assert result[0]["start_date"] is None
        assert result[0]["finish_date"] is None

    def test_includes_start_and_finish_date_from_payload(self) -> None:
        """start_date/finish_date come from payload (same defensive pattern
        as name): present when the payload carries them, None otherwise."""
        from app.services.ml_promotions_service import fetch_item_promotions

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            _make_item_promotion_row(
                payload={
                    "id": "DEAL-1",
                    "start_date": "2026-07-01T00:00:00",
                    "finish_date": "2026-07-31T23:59:59",
                }
            ),
            _make_item_promotion_row(payload={"id": "PRICE_DISCOUNT"}),
        ]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_item_promotions("MLA123456789")

        assert result[0]["start_date"] == "2026-07-01T00:00:00"
        assert result[0]["finish_date"] == "2026-07-31T23:59:59"
        assert result[1]["start_date"] is None
        assert result[1]["finish_date"] is None


class TestFetchPromoSummaryByMla:
    """fetch_promo_summary_by_mla(mla_ids) — batched cross-DB summary read.

    One GROUP BY query per call (no N+1). Per-mla dict:
    {"active_count": int, "has_applied": bool, "applied_name": Optional[str]}.
    """

    def test_multiple_mlas_batched_in_one_query_call(self) -> None:
        from app.services.ml_promotions_service import fetch_promo_summary_by_mla

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            ("MLA111", 3, True, "Oferta Relámpago"),
            ("MLA222", 1, False, None),
        ]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_promo_summary_by_mla(["MLA111", "MLA222"])

        assert mock_conn.execute.call_count == 1
        assert result["MLA111"] == {
            "active_count": 3,
            "has_applied": True,
            "applied_name": "Oferta Relámpago",
        }
        assert result["MLA222"] == {
            "active_count": 1,
            "has_applied": False,
            "applied_name": None,
        }

        executed_query = str(mock_conn.execute.call_args[0][0])
        assert "ml_promotions" in executed_query
        assert "LEFT JOIN" in executed_query
        assert "payload->>'name'" in executed_query
        assert "p.name" in executed_query

    def test_applied_name_ordered_by_price_asc_nulls_first(self) -> None:
        """A single item can be `started` in several promos at once; ML
        only applies the lowest-price one (null price counts as active,
        never discarded), so `applied_name` must reflect THAT one, not the
        most recently updated row."""
        from app.services.ml_promotions_service import fetch_promo_summary_by_mla

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            fetch_promo_summary_by_mla(["MLA111"])

        executed_query = str(mock_conn.execute.call_args[0][0])
        assert "ORDER BY ip.price ASC NULLS FIRST" in executed_query

    def test_active_count_counts_candidate_and_started(self) -> None:
        from app.services.ml_promotions_service import fetch_promo_summary_by_mla

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            ("MLA111", 4, True, "Nombre"),
        ]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_promo_summary_by_mla(["MLA111"])

        assert result["MLA111"]["active_count"] == 4

    def test_has_applied_true_when_started_row_exists(self) -> None:
        from app.services.ml_promotions_service import fetch_promo_summary_by_mla

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            ("MLA111", 2, True, "Nombre"),
        ]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_promo_summary_by_mla(["MLA111"])

        assert result["MLA111"]["has_applied"] is True

    def test_has_applied_false_when_no_started_row(self) -> None:
        from app.services.ml_promotions_service import fetch_promo_summary_by_mla

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            ("MLA111", 2, False, None),
        ]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_promo_summary_by_mla(["MLA111"])

        assert result["MLA111"]["has_applied"] is False
        assert result["MLA111"]["applied_name"] is None

    def test_applied_name_uses_payload_name(self) -> None:
        from app.services.ml_promotions_service import fetch_promo_summary_by_mla

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            ("MLA111", 1, True, "Campaña Vendedor"),
        ]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_promo_summary_by_mla(["MLA111"])

        assert result["MLA111"]["applied_name"] == "Campaña Vendedor"

    def test_applied_name_falls_back_to_promotion_type_when_name_null(self) -> None:
        """PRICE_DISCOUNT sends payload.name == "" -> COALESCE(NULLIF(...))
        falls back to promotion_type in the SQL; here we just assert the
        dict passes through whatever the row provides (fallback happens
        in SQL)."""
        from app.services.ml_promotions_service import fetch_promo_summary_by_mla

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            ("MLA111", 1, True, "PRICE_DISCOUNT"),
        ]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_promo_summary_by_mla(["MLA111"])

        assert result["MLA111"]["applied_name"] == "PRICE_DISCOUNT"

    def test_status_clause_includes_pending(self) -> None:
        """REQ-2: summary SQL must include `pending` in its status IN clause."""
        from app.services.ml_promotions_service import fetch_promo_summary_by_mla

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            fetch_promo_summary_by_mla(["MLA111"])

        executed_query = str(mock_conn.execute.call_args[0][0])
        assert "'pending'" in executed_query
        # REGRESSION: has_applied / applied_name FILTER stay started-only.
        assert "ip.status = 'started'" in executed_query

    def test_empty_mla_ids_returns_empty_dict_no_engine_call(self) -> None:
        from app.services.ml_promotions_service import fetch_promo_summary_by_mla

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine") as mock_engine_fn:
            result = fetch_promo_summary_by_mla([])

        assert result == {}
        mock_engine_fn.assert_not_called()

    def test_db_unavailable_raises_runtime_error(self) -> None:
        from app.services.ml_promotions_service import fetch_promo_summary_by_mla

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine") as mock_engine_fn:
            mock_engine_fn.side_effect = RuntimeError("ML_WEBHOOK_DB_URL no configurada")

            with pytest.raises(RuntimeError):
                fetch_promo_summary_by_mla(["MLA111"])


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


class TestFetchMlasWithActivePromoType:
    """fetch_mlas_with_active_promo_type(promo_types, applied_only=False) —
    cross-DB lookup used by the Productos LIST promo-type filter (feature
    productos-list-promo-filter). ONE query per call, DISTINCT mla, filtered
    by promotion_type = ANY(:types) and a status set depending on mode.
    """

    def test_empty_promo_types_returns_empty_set_without_engine_call(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_with_active_promo_type

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine") as mock_engine_fn:
            result = fetch_mlas_with_active_promo_type([])

        assert result == set()
        mock_engine_fn.assert_not_called()

    def test_empty_rows_returns_empty_set(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_with_active_promo_type

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_mlas_with_active_promo_type(["SMART"])

        assert result == set()

    def test_rows_return_set_of_mla(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_with_active_promo_type

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [("MLA111",), ("MLA222",)]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_mlas_with_active_promo_type(["SMART"])

        assert result == {"MLA111", "MLA222"}

    def test_applied_only_false_uses_candidate_started_status(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_with_active_promo_type

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            fetch_mlas_with_active_promo_type(["SMART"], applied_only=False)

        executed_query = str(mock_conn.execute.call_args[0][0])
        assert "IN ('candidate', 'started')" in executed_query
        assert "= 'started'" not in executed_query

    def test_applied_only_true_uses_started_only_status(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_with_active_promo_type

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            fetch_mlas_with_active_promo_type(["SMART"], applied_only=True)

        executed_query = str(mock_conn.execute.call_args[0][0])
        assert "status = 'started'" in executed_query
        assert "IN ('candidate'" not in executed_query

    def test_binds_types_param_via_any(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_with_active_promo_type

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            fetch_mlas_with_active_promo_type(["SMART", "DEAL"])

        executed_query = str(mock_conn.execute.call_args[0][0])
        assert "ANY(:types)" in executed_query
        bound_params = mock_conn.execute.call_args[0][1]
        assert bound_params == {"types": ["SMART", "DEAL"]}

    def test_engine_failure_propagates(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_with_active_promo_type

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine") as mock_engine_fn:
            mock_engine_fn.side_effect = RuntimeError("ML_WEBHOOK_DB_URL no configurada")

            with pytest.raises(RuntimeError):
                fetch_mlas_with_active_promo_type(["SMART"])


def _promo(promotion_id: str, status: str, price: float = None, promotion_type: str = "SELLER_CAMPAIGN") -> dict:
    return {
        "mla": "MLA123456789",
        "promotion_id": promotion_id,
        "promotion_type": promotion_type,
        "status": status,
        "price": price,
    }


class TestDerivarApplicationStatus:
    """A single item can be legitimately `started` in MULTIPLE promos: ML
    applies only the lowest-price one and leaves the rest programmed.
    ML's API never distinguishes these (both show `started`), so
    `derivar_application_status` derives it from `price`."""

    def test_single_min_price_is_active_others_programmed(self) -> None:
        from app.services.ml_promotions_service import derivar_application_status

        promos = [
            _promo("A-1", "started", price=900.0, promotion_type="SMART"),
            _promo("B-1", "started", price=850.0, promotion_type="DEAL"),
            _promo("C-1", "started", price=950.0, promotion_type="SELLER_CAMPAIGN"),
        ]

        result = derivar_application_status(promos)

        by_id = {p["promotion_id"]: p["application_status"] for p in result}
        assert by_id["B-1"] == "active"
        assert by_id["A-1"] == "programmed"
        assert by_id["C-1"] == "programmed"

    def test_tie_on_min_price_marks_all_tied_active(self) -> None:
        from app.services.ml_promotions_service import derivar_application_status

        promos = [
            _promo("A-1", "started", price=850.0),
            _promo("B-1", "started", price=850.0),
            _promo("C-1", "started", price=900.0),
        ]

        result = derivar_application_status(promos)

        by_id = {p["promotion_id"]: p["application_status"] for p in result}
        assert by_id["A-1"] == "active"
        assert by_id["B-1"] == "active"
        assert by_id["C-1"] == "programmed"

    def test_null_price_is_active(self) -> None:
        """A null price is always active; when it's the ONLY other started
        promo, the non-null one is also the min of non-null prices, so it
        is active too."""
        from app.services.ml_promotions_service import derivar_application_status

        promos = [
            _promo("A-1", "started", price=None),
            _promo("B-1", "started", price=900.0),
        ]

        result = derivar_application_status(promos)

        by_id = {p["promotion_id"]: p["application_status"] for p in result}
        assert by_id["A-1"] == "active"
        assert by_id["B-1"] == "active"

    def test_null_price_active_while_higher_non_null_is_programmed(self) -> None:
        """A null-price started promo is active; a non-null started promo
        above the min of non-null prices is programmed."""
        from app.services.ml_promotions_service import derivar_application_status

        promos = [
            _promo("A-1", "started", price=None),
            _promo("B-1", "started", price=850.0),
            _promo("C-1", "started", price=900.0),
        ]

        result = derivar_application_status(promos)

        by_id = {p["promotion_id"]: p["application_status"] for p in result}
        assert by_id["A-1"] == "active"
        assert by_id["B-1"] == "active"
        assert by_id["C-1"] == "programmed"

    def test_all_null_prices_are_all_active(self) -> None:
        from app.services.ml_promotions_service import derivar_application_status

        promos = [
            _promo("A-1", "started", price=None),
            _promo("B-1", "started", price=None),
        ]

        result = derivar_application_status(promos)

        assert all(p["application_status"] == "active" for p in result)

    def test_candidate_has_none_application_status(self) -> None:
        from app.services.ml_promotions_service import derivar_application_status

        promos = [_promo("A-1", "candidate", price=0.0)]

        result = derivar_application_status(promos)

        assert result[0]["application_status"] is None

    def test_no_started_promos_leaves_candidates_untouched(self) -> None:
        from app.services.ml_promotions_service import derivar_application_status

        promos = [_promo("A-1", "candidate", price=0.0), _promo("B-1", "candidate", price=0.0)]

        result = derivar_application_status(promos)

        assert all(p["application_status"] is None for p in result)

    def test_mutates_and_returns_same_list(self) -> None:
        from app.services.ml_promotions_service import derivar_application_status

        promos = [_promo("A-1", "started", price=900.0)]

        result = derivar_application_status(promos)

        assert result is promos

    def test_pending_status_gets_distinct_pending_application_status(self) -> None:
        """REQ-3: pending must NOT be None, active, or programmed."""
        from app.services.ml_promotions_service import derivar_application_status

        promos = [_promo("A-1", "pending", price=None)]

        result = derivar_application_status(promos)

        assert result[0]["application_status"] == "pending"

    def test_pending_status_distinct_when_no_started_promos_present(self) -> None:
        from app.services.ml_promotions_service import derivar_application_status

        promos = [_promo("A-1", "pending", price=None), _promo("B-1", "candidate", price=0.0)]

        result = derivar_application_status(promos)

        by_id = {p["promotion_id"]: p["application_status"] for p in result}
        assert by_id["A-1"] == "pending"
        assert by_id["B-1"] is None

    def test_mixed_pending_and_started_produces_both_distinct_badges(self) -> None:
        from app.services.ml_promotions_service import derivar_application_status

        promos = [
            _promo("A-1", "pending", price=None),
            _promo("B-1", "started", price=900.0),
        ]

        result = derivar_application_status(promos)

        by_id = {p["promotion_id"]: p["application_status"] for p in result}
        assert by_id["A-1"] == "pending"
        assert by_id["B-1"] == "active"


class TestKnownPromotionTypes:
    """KNOWN_PROMOTION_TYPES — vocabulary used by the Productos `promo:` search
    operator to disambiguate a type literal from a promo-name substring
    (feature productos-search-mla-promo-operators, ADR-2)."""

    def test_exactly_eight_known_types(self) -> None:
        from app.services.ml_promotions_service import KNOWN_PROMOTION_TYPES

        assert len(KNOWN_PROMOTION_TYPES) == 8

    def test_uppercase_membership(self) -> None:
        from app.services.ml_promotions_service import KNOWN_PROMOTION_TYPES

        assert "SMART".upper() in KNOWN_PROMOTION_TYPES
        assert "smart".upper() in KNOWN_PROMOTION_TYPES
        assert {
            "SELLER_CAMPAIGN",
            "DEAL",
            "SMART",
            "PRE_NEGOTIATED",
            "PRICE_MATCHING",
            "DOD",
            "LIGHTNING",
            "PRICE_DISCOUNT",
        } == set(KNOWN_PROMOTION_TYPES)


class TestFetchMlasByPromoName:
    """fetch_mlas_by_promo_name(name_substr) — resolves the `promo:` search
    operator when VALUE does not match a known promotion_type (name branch,
    ADR-2/ADR-4)."""

    def test_falsy_input_returns_empty_set_without_engine_call(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_by_promo_name

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine") as mock_engine_fn:
            result = fetch_mlas_by_promo_name("")

        assert result == set()
        mock_engine_fn.assert_not_called()

    def test_whitespace_only_input_returns_empty_set_without_engine_call(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_by_promo_name

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine") as mock_engine_fn:
            result = fetch_mlas_by_promo_name("   ")

        assert result == set()
        mock_engine_fn.assert_not_called()

    def test_empty_rows_returns_empty_set(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_by_promo_name

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_mlas_by_promo_name("FORZA")

        assert result == set()

    def test_rows_return_set_of_mla(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_by_promo_name

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [("MLA111",), ("MLA222",)]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_mlas_by_promo_name("FORZA")

        assert result == {"MLA111", "MLA222"}

    def test_uses_ilike_substring_pattern_and_active_statuses(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_by_promo_name

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            fetch_mlas_by_promo_name("FORZA")

        executed_query = str(mock_conn.execute.call_args[0][0])
        assert "ILIKE" in executed_query
        assert "IN ('candidate', 'started')" in executed_query
        bound_params = mock_conn.execute.call_args[0][1]
        assert bound_params == {"pattern": "%FORZA%"}

    def test_engine_failure_propagates(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_by_promo_name

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine") as mock_engine_fn:
            mock_engine_fn.side_effect = RuntimeError("ML_WEBHOOK_DB_URL no configurada")

            with pytest.raises(RuntimeError):
                fetch_mlas_by_promo_name("FORZA")


class TestFetchMlasWithStarted:
    """fetch_mlas_with_started() — dedicated, type-agnostic helper for the
    `con_promo_aplicada` boolean filter (ADR-3: NOT a wrapper over
    fetch_mlas_with_active_promo_type)."""

    def test_empty_rows_returns_empty_set(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_with_started

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_mlas_with_started()

        assert result == set()

    def test_rows_return_set_of_mla(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_with_started

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [("MLA111",), ("MLA222",)]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_mlas_with_started()

        assert result == {"MLA111", "MLA222"}

    def test_engine_failure_propagates(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_with_started

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine") as mock_engine_fn:
            mock_engine_fn.side_effect = RuntimeError("ML_WEBHOOK_DB_URL no configurada")

            with pytest.raises(RuntimeError):
                fetch_mlas_with_started()


class TestFetchMlasWithCandidateNotStarted:
    """fetch_mlas_with_candidate_not_started() — resolves `con_promo_sin_aplicar`:
    at least one candidate promo AND zero started promos, per MLA (compound
    aggregation, mirrors fetch_promo_summary_by_mla's bool_or GROUP BY)."""

    def test_empty_rows_returns_empty_set(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_with_candidate_not_started

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_mlas_with_candidate_not_started()

        assert result == set()

    def test_rows_return_set_of_mla(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_with_candidate_not_started

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [("MLA111",), ("MLA222",)]

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            result = fetch_mlas_with_candidate_not_started()

        assert result == {"MLA111", "MLA222"}

    def test_query_uses_group_by_having_bool_or(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_with_candidate_not_started

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine", return_value=mock_engine):
            fetch_mlas_with_candidate_not_started()

        executed_query = str(mock_conn.execute.call_args[0][0])
        assert "GROUP BY" in executed_query
        assert "HAVING" in executed_query
        assert "bool_or" in executed_query

    def test_engine_failure_propagates(self) -> None:
        from app.services.ml_promotions_service import fetch_mlas_with_candidate_not_started

        with patch("app.services.ml_promotions_service.get_mlwebhook_engine") as mock_engine_fn:
            mock_engine_fn.side_effect = RuntimeError("ML_WEBHOOK_DB_URL no configurada")

            with pytest.raises(RuntimeError):
                fetch_mlas_with_candidate_not_started()
