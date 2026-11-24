"""sell-in-costo-si T5 PR A, L24-L25: a sale-cost bonus is never applied per sale any more (costo SI holds the loyalty
through its invoices), so its worker only reconciles the purchases, and a lump-sum bonus is refused until PR E divides it on invoices."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.schemas.sell_in_bonos import SellInBonoIn
from app.services.sell_in import bonos_crud
from app.services.sell_in import bonos_costo
from app.workers.handlers import sell_in_bono


def test_the_bonus_worker_no_longer_applies_cost_bonuses_per_sale(monkeypatch: pytest.MonkeyPatch) -> None:
    llamados = []
    monkeypatch.setattr(sell_in_bono.tacticals, "aplicar_facturas_pendientes", lambda db, ids: None)
    monkeypatch.setattr(sell_in_bono.tacticals, "repartir_totales_de_factura", lambda db, ids: None)
    monkeypatch.setattr(sell_in_bono.bonos, "reconciliar", lambda db, **k: SimpleNamespace(fallidas={}))
    monkeypatch.setattr(bonos_costo, "recalcular", lambda *a, **k: llamados.append(a))
    monkeypatch.setattr(sell_in_bono.bono_queue, "settle", lambda db, ok, failed: [])

    _, failed, parked = sell_in_bono._reconciliar(None, [("bono", 7), ("pedido", 9)])

    assert (llamados, failed, parked) == ([], {}, [])


def test_a_lump_sum_bonus_is_refused_with_its_message(db) -> None:
    data = SellInBonoIn(
        base="costo_venta",
        alcance="marca",
        marca="TP-LINK",
        tipo="monto_total",
        monto_total=Decimal("100000"),
        reparto_criterio="unidades",
        moneda="ARS",
        fecha_desde=date(2026, 11, 1),
        fecha_hasta=date(2026, 11, 30),
    )

    with pytest.raises(bonos_crud.SellInBonoError) as exc:
        bonos_crud.validar(db, data)

    assert str(exc.value) == (
        "Un bono de sell in por monto total no se puede cargar por ahora: si es sobre las ventas, cargalo como sell out"
    )
