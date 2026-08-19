"""Unit tests for the cross-DB (mlwebhook) PxQ tier readers.

Mirrors `tests/unit/test_ml_promotions_service.py::TestFetchMlasWithActivePromoType`:
the mlwebhook engine is never reachable in tests, so it is mocked at the
module's import site and the assertions cover the CONTRACT (one batched query,
DISTINCT/ordered shape, empty-set guards, error propagation) rather than SQL
execution.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.services.ml_pxq_tiers_read_service import (
    PxqTier,
    fetch_mlas_with_pxq_tiers,
    fetch_pxq_tiers_by_mla,
)

_ENGINE_PATH = "app.services.ml_pxq_tiers_read_service.get_mlwebhook_engine"


def _mock_engine(rows):
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchall.return_value = rows
    return mock_engine, mock_conn


class TestFetchMlasWithPxqTiers:
    def test_empty_rows_returns_empty_set(self) -> None:
        mock_engine, _ = _mock_engine([])

        with patch(_ENGINE_PATH, return_value=mock_engine):
            assert fetch_mlas_with_pxq_tiers() == set()

    def test_rows_return_set_of_mla(self) -> None:
        mock_engine, _ = _mock_engine([("MLA111",), ("MLA222",)])

        with patch(_ENGINE_PATH, return_value=mock_engine):
            assert fetch_mlas_with_pxq_tiers() == {"MLA111", "MLA222"}

    def test_issues_exactly_one_distinct_query(self) -> None:
        mock_engine, mock_conn = _mock_engine([])

        with patch(_ENGINE_PATH, return_value=mock_engine):
            fetch_mlas_with_pxq_tiers()

        assert mock_conn.execute.call_count == 1
        executed = str(mock_conn.execute.call_args[0][0])
        assert "SELECT DISTINCT mla" in executed
        assert "ml_pxq_price_tiers" in executed

    def test_mla_ids_scopes_the_query_to_those_mlas(self) -> None:
        """Per-MLA callers (the detail/tree `matches_filter` fold) resolve
        over ONE product's publications — never the whole account universe.
        Mirrors `fetch_mlas_with_active_promo_type`'s `mla_ids`."""
        mock_engine, mock_conn = _mock_engine([("MLA111",)])

        with patch(_ENGINE_PATH, return_value=mock_engine):
            result = fetch_mlas_with_pxq_tiers(mla_ids=["MLA111", "MLA222"])

        assert result == {"MLA111"}
        executed = str(mock_conn.execute.call_args[0][0])
        assert "mla = ANY(:mla_ids)" in executed
        assert mock_conn.execute.call_args[0][1] == {"mla_ids": ["MLA111", "MLA222"]}

    def test_no_mla_ids_keeps_the_unbounded_universe_query(self) -> None:
        mock_engine, mock_conn = _mock_engine([])

        with patch(_ENGINE_PATH, return_value=mock_engine):
            fetch_mlas_with_pxq_tiers()

        assert "ANY(:mla_ids)" not in str(mock_conn.execute.call_args[0][0])

    def test_empty_mla_ids_returns_empty_set_without_engine_call(self) -> None:
        """A product with zero publications cannot match: no query, and the
        empty set means "nothing matches", not "filter off"."""
        with patch(_ENGINE_PATH) as mock_engine_fn:
            assert fetch_mlas_with_pxq_tiers(mla_ids=[]) == set()

        mock_engine_fn.assert_not_called()

    def test_missing_env_runtimeerror_propagates(self) -> None:
        """The endpoint helper (`_resolve_and_fold_mlas`) is what maps this to
        a 503 — the reader must NOT swallow it into an empty set, which would
        read as 'no product has tiers' and silently return zero rows."""
        with patch(_ENGINE_PATH, side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada")):
            with pytest.raises(RuntimeError):
                fetch_mlas_with_pxq_tiers()

    def test_connection_failure_propagates(self) -> None:
        with patch(_ENGINE_PATH, side_effect=SQLAlchemyError("down")):
            with pytest.raises(SQLAlchemyError):
                fetch_mlas_with_pxq_tiers()


class TestFetchPxqTiersByMla:
    def test_empty_mla_ids_returns_empty_dict_without_engine_call(self) -> None:
        with patch(_ENGINE_PATH) as mock_engine_fn:
            assert fetch_pxq_tiers_by_mla([]) == {}

        mock_engine_fn.assert_not_called()

    def test_groups_rows_by_mla(self) -> None:
        mock_engine, _ = _mock_engine(
            [
                ("MLA111", 2, Decimal("50.00")),
                ("MLA111", 5, Decimal("37.80")),
                ("MLA222", 3, Decimal("10.00")),
            ]
        )

        with patch(_ENGINE_PATH, return_value=mock_engine):
            result = fetch_pxq_tiers_by_mla(["MLA111", "MLA222"])

        assert result == {
            "MLA111": [PxqTier(quantity=2, amount=50.0), PxqTier(quantity=5, amount=37.8)],
            "MLA222": [PxqTier(quantity=3, amount=10.0)],
        }

    def test_is_one_batched_query_scoped_to_the_given_mlas(self) -> None:
        """Never N+1: one query for the whole page, bound to :mla_ids."""
        mock_engine, mock_conn = _mock_engine([])

        with patch(_ENGINE_PATH, return_value=mock_engine):
            fetch_pxq_tiers_by_mla(["MLA111", "MLA222"])

        assert mock_conn.execute.call_count == 1
        executed = str(mock_conn.execute.call_args[0][0])
        assert "mla = ANY(:mla_ids)" in executed
        assert "ORDER BY" in executed and "quantity" in executed
        assert mock_conn.execute.call_args[0][1] == {"mla_ids": ["MLA111", "MLA222"]}

    def test_tiers_are_sorted_by_quantity_even_if_rows_arrive_unordered(self) -> None:
        mock_engine, _ = _mock_engine(
            [
                ("MLA111", 10, Decimal("30.00")),
                ("MLA111", 2, Decimal("50.00")),
            ]
        )

        with patch(_ENGINE_PATH, return_value=mock_engine):
            result = fetch_pxq_tiers_by_mla(["MLA111"])

        assert [t.quantity for t in result["MLA111"]] == [2, 10]

    def test_failure_propagates(self) -> None:
        """Fail-open is the CALLER's decision (the quick view must never 503);
        the reader still surfaces the fault instead of faking an empty read."""
        with patch(_ENGINE_PATH, side_effect=SQLAlchemyError("down")):
            with pytest.raises(SQLAlchemyError):
                fetch_pxq_tiers_by_mla(["MLA111"])
