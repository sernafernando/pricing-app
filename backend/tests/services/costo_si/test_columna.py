"""The costo SI column shown next to the list cost (sell-in-costo-si T3 PR 2, inventory §10, C4 pattern): its payload,
the cost in its own currency and in pesos. No markups of its own: the main markups are already over costo SI in pesos
(S13, #2363), so T3 PR 3 dropped the copy. Display only: no number elsewhere moves.
Spec: handoffs/sell-in-costo-si-feature.md S10, S13 (show); plan handoffs/sell-in-costo-si-t3-inventario.md §10 PR 2.
Invented data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.schemas.costo_si import CostoSiPayload
from app.services.costo_si import columna
from app.services.costo_si.lote import FUENTE_COSTO_SI, FUENTE_LISTA, Costo
from app.services.productos_sell_in_out import MarkupCompanions

D = Decimal
USD_SI = Costo(1, D("10.5"), "USD", FUENTE_COSTO_SI, date(2026, 10, 1), D("1000"), D("10500"), date(2026, 11, 2))


def test_the_payload_carries_the_cost_in_its_currency_its_source_and_pesos() -> None:
    assert columna.payload(USD_SI) == CostoSiPayload(
        costo=10.5,
        moneda="USD",
        fuente="costo_si",
        desde=date(2026, 10, 1),
        tipo_cambio=1000.0,
        tipo_cambio_fecha=date(2026, 11, 2),
        costo_ars=10500.0,
    )


def test_the_payload_dates_its_rate_and_carries_no_markups() -> None:
    """The rate's own date travels with it (the reader's `tipo_cambio_fecha`); the main markups are the one source."""
    dumped = columna.payload(USD_SI).model_dump()

    assert dumped["tipo_cambio_fecha"] == date(2026, 11, 2)
    assert "markups" not in dumped


def test_a_list_cost_shows_with_its_source() -> None:
    """Q1: no costo SI = the list cost, marked 'lista'; still one cost everywhere."""
    assert columna.payload(Costo(2, D("20000"), "ARS", FUENTE_LISTA, None, None, D("20000"))) == CostoSiPayload(
        costo=20000.0, moneda="ARS", fuente="lista", costo_ars=20000.0
    )


def test_an_unknown_cost_has_no_payload() -> None:
    assert columna.payload(None) is None
    assert columna.payload(Costo(3, None, None, None, None, None, None)) is None


def test_without_pesos_the_cost_shows_and_its_pesos_stay_unknown() -> None:
    """A USD cost with no rate: the USD figure shows, its pesos don't (never USD passed off as pesos, never 0)."""
    assert columna.payload(Costo(4, D("10"), "USD", FUENTE_COSTO_SI, date(2026, 10, 1), None, None)) == CostoSiPayload(
        costo=10.0, moneda="USD", fuente="costo_si", desde=date(2026, 10, 1)
    )


def test_the_companions_record_each_site_into_the_ppp_and_the_sell_in_out() -> None:
    class _Acc:
        def __init__(self) -> None:
            self.got = []

        def record(self, key, limpio, *, percent=True):
            self.got.append((key, limpio, percent))

    ppp, siso = _Acc(), _Acc()
    MarkupCompanions(ppp, siso).record("rebate", 13125.0, percent=False)

    assert ppp.got == siso.got == [("rebate", 13125.0, False)]
