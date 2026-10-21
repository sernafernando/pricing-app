"""`asignacion._asignar` does not depend on the order the loader lists sales and returns in."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.sell_out import SellOutCampana
from app.services.sell_out.alcance import Venta
from app.services.sell_out.asignacion import _asignar, _Tasas


def test_a_linked_return_listed_before_its_sale_still_frees_it() -> None:
    campana = SellOutCampana(
        id=1,
        tipo="por_unidad",
        moneda="ARS",
        monto_unit=Decimal("10"),
        acumulable=True,
        monto_incluye_iva=False,
        fecha_desde=date(2026, 11, 1),
        fecha_hasta=date(2026, 11, 30),
    )
    venta = Venta("fuera", 1, 2964, date(2026, 11, 2), 2)
    devolucion = Venta("fuera", 2, 2964, date(2026, 11, 3), -1, objetivo=("fuera", 1))

    salida, _ = _asignar([campana], {1: {2964: Decimal(21)}}, [devolucion, venta], _Tasas({}, None))

    assert [(c.venta_ref, c.unidades) for c in salida[1]] == [(1, 1)]
