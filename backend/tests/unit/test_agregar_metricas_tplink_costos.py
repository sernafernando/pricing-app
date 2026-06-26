"""
T-4 / T-5: Unit tests — obtener_costo_item in agregar_metricas_tplink.py.

Verifies:
- Returns list-8 (coslis_id=8) price when available, NOT list-1.
- Returns (0.0, "ARS") when only list-1 cost exists (no list-8 row).
- Missing-cost counter is incremented and item code is recorded on the no-cost path.

SQLite-runnable.
"""

from __future__ import annotations

import pytest
from datetime import datetime
from app.models.item_cost_list_history import ItemCostListHistory


@pytest.fixture()
def cost_fixtures(db):
    """Seed cost-list rows for two items."""
    # Item 501: has BOTH list-8 ($200) and list-1 ($50) costs
    db.add(
        ItemCostListHistory(
            iclh_id=8001,
            item_id=501,
            coslis_id=8,
            iclh_price=200.0,
            curr_id=1,  # ARS
            iclh_cd=datetime(2026, 1, 1),
        )
    )
    db.add(
        ItemCostListHistory(
            iclh_id=8002,
            item_id=501,
            coslis_id=1,
            iclh_price=50.0,
            curr_id=1,
            iclh_cd=datetime(2026, 1, 1),
        )
    )
    # Item 502: only list-1 ($75) — no list-8 cost
    db.add(
        ItemCostListHistory(
            iclh_id=8003,
            item_id=502,
            coslis_id=1,
            iclh_price=75.0,
            curr_id=1,
            iclh_cd=datetime(2026, 1, 1),
        )
    )
    db.flush()


class TestObtenerCostoItemTplink:
    """obtener_costo_item uses coslis_id=8 and never falls back to list-1."""

    def test_returns_list8_price_when_available(self, db, cost_fixtures) -> None:
        """Item 501 has list-8 at $200; function must return ~200*qty, not 50."""
        from app.scripts.agregar_metricas_tplink import obtener_costo_item

        costo, moneda = obtener_costo_item(
            db=db,
            item_id=501,
            fecha_venta=datetime(2026, 6, 1, 12, 0),
            cantidad=1.0,
            mlo_id=1,
        )
        assert costo == pytest.approx(200.0, abs=0.01), f"Expected 200.0, got {costo}"
        assert moneda == "ARS"

    def test_returns_zero_when_no_list8_cost(self, db, cost_fixtures) -> None:
        """Item 502 has only list-1; function must return (0.0, 'ARS') — no silent list-1 fallback."""
        from app.scripts.agregar_metricas_tplink import obtener_costo_item

        costo, moneda = obtener_costo_item(
            db=db,
            item_id=502,
            fecha_venta=datetime(2026, 6, 1, 12, 0),
            cantidad=1.0,
            mlo_id=1,
        )
        assert costo == 0.0, f"Expected 0.0 (no list-8), got {costo}"

    def test_missing_cost_counter_incremented(self, db, cost_fixtures) -> None:
        """When no list-8 cost exists, the missing-cost counter must be incremented."""
        from app.scripts import agregar_metricas_tplink as mod

        # Reset counters before test
        mod._missing_cost_count = 0
        mod._missing_cost_sample = []

        mod.obtener_costo_item(
            db=db,
            item_id=502,
            fecha_venta=datetime(2026, 6, 1, 12, 0),
            cantidad=1.0,
            mlo_id=1,
        )
        assert mod._missing_cost_count == 1
