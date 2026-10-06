"""`ML_PUBLICATIONS_REGISTRY` (design D1): a second explicit handler list for the separate
ML worker process. The existing `REGISTRY` must stay exactly as it was."""

from __future__ import annotations

from datetime import timedelta

from app.workers import registry
from app.workers.handlers import ml_publications
from app.workers.handlers.order_metrics import divergence, drain, reconcile


class TestExistingRegistryIsUntouched:
    def test_default_registry_is_exactly_the_three_order_metrics_handlers(self) -> None:
        assert registry.REGISTRY == [drain, reconcile, divergence]
        assert [h.name for h in registry.REGISTRY] == [
            "order_metrics.drain",
            "order_metrics.reconcile",
            "order_metrics.divergence",
        ]

    def test_no_ml_publications_handler_leaks_into_the_default_registry(self) -> None:
        assert not [h for h in registry.REGISTRY if h.name.startswith("ml_publications.")]


class TestMlPublicationsRegistry:
    def test_contains_only_the_refresh_handler(self) -> None:
        assert [h.name for h in registry.ML_PUBLICATIONS_REGISTRY] == ["ml_publications.refresh"]
        assert registry.ML_PUBLICATIONS_REGISTRY[0] is ml_publications.refresh

    def test_refresh_runs_every_five_seconds_and_is_not_notify_driven(self) -> None:
        handler = registry.ML_PUBLICATIONS_REGISTRY[0]
        assert handler.interval == timedelta(seconds=5)
        assert handler.run_at_local is None
        assert handler.channels == ()
