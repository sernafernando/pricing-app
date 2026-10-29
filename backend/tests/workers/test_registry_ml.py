"""`ML_PUBLICATIONS_REGISTRY` (design D1): a second explicit handler list for the separate
ML worker process. The existing `REGISTRY` must stay exactly as it was."""

from __future__ import annotations

from datetime import time, timedelta

from app.workers import registry
from app.workers.handlers import ml_ads, ml_billing, ml_publications
from app.workers.handlers.combos_sync import sync as combos_sync
from app.workers.handlers.ml_orders_quarantine import quarantine_retry
from app.workers.handlers.order_metrics import divergence, drain, reconcile
from app.workers.handlers.para_ganar_consulta import para_ganar_consulta
from app.workers.handlers.promo_refresh import promo_write_refresh
from app.workers.handlers.rrhh_horas_extras import horas_extras
from app.workers.handlers.sell_drain import drain as sell_drain
from app.workers.handlers.sell_in_bono import bono as sell_in_bono
from app.workers.handlers.sell_out_drain import drain as sell_out_drain
from app.workers.handlers.tp_cost_fill import fill as tp_cost_fill


class TestExistingRegistryIsUntouched:
    def test_main_registry_handlers(self) -> None:
        assert registry.REGISTRY == [
            drain,
            reconcile,
            divergence,
            tp_cost_fill,
            sell_drain,
            combos_sync,
            horas_extras,
            quarantine_retry,
            sell_in_bono,
            sell_out_drain,
        ]
        assert [h.name for h in registry.REGISTRY] == [
            "order_metrics.drain",
            "order_metrics.reconcile",
            "order_metrics.divergence",
            "tp_cost.fill",
            "sell.drain",
            "combos.sync",
            "rrhh.horas_extras",
            "ml_orders.quarantine_retry",
            "sell_in.bono",
            "sell_out.drain",
        ]

    def test_no_ml_publications_handler_leaks_into_the_default_registry(self) -> None:
        assert not [h for h in registry.REGISTRY if h.name.startswith("ml_publications.")]


class TestMlPublicationsRegistry:
    def test_contains_the_ml_handlers_in_that_order(self) -> None:
        assert [h.name for h in registry.ML_PUBLICATIONS_REGISTRY] == [
            "ml_publications.refresh",
            "ml_publications.intake",
            "ml_publications.relink",
            "ml_publications.scan",
            "ml_publications.missed_feeds",
            "ml_publications.sweep",
            "ml_publications.verify",
            "ml_publications.promo_refresh",
            "ml_ads.ingest",
            "promo_write.refresh",
            "ml_publications.freshness",
            "ml_billing.sweep",
            "para_ganar.consulta",
        ]
        assert registry.ML_PUBLICATIONS_REGISTRY[0] is ml_publications.refresh
        assert registry.ML_PUBLICATIONS_REGISTRY[1] is ml_publications.intake
        assert registry.ML_PUBLICATIONS_REGISTRY[2] is ml_publications.relink
        assert registry.ML_PUBLICATIONS_REGISTRY[3] is ml_publications.scan
        assert registry.ML_PUBLICATIONS_REGISTRY[4] is ml_publications.missed_feeds
        assert registry.ML_PUBLICATIONS_REGISTRY[5] is ml_publications.sweep
        assert registry.ML_PUBLICATIONS_REGISTRY[6] is ml_publications.verify
        assert registry.ML_PUBLICATIONS_REGISTRY[7].name == "ml_publications.promo_refresh"
        assert registry.ML_PUBLICATIONS_REGISTRY[8] is ml_ads.ads
        assert registry.ML_PUBLICATIONS_REGISTRY[9] is promo_write_refresh
        assert registry.ML_PUBLICATIONS_REGISTRY[10] is ml_publications.freshness
        assert registry.ML_PUBLICATIONS_REGISTRY[11] is ml_billing.billing
        assert registry.ML_PUBLICATIONS_REGISTRY[12] is para_ganar_consulta

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

    def test_verify_runs_daily_at_five_with_a_two_minute_catch_up_and_is_not_notify_driven(self) -> None:
        handler = registry.ML_PUBLICATIONS_REGISTRY[6]
        assert handler.run_at_local == time(5, 0) and handler.interval is None
        assert handler.catch_up_interval == timedelta(minutes=2)
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
            "'ml_publications.scan', 'ml_publications.missed_feeds', 'ml_publications.sweep', "
            "'ml_publications.verify', 'ml_publications.promo_refresh', 'ml_ads.ingest', 'promo_write.refresh', "
            "'ml_publications.freshness', 'ml_billing.sweep', 'para_ganar.consulta'] True"
        )
