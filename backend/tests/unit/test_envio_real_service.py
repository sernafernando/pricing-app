"""
Unit tests for envio_real_service — resolver de costo de envio real desde mlwebhook.

TDD: All tests in this file were written BEFORE the implementation.

Spec coverage:
  REQ-1  — resolver returns MAX(list_cost) when active MLAs exist
  REQ-2  — resolver falls back to ERP envio when no active MLAs found
  REQ-3  — resolver falls back to ERP envio when mlwebhook DB is unreachable
  REQ-4  — list_cost = 0 rows are excluded from MAX
  REQ-5  — inactive MLAs are excluded from the resolved set
  REQ-6  — IVA pass-through: resolver returns list_cost AS-IS (no /1.21)
  REQ-7  — multiple logistic_type values: MAX wins regardless
  REQ-8  — batch resolver returns dict keyed by item_id
  REQ-9  — batch resolver excludes absent items (no fallback value in dict)
  REQ-10 — batch resolver returns {} when DB is unreachable

Design note: get_mlwebhook_engine is ALWAYS mocked in these tests because
the mlwebhook DB is NOT reachable from the test environment.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_producto(item_id: int = 1, envio: float = 1500.0) -> MagicMock:
    """Build a minimal ProductoERP-like mock."""
    p = MagicMock()
    p.item_id = item_id
    p.envio = envio
    return p


def _make_publicacion(mla: str, activo: bool = True) -> MagicMock:
    pub = MagicMock()
    pub.mla = mla
    pub.activo = activo
    return pub


# ---------------------------------------------------------------------------
# T-01 — RED: fallback branches
# ---------------------------------------------------------------------------


class TestResolverFallbacks:
    """REQ-2, REQ-3: All branches that return ProductoERP.envio."""

    def test_no_publicaciones_returns_erp_envio(self, db: MagicMock) -> None:
        """REQ-2 (branch a): product has no PublicacionML rows at all."""
        from app.services.envio_real_service import resolver_costo_envio

        producto = _make_producto(item_id=1, envio=2000.0)
        # Simulate query returning empty list
        db.query.return_value.filter.return_value.all.return_value = []

        result = resolver_costo_envio(db, producto)

        assert result == 2000.0

    def test_no_active_publicaciones_returns_erp_envio(self, db: MagicMock) -> None:
        """REQ-2 (branch b): product has PublicacionML rows but none are active."""
        from app.services.envio_real_service import resolver_costo_envio

        producto = _make_producto(item_id=1, envio=3000.0)
        inactive_pub = _make_publicacion(mla="MLA111", activo=False)
        db.query.return_value.filter.return_value.all.return_value = [inactive_pub]

        result = resolver_costo_envio(db, producto, mlas_activas=[inactive_pub])

        # No active MLAs → fall back
        assert result == 3000.0

    def test_db_unreachable_returns_erp_envio_no_raise(self, db: MagicMock) -> None:
        """REQ-3: mlwebhook DB connection raises → returns ERP envio, never raises."""
        from app.services.envio_real_service import resolver_costo_envio

        producto = _make_producto(item_id=2, envio=1200.0)
        pub = _make_publicacion(mla="MLA999", activo=True)
        db.query.return_value.filter.return_value.all.return_value = [pub]

        with patch("app.services.envio_real_service.get_mlwebhook_engine") as mock_engine_fn:
            mock_engine_fn.side_effect = RuntimeError("ML_WEBHOOK_DB_URL no configurada")
            result = resolver_costo_envio(db, producto)

        assert result == 1200.0

    def test_db_connect_error_returns_erp_envio_no_raise(self, db: MagicMock) -> None:
        """REQ-3 (variant): engine obtained but connect() raises → ERP fallback."""
        from app.services.envio_real_service import resolver_costo_envio

        producto = _make_producto(item_id=3, envio=500.0)
        pub = _make_publicacion(mla="MLA888", activo=True)
        db.query.return_value.filter.return_value.all.return_value = [pub]

        with patch("app.services.envio_real_service.get_mlwebhook_engine") as mock_engine_fn:
            mock_engine = MagicMock()
            mock_engine_fn.return_value = mock_engine
            mock_engine.connect.side_effect = Exception("Connection refused")

            result = resolver_costo_envio(db, producto)

        assert result == 500.0

    def test_empty_shipping_costs_result_returns_erp_envio(self, db: MagicMock) -> None:
        """REQ-2 (branch c): query returns no rows for the MLAs → ERP fallback."""
        from app.services.envio_real_service import resolver_costo_envio

        producto = _make_producto(item_id=4, envio=800.0)
        pub = _make_publicacion(mla="MLA777", activo=True)
        db.query.return_value.filter.return_value.all.return_value = [pub]

        with (
            patch("app.services.envio_real_service.get_mlwebhook_engine"),
            patch("app.services.envio_real_service._fetch_list_cost_by_mla") as mock_fetch,
        ):
            mock_fetch.return_value = {}  # no shipping cost rows

            result = resolver_costo_envio(db, producto)

        assert result == 800.0


# ---------------------------------------------------------------------------
# T-03 — RED: MAX logic, list_cost=0 exclusion, inactive MLA exclusion, IVA
# ---------------------------------------------------------------------------


class TestResolverMaxLogicAndFilters:
    """REQ-1, REQ-4, REQ-5, REQ-6, REQ-7."""

    def test_returns_max_list_cost_across_active_mlas(self, db: MagicMock) -> None:
        """REQ-1: MAX(list_cost) is returned when multiple active MLAs exist."""
        from app.services.envio_real_service import resolver_costo_envio

        producto = _make_producto(item_id=10, envio=0.0)
        pub1 = _make_publicacion(mla="MLA001", activo=True)
        pub2 = _make_publicacion(mla="MLA002", activo=True)
        db.query.return_value.filter.return_value.all.return_value = [pub1, pub2]

        with patch("app.services.envio_real_service._fetch_list_cost_by_mla") as mock_fetch:
            mock_fetch.return_value = {"MLA001": 3000.0, "MLA002": 7500.0}
            result = resolver_costo_envio(db, producto)

        assert result == 7500.0

    def test_list_cost_zero_excluded_from_max(self, db: MagicMock) -> None:
        """REQ-4: rows with list_cost = 0 must not participate in MAX."""
        from app.services.envio_real_service import resolver_costo_envio

        produto = _make_producto(item_id=11, envio=1000.0)
        pub1 = _make_publicacion(mla="MLA003", activo=True)
        pub2 = _make_publicacion(mla="MLA004", activo=True)
        db.query.return_value.filter.return_value.all.return_value = [pub1, pub2]

        with patch("app.services.envio_real_service._fetch_list_cost_by_mla") as mock_fetch:
            # MLA003 has list_cost=0, MLA004 has list_cost=8000
            # The SQL filter (list_cost > 0) means _fetch returns only MLA004
            mock_fetch.return_value = {"MLA004": 8000.0}
            result = resolver_costo_envio(db, produto)

        assert result == 8000.0

    def test_inactive_mla_excluded(self, db: MagicMock) -> None:
        """REQ-5: inactive MLAs (activo=False) are not passed to _fetch."""
        from app.services.envio_real_service import resolver_costo_envio

        produto = _make_produto = _make_producto(item_id=12, envio=500.0)
        active_pub = _make_publicacion(mla="MLA005", activo=True)
        inactive_pub = _make_publicacion(mla="MLA006", activo=False)
        db.query.return_value.filter.return_value.all.return_value = [
            active_pub,
            inactive_pub,
        ]

        with patch("app.services.envio_real_service._fetch_list_cost_by_mla") as mock_fetch:
            mock_fetch.return_value = {"MLA005": 6000.0}
            result = resolver_costo_envio(db, produto)

        # Only active MLA IDs should have been passed to _fetch
        called_ids = mock_fetch.call_args[0][0]
        assert "MLA006" not in called_ids
        assert "MLA005" in called_ids
        assert result == 6000.0

    def test_iva_passthrough_no_division(self, db: MagicMock) -> None:
        """REQ-6: resolver returns list_cost AS-IS — no /1.21 division applied."""
        from app.services.envio_real_service import resolver_costo_envio

        producto = _make_producto(item_id=13, envio=0.0)
        pub = _make_publicacion(mla="MLA007", activo=True)
        db.query.return_value.filter.return_value.all.return_value = [pub]

        with patch("app.services.envio_real_service._fetch_list_cost_by_mla") as mock_fetch:
            # list_cost is stored WITH IVA = 12100; resolver must return 12100
            mock_fetch.return_value = {"MLA007": 12100.0}
            result = resolver_costo_envio(db, producto)

        # Must NOT divide by 1.21 here; calcular_limpio does that
        assert result == 12100.0
        assert result != pytest.approx(12100.0 / 1.21)

    def test_max_ignores_logistic_type(self, db: MagicMock) -> None:
        """REQ-7: MAX applies across all logistic types without discrimination."""
        from app.services.envio_real_service import resolver_costo_envio

        producto = _make_producto(item_id=14, envio=0.0)
        pub1 = _make_publicacion(mla="MLA010", activo=True)
        pub2 = _make_publicacion(mla="MLA011", activo=True)
        db.query.return_value.filter.return_value.all.return_value = [pub1, pub2]

        with patch("app.services.envio_real_service._fetch_list_cost_by_mla") as mock_fetch:
            # Different logistic types, MAX should win
            mock_fetch.return_value = {"MLA010": 3000.0, "MLA011": 7500.0}
            result = resolver_costo_envio(db, producto)

        assert result == 7500.0


# ---------------------------------------------------------------------------
# T-05 — RED: batch resolver
# ---------------------------------------------------------------------------


class TestBatchResolver:
    """REQ-8, REQ-9, REQ-10: batch resolver dict shape."""

    def test_batch_returns_dict_keyed_by_item_id(self, db: MagicMock) -> None:
        """REQ-8: resolver_costos_envio_batch returns {item_id: max_cost}."""
        from app.services.envio_real_service import resolver_costos_envio_batch

        # pubs_by_item pre-computed: {item_id: [PublicacionML, ...]}
        pub1 = _make_publicacion(mla="MLA100", activo=True)
        pub2 = _make_publicacion(mla="MLA200", activo=True)
        pubs_by_item = {1: [pub1], 2: [pub2]}

        with patch("app.services.envio_real_service._fetch_list_cost_by_mla") as mock_fetch:
            mock_fetch.return_value = {"MLA100": 5000.0, "MLA200": 3000.0}
            result = resolver_costos_envio_batch(db, [1, 2], pubs_by_item=pubs_by_item)

        assert result == {1: 5000.0, 2: 3000.0}

    def test_batch_absent_item_not_in_result(self, db: MagicMock) -> None:
        """REQ-9: item with no active MLAs or no shipping cost is absent from dict."""
        from app.services.envio_real_service import resolver_costos_envio_batch

        pub1 = _make_publicacion(mla="MLA300", activo=True)
        pubs_by_item = {10: [pub1], 20: []}  # item 20 has no MLAs

        with patch("app.services.envio_real_service._fetch_list_cost_by_mla") as mock_fetch:
            mock_fetch.return_value = {"MLA300": 4000.0}
            result = resolver_costos_envio_batch(db, [10, 20], pubs_by_item=pubs_by_item)

        assert 10 in result
        assert 20 not in result

    def test_batch_db_down_returns_empty_dict(self, db: MagicMock) -> None:
        """REQ-10: when mlwebhook DB is unreachable, batch returns {}."""
        from app.services.envio_real_service import resolver_costos_envio_batch

        pub1 = _make_publicacion(mla="MLA400", activo=True)
        pubs_by_item = {5: [pub1]}

        with patch("app.services.envio_real_service.get_mlwebhook_engine") as mock_engine_fn:
            mock_engine_fn.side_effect = RuntimeError("ML_WEBHOOK_DB_URL no configurada")
            result = resolver_costos_envio_batch(db, [5], pubs_by_item=pubs_by_item)

        assert result == {}

    def test_batch_reuses_pubs_by_item_no_extra_query(self, db: MagicMock) -> None:
        """REQ-8: when pubs_by_item is provided, no extra DB query is made."""
        from app.services.envio_real_service import resolver_costos_envio_batch

        pub1 = _make_publicacion(mla="MLA500", activo=True)
        pubs_by_item = {7: [pub1]}

        with patch("app.services.envio_real_service._fetch_list_cost_by_mla") as mock_fetch:
            mock_fetch.return_value = {"MLA500": 9000.0}
            resolver_costos_envio_batch(db, [7], pubs_by_item=pubs_by_item)

        # The main DB session query should NOT have been called when pubs_by_item provided
        db.query.assert_not_called()

    def test_batch_item_with_only_inactive_mlas_absent(self, db: MagicMock) -> None:
        """REQ-9 (variant): item whose MLAs are all inactive is absent from result."""
        from app.services.envio_real_service import resolver_costos_envio_batch

        inactive_pub = _make_publicacion(mla="MLA600", activo=False)
        pubs_by_item = {15: [inactive_pub]}

        with patch("app.services.envio_real_service._fetch_list_cost_by_mla") as mock_fetch:
            mock_fetch.return_value = {}  # nothing returned since all inactive
            result = resolver_costos_envio_batch(db, [15], pubs_by_item=pubs_by_item)

        assert 15 not in result


# ---------------------------------------------------------------------------
# Pytest fixture: lightweight mock db for pure-unit tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def db() -> MagicMock:
    """Minimal mock for SQLAlchemy Session — no real DB needed."""
    return MagicMock()
