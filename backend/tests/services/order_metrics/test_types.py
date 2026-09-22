"""RED/GREEN -- `OrderMetrics` dataclass + `GaussStatus` enum invariants
(ventas-ml-rediseno PR1.T1, design D2, spec ml-order-stored-metrics R2).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.services.order_metrics.types import GaussStatus, OrderMetrics


def _kwargs(**overrides):
    base = dict(
        order_id=1,
        neto=Decimal("100.00"),
        neto_sin_iva=Decimal("82.64"),
        iva_reconcilia=True,
        costo_mercaderia=Decimal("40.00"),
        total_gauss=Decimal("42.64"),
        markup_pct=Decimal("106.60"),
        gauss_status=GaussStatus.OK,
        provisional_falta=None,
        unresolved_reason=None,
        formula_version=2,
        computed_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return base


class TestUnresolvedForcesNullDependents:
    def test_unresolved_with_total_gauss_none_is_valid(self) -> None:
        metrics = OrderMetrics(
            **_kwargs(
                gauss_status=GaussStatus.UNRESOLVED,
                total_gauss=None,
                markup_pct=None,
                unresolved_reason="costo_mercaderia",
            )
        )
        assert metrics.total_gauss is None
        assert metrics.markup_pct is None

    def test_unresolved_rejects_a_present_total_gauss(self) -> None:
        with pytest.raises(ValueError):
            OrderMetrics(**_kwargs(gauss_status=GaussStatus.UNRESOLVED, total_gauss=Decimal("1.00")))

    def test_unresolved_rejects_a_present_markup_pct(self) -> None:
        with pytest.raises(ValueError):
            OrderMetrics(
                **_kwargs(
                    gauss_status=GaussStatus.UNRESOLVED,
                    total_gauss=None,
                    markup_pct=Decimal("1.00"),
                )
            )


class TestNonUnresolvedRejectsNullTotalGauss:
    @pytest.mark.parametrize("status", [GaussStatus.OK, GaussStatus.PROVISIONAL])
    def test_rejects_null_total_gauss(self, status) -> None:
        with pytest.raises(ValueError):
            OrderMetrics(**_kwargs(gauss_status=status, total_gauss=None, markup_pct=None))


class TestMarkupPctNullWhenCostoUnknownOrZero:
    @pytest.mark.parametrize("status", [GaussStatus.OK, GaussStatus.PROVISIONAL])
    def test_costo_none_forces_markup_none(self, status) -> None:
        metrics = OrderMetrics(**_kwargs(gauss_status=status, costo_mercaderia=None, markup_pct=None))
        assert metrics.markup_pct is None

    @pytest.mark.parametrize("status", [GaussStatus.OK, GaussStatus.PROVISIONAL])
    def test_costo_zero_forces_markup_none(self, status) -> None:
        metrics = OrderMetrics(**_kwargs(gauss_status=status, costo_mercaderia=Decimal("0"), markup_pct=None))
        assert metrics.markup_pct is None

    def test_costo_none_with_markup_present_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            OrderMetrics(**_kwargs(costo_mercaderia=None, markup_pct=Decimal("1.00")))

    def test_costo_zero_with_markup_present_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            OrderMetrics(**_kwargs(costo_mercaderia=Decimal("0"), markup_pct=Decimal("1.00")))
