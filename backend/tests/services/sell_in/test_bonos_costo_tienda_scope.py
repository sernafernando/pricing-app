"""Cost-bonus allocator respects tactical store scope (same rules as sell-out)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.sell_in import SellInBonoMarca
from app.services.sell_in.bonos_costo import _componente
from app.services.sell_out.alcance import Venta
from app.services.sell_out.tienda_scope import Scope


def _bono(**kwargs) -> SellInBonoMarca:
    base = dict(
        id=1,
        base="costo_venta",
        tipo="porcentaje",
        moneda="ARS",
        alcance="marca",
        marca="TP-LINK",
        porcentaje=Decimal("10"),
        incluye_iva=False,
        acumulable=True,
        fecha_desde=date(2026, 11, 1),
        fecha_hasta=date(2026, 11, 30),
        tope_unidades=1,
        estado="activo",
    )
    base.update(kwargs)
    return SellInBonoMarca(**base)


def test_cost_bonus_skips_sales_outside_store_scope() -> None:
    bono = _bono()
    scope = Scope(
        todas_tiendas=False,
        tope_compartido=True,
        oficiales=frozenset({57997}),
        canales=frozenset(),
    )
    dentro = Venta("ml", 1, 2964, date(2026, 11, 2), 1, costo_unit=Decimal("100"), store_id=57997)
    fuera = Venta("ml", 2, 2964, date(2026, 11, 2), 1, costo_unit=Decimal("100"), store_id=2645)

    deseadas = _componente(
        [bono],
        {1: {2964}},
        {1: {}},
        {2964: Decimal(21)},
        [dentro, fuera],
        {},
        {},
        scopes={1: scope},
    )

    assert list(deseadas) == [(1, "ml", 1, 2964)]
    assert deseadas[(1, "ml", 1, 2964)][2] == 1


def test_cost_bonus_per_store_cap() -> None:
    bono = _bono(tope_unidades=1)
    scope = Scope(
        todas_tiendas=False,
        tope_compartido=False,
        oficiales=frozenset({57997, 2645}),
        canales=frozenset(),
    )
    a = Venta("ml", 1, 2964, date(2026, 11, 2), 1, costo_unit=Decimal("100"), store_id=57997)
    b = Venta("ml", 2, 2964, date(2026, 11, 2), 1, costo_unit=Decimal("100"), store_id=2645)

    deseadas = _componente(
        [bono],
        {1: {2964}},
        {1: {}},
        {2964: Decimal(21)},
        [a, b],
        {},
        {},
        scopes={1: scope},
    )

    assert sorted(deseadas) == [(1, "ml", 1, 2964), (1, "ml", 2, 2964)]
