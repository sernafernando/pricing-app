"""
TDD RED→GREEN tests — recalcular_markups_service uses the real-shipping batch resolver.

Sentinel values:
  item_id=1  →  batch resolver returns 9999.0  (sentinel, should be used)
  item_id=2  →  absent from batch dict         (ERP fallback: producto.envio = 500)
  DB down    →  batch dict = {}                (ERP fallback for every product)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PATCH_BASE = "app.services.recalcular_markups_service"


def _make_pricing(item_id: int, precio_lista_ml: float | None = 100_000.0) -> MagicMock:
    m = MagicMock()
    m.item_id = item_id
    m.precio_lista_ml = precio_lista_ml
    m.markup_calculado = None
    return m


def _make_producto(item_id: int, envio: float = 500.0, moneda: str = "ARS") -> MagicMock:
    m = MagicMock()
    m.item_id = item_id
    m.envio = envio
    m.costo = 80_000
    m.moneda_costo = moneda
    m.iva = 21.0
    m.subcategoria_id = 1
    return m


def _run_recalc(
    db: MagicMock,
    pricings: list,
    productos: list,
    batch_return: dict,
    limpio_calls: list,
) -> None:
    """Shared harness: patches everything and calls recalcular_markups."""

    def _db_query_side_effect(*args):
        mock_q = MagicMock()
        # All pricings query (filter.all)
        mock_q.filter.return_value.all.return_value = pricings
        # Per-product query (filter.first) — side_effect will be consumed in order
        mock_q.filter.return_value.first.side_effect = list(productos)
        return mock_q

    db.query.side_effect = _db_query_side_effect

    def capturing_calcular_limpio(precio, iva, envio, comision, **kwargs):
        limpio_calls.append(envio)
        return 70_000.0

    with (
        patch(f"{_PATCH_BASE}.resolver_costos_envio_batch", return_value=batch_return),
        patch(f"{_PATCH_BASE}.calcular_limpio", side_effect=capturing_calcular_limpio),
        patch(f"{_PATCH_BASE}.calcular_comision_ml_total", return_value={"comision_total": 5000}),
        patch(f"{_PATCH_BASE}.calcular_markup", return_value=0.25),
        patch(f"{_PATCH_BASE}.obtener_tipo_cambio_actual", return_value=None),
        patch(f"{_PATCH_BASE}.convertir_a_pesos", return_value=80_000.0),
        patch(f"{_PATCH_BASE}.obtener_grupo_subcategoria", return_value=1),
        patch(f"{_PATCH_BASE}.obtener_comision_base", return_value=MagicMock()),
    ):
        from app.services.recalcular_markups_service import recalcular_markups

        recalcular_markups(db)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRecalcularMarkupsServiceUsesResolver:
    """recalcular_markups must call resolver_costos_envio_batch once and use the result."""

    def test_resolver_called_once_for_all_products(self):
        """
        resolver_costos_envio_batch must be called ONCE per recalcular_markups invocation,
        not once per product.
        """
        db = MagicMock()
        pricing_1 = _make_pricing(1)
        pricing_2 = _make_pricing(2)
        prod_1 = _make_produto_p1 = _make_producto(1)
        prod_2 = _make_produto_p2 = _make_producto(2)

        def _db_query_side(*args):
            mock_q = MagicMock()
            mock_q.filter.return_value.all.return_value = [pricing_1, pricing_2]
            mock_q.filter.return_value.first.side_effect = [prod_1, prod_2]
            return mock_q

        db.query.side_effect = _db_query_side

        with (
            patch(f"{_PATCH_BASE}.resolver_costos_envio_batch", return_value={1: 9999.0}) as mock_batch,
            patch(f"{_PATCH_BASE}.calcular_limpio", return_value=70_000.0),
            patch(f"{_PATCH_BASE}.calcular_comision_ml_total", return_value={"comision_total": 5000}),
            patch(f"{_PATCH_BASE}.calcular_markup", return_value=0.25),
            patch(f"{_PATCH_BASE}.obtener_tipo_cambio_actual", return_value=None),
            patch(f"{_PATCH_BASE}.convertir_a_pesos", return_value=80_000.0),
            patch(f"{_PATCH_BASE}.obtener_grupo_subcategoria", return_value=1),
            patch(f"{_PATCH_BASE}.obtener_comision_base", return_value=MagicMock()),
        ):
            from app.services.recalcular_markups_service import recalcular_markups

            recalcular_markups(db)

        mock_batch.assert_called_once()

    def test_sentinel_envio_used_for_product_in_batch_dict(self):
        """
        calcular_limpio must receive the sentinel value (9999.0) for item_id=1.
        """
        db = MagicMock()
        pricing_1 = _make_pricing(1)
        prod_1 = _make_producto(1, envio=500.0)

        limpio_calls: list[Any] = []

        def _db_query_side(*args):
            mock_q = MagicMock()
            mock_q.filter.return_value.all.return_value = [pricing_1]
            mock_q.filter.return_value.first.return_value = prod_1
            return mock_q

        db.query.side_effect = _db_query_side

        def capturing(precio, iva, envio, comision, **kwargs):
            limpio_calls.append(envio)
            return 70_000.0

        with (
            patch(f"{_PATCH_BASE}.resolver_costos_envio_batch", return_value={1: 9999.0}),
            patch(f"{_PATCH_BASE}.calcular_limpio", side_effect=capturing),
            patch(f"{_PATCH_BASE}.calcular_comision_ml_total", return_value={"comision_total": 5000}),
            patch(f"{_PATCH_BASE}.calcular_markup", return_value=0.25),
            patch(f"{_PATCH_BASE}.obtener_tipo_cambio_actual", return_value=None),
            patch(f"{_PATCH_BASE}.convertir_a_pesos", return_value=80_000.0),
            patch(f"{_PATCH_BASE}.obtener_grupo_subcategoria", return_value=1),
            patch(f"{_PATCH_BASE}.obtener_comision_base", return_value=MagicMock()),
        ):
            from app.services.recalcular_markups_service import recalcular_markups

            recalcular_markups(db)

        assert limpio_calls, "calcular_limpio was never called"
        assert limpio_calls[0] == 9999.0, f"Expected sentinel 9999.0 for item_id=1, got {limpio_calls[0]}"

    def test_erp_envio_used_for_product_absent_from_batch_dict(self):
        """
        calcular_limpio must receive producto.envio (500.0) for item_id=2,
        which is absent from the batch dict.
        """
        db = MagicMock()
        pricing_2 = _make_pricing(2)
        prod_2 = _make_producto(2, envio=500.0)

        limpio_calls: list[Any] = []

        def _db_query_side(*args):
            mock_q = MagicMock()
            mock_q.filter.return_value.all.return_value = [pricing_2]
            mock_q.filter.return_value.first.return_value = prod_2
            return mock_q

        db.query.side_effect = _db_query_side

        def capturing(precio, iva, envio, comision, **kwargs):
            limpio_calls.append(envio)
            return 70_000.0

        with (
            patch(f"{_PATCH_BASE}.resolver_costos_envio_batch", return_value={1: 9999.0}),
            patch(f"{_PATCH_BASE}.calcular_limpio", side_effect=capturing),
            patch(f"{_PATCH_BASE}.calcular_comision_ml_total", return_value={"comision_total": 5000}),
            patch(f"{_PATCH_BASE}.calcular_markup", return_value=0.25),
            patch(f"{_PATCH_BASE}.obtener_tipo_cambio_actual", return_value=None),
            patch(f"{_PATCH_BASE}.convertir_a_pesos", return_value=80_000.0),
            patch(f"{_PATCH_BASE}.obtener_grupo_subcategoria", return_value=1),
            patch(f"{_PATCH_BASE}.obtener_comision_base", return_value=MagicMock()),
        ):
            from app.services.recalcular_markups_service import recalcular_markups

            recalcular_markups(db)

        assert limpio_calls, "calcular_limpio was never called"
        assert limpio_calls[0] == 500.0, f"Expected ERP fallback 500.0 for item_id=2, got {limpio_calls[0]}"

    def test_batch_resolver_down_falls_back_to_erp(self):
        """
        When resolver_costos_envio_batch returns {} (DB down), every product
        falls back to producto.envio.
        """
        db = MagicMock()
        pricing_1 = _make_pricing(1)
        prod_1 = _make_producto(1, envio=777.0)

        limpio_calls: list[Any] = []

        def _db_query_side(*args):
            mock_q = MagicMock()
            mock_q.filter.return_value.all.return_value = [pricing_1]
            mock_q.filter.return_value.first.return_value = prod_1
            return mock_q

        db.query.side_effect = _db_query_side

        def capturing(precio, iva, envio, comision, **kwargs):
            limpio_calls.append(envio)
            return 70_000.0

        with (
            patch(f"{_PATCH_BASE}.resolver_costos_envio_batch", return_value={}),
            patch(f"{_PATCH_BASE}.calcular_limpio", side_effect=capturing),
            patch(f"{_PATCH_BASE}.calcular_comision_ml_total", return_value={"comision_total": 5000}),
            patch(f"{_PATCH_BASE}.calcular_markup", return_value=0.25),
            patch(f"{_PATCH_BASE}.obtener_tipo_cambio_actual", return_value=None),
            patch(f"{_PATCH_BASE}.convertir_a_pesos", return_value=80_000.0),
            patch(f"{_PATCH_BASE}.obtener_grupo_subcategoria", return_value=1),
            patch(f"{_PATCH_BASE}.obtener_comision_base", return_value=MagicMock()),
        ):
            from app.services.recalcular_markups_service import recalcular_markups

            recalcular_markups(db)

        assert limpio_calls, "calcular_limpio was never called"
        assert limpio_calls[0] == 777.0, (
            f"Expected ERP fallback 777.0 when batch returns empty dict, got {limpio_calls[0]}"
        )
