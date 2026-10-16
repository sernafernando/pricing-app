"""R3-005: the tienda listing's prefetch keys its commission maps by
(version_id, grupo_id) and (version_id, cuotas). Its PricingContext keeps only
the active version's entries, so two versions sharing a grupo or a cuotas count
never collapse into one."""

from __future__ import annotations

from datetime import date

from app.api.endpoints.productos_listing import tienda_pricing_context


def test_keeps_only_the_active_versions_commissions() -> None:
    ctx = tienda_pricing_context(
        hoy=date(2026, 1, 1),
        tipo_cambio_usd=1000.0,
        constantes=None,
        subcat_to_grupo={100: 1},
        active_version_id=2,
        comision_base_map={(1, 1): 99.0, (2, 1): 12.5},
        comision_adicional_map={(2, 3): 3.0, (1, 3): 50.0},
        envio_promedio_by_grupo={1: 0.0},
    )

    assert dict(ctx.comision_base) == {1: 12.5}
    assert dict(ctx.comision_adicional) == {3: 3.0}
    assert ctx.comision(4, 1) == 12.5
    assert ctx.comision(17, 1) == 15.5


def test_without_an_active_version_there_is_no_commission() -> None:
    ctx = tienda_pricing_context(
        hoy=date(2026, 1, 1),
        tipo_cambio_usd=None,
        constantes=None,
        subcat_to_grupo={},
        active_version_id=None,
        comision_base_map={},
        comision_adicional_map={},
        envio_promedio_by_grupo={},
    )

    assert ctx.comision(4, 1) is None
