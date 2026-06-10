"""
TDD RED→GREEN — cron scripts use resolver_costos_envio_batch instead of raw producto.envio.

Scripts tested:
  - app.scripts.recalcular_markups_pricing  (main function)
  - app.scripts.calcular_markups_rebate_oferta (calcular_markups function)

Strategy: source-inspection tests. The scripts are not designed as importable modules
with testable helper functions (they contain top-level __main__ guards and side-effectful
imports). Source-inspection is the established pattern for this type of module
(see test_produtos_listing_envio.py for precedent).

Assertions:
  1. resolver_costos_envio_batch is imported in each script.
  2. envio_real_by_item is used in each script.
"""

from __future__ import annotations

import importlib
import inspect


def _load_script_source(dotted_name: str) -> str:
    """Load and return the full source of a script module."""
    mod = importlib.import_module(dotted_name)
    return inspect.getsource(mod)


class TestRecalcularMarkupsPricingScriptUsesResolver:
    """recalcular_markups_pricing.py must use the batch resolver."""

    def test_imports_resolver_costos_envio_batch(self):
        import app.scripts.recalcular_markups_pricing as mod

        assert hasattr(mod, "resolver_costos_envio_batch"), (
            "resolver_costos_envio_batch must be imported in recalcular_markups_pricing"
        )

    def test_envio_real_by_item_in_source(self):
        src = _load_script_source("app.scripts.recalcular_markups_pricing")
        assert "envio_real_by_item" in src, (
            "envio_real_by_item not found in recalcular_markups_pricing — batch resolver not used"
        )


class TestCalcularMarkupsRebateOfertaScriptUsesResolver:
    """calcular_markups_rebate_oferta.py must use the batch resolver."""

    def test_imports_resolver_costos_envio_batch(self):
        import app.scripts.calcular_markups_rebate_oferta as mod

        assert hasattr(mod, "resolver_costos_envio_batch"), (
            "resolver_costos_envio_batch must be imported in calcular_markups_rebate_oferta"
        )

    def test_envio_real_by_item_in_source(self):
        src = _load_script_source("app.scripts.calcular_markups_rebate_oferta")
        assert "envio_real_by_item" in src, (
            "envio_real_by_item not found in calcular_markups_rebate_oferta — batch resolver not used"
        )
