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
    def test_contains_the_refresh_intake_relink_and_scan_handlers_in_that_order(self) -> None:
        assert [h.name for h in registry.ML_PUBLICATIONS_REGISTRY] == [
            "ml_publications.refresh",
            "ml_publications.intake",
            "ml_publications.relink",
            "ml_publications.scan",
        ]
        assert registry.ML_PUBLICATIONS_REGISTRY[0] is ml_publications.refresh
        assert registry.ML_PUBLICATIONS_REGISTRY[1] is ml_publications.intake
        assert registry.ML_PUBLICATIONS_REGISTRY[2] is ml_publications.relink
        assert registry.ML_PUBLICATIONS_REGISTRY[3] is ml_publications.scan

    def test_intake_runs_every_fifteen_seconds_and_is_not_notify_driven(self) -> None:
        handler = registry.ML_PUBLICATIONS_REGISTRY[1]
        assert handler.interval == timedelta(seconds=15)
        assert handler.run_at_local is None
        assert handler.channels == ()

    def test_refresh_runs_every_five_seconds_and_is_not_notify_driven(self) -> None:
        handler = registry.ML_PUBLICATIONS_REGISTRY[0]
        assert handler.interval == timedelta(seconds=5)
        assert handler.run_at_local is None
        assert handler.channels == ()


class TestProcessIsolation:
    """The sales worker must not load the ML module: an import failure there would take down
    `pricing-worker` too, against the point of running ML in its own process (design D1)."""

    @staticmethod
    def _run(code: str) -> str:
        import subprocess
        import sys

        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def test_importing_the_runtime_does_not_import_the_ml_handlers(self) -> None:
        code = (
            "import sys, app.workers.runtime, app.workers.registry; "
            "print('app.workers.handlers.ml_publications' in sys.modules, "
            "any(m.startswith('app.services.ml_publications') for m in sys.modules))"
        )
        assert self._run(code) == "False False"

    def test_the_ml_registry_loads_on_first_use_and_is_stable(self) -> None:
        code = (
            "import app.workers.registry as r; a = r.ML_PUBLICATIONS_REGISTRY; "
            "print([h.name for h in a], a is r.ML_PUBLICATIONS_REGISTRY)"
        )
        assert self._run(code) == (
            "['ml_publications.refresh', 'ml_publications.intake', 'ml_publications.relink', "
            "'ml_publications.scan'] True"
        )
