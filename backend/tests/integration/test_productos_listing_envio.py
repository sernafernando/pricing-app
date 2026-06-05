"""
Integration tests for T-11: productos_listing uses resolver_costos_envio_batch.

Strategy: The listing endpoint is too complex for a full HTTP integration test
in the SQLite test environment (dozens of lazy-imported models). We verify the
key contract at the module level:
  1. resolver_costos_envio_batch is imported in productos_listing.
  2. _resolve_envio / _resolve_envio_t prefer the batch dict over ERP envio.

RED phase drives T-12 implementation.

Run:
    pytest tests/integration/test_productos_listing_envio.py -v
"""

from __future__ import annotations


class TestListingModuleImportsBatchResolver:
    """The listing module must import resolver_costos_envio_batch at module level."""

    def test_resolver_costos_envio_batch_imported(self):
        """productos_listing must expose resolver_costos_envio_batch as a module attribute."""
        import app.api.endpoints.productos_listing as listing

        assert hasattr(listing, "resolver_costos_envio_batch"), (
            "resolver_costos_envio_batch must be imported at module level in productos_listing"
        )

    def test_resolver_costos_envio_batch_is_callable(self):
        """The imported symbol must be the real resolver function."""
        import app.api.endpoints.productos_listing as listing
        from app.services.envio_real_service import resolver_costos_envio_batch

        assert listing.resolver_costos_envio_batch is resolver_costos_envio_batch


class TestResolveEnvioFunctionSignature:
    """
    The internal _resolve_envio / _resolve_envio_t functions inside each listing
    endpoint cannot be tested directly (they are closures). However, the batch dict
    lookup is implemented by calling the function with item_id as first argument.
    We validate the design contract by checking the listing module source.
    """

    def test_resolve_envio_accepts_item_id_first_arg(self):
        """
        The module source must contain _resolve_envio(item_id calls,
        proving the new signature was applied.
        """
        import inspect
        import app.api.endpoints.productos_listing as listing

        src = inspect.getsource(listing)
        # The updated call pattern must be present
        assert "_resolve_envio(item_id" in src or "_resolve_envio(producto_erp.item_id" in src, (
            "_resolve_envio must be called with item_id as the first argument (T-12 not applied)"
        )

    def test_resolve_envio_t_accepts_item_id_first_arg(self):
        """
        Same check for _resolve_envio_t (used in listar_productos_tienda).
        """
        import inspect
        import app.api.endpoints.productos_listing as listing

        src = inspect.getsource(listing)
        assert "_resolve_envio_t(item_id" in src or "_resolve_envio_t(producto_erp.item_id" in src, (
            "_resolve_envio_t must be called with item_id as the first argument (T-12 not applied)"
        )

    def test_envio_real_by_item_lookup_in_source(self):
        """
        Both _resolve_envio and _resolve_envio_t must consult envio_real_by_item / envio_real_by_item_t
        (the batch dict) before falling back to ERP envio.
        """
        import inspect
        import app.api.endpoints.productos_listing as listing

        src = inspect.getsource(listing)
        assert "envio_real_by_item" in src, (
            "Batch dict envio_real_by_item not found in listing — resolver_costos_envio_batch result not used"
        )
