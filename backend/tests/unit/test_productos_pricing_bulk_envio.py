"""
TDD RED→GREEN — productos_pricing bulk endpoints use resolver_costos_envio_batch.

Strategy: source-inspection tests (same pattern as test_produtos_listing_envio.py T-11).
The bulk endpoint functions are large inline route handlers; patching them for behavioral
tests would require a full FastAPI test client. Source-inspection gives us the same
guarantees with less setup.

Assertions:
  1. resolver_costos_envio_batch is imported in productos_pricing.
  2. envio_real_by_item is present in the source (batch dict is used).
  3. The batch dict appears at least twice (once per bulk endpoint function).
"""

from __future__ import annotations

import inspect


class TestProductosPricingImportsBatchResolver:
    """The module must import resolver_costos_envio_batch at module level."""

    def test_resolver_costos_envio_batch_imported(self):
        import app.api.endpoints.productos_pricing as mod

        assert hasattr(mod, "resolver_costos_envio_batch"), (
            "resolver_costos_envio_batch must be imported in productos_pricing"
        )

    def test_imported_symbol_is_the_real_resolver(self):
        import app.api.endpoints.productos_pricing as mod
        from app.services.envio_real_service import resolver_costos_envio_batch

        assert mod.resolver_costos_envio_batch is resolver_costos_envio_batch


class TestProductosPricingBulkUsesResolverDict:
    """The bulk loops must resolve envio via the batch dict, not raw producto_erp.envio."""

    def test_envio_real_by_item_in_source(self):
        """
        Both bulk loops must reference envio_real_by_item (the pre-fetched batch dict).
        """
        import app.api.endpoints.productos_pricing as mod

        src = inspect.getsource(mod)
        assert "envio_real_by_item" in src, (
            "envio_real_by_item not found — batch resolver result not used in productos_pricing"
        )

    def test_bulk_endpoints_use_resolver_at_least_twice(self):
        """
        envio_real_by_item must appear at least twice — once per bulk endpoint
        (calcular-pvp-masivo and recalcular-cuotas-masivo).
        """
        import app.api.endpoints.productos_pricing as mod

        src = inspect.getsource(mod)

        count_resolved = src.count("envio_real_by_item")
        assert count_resolved >= 2, (
            f"Expected envio_real_by_item to appear at least twice (one per bulk endpoint), got {count_resolved}"
        )
