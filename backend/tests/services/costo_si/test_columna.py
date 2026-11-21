"""The costo SI column shown next to the list cost (sell-in-costo-si T3 PR 2, inventory §10, C4 pattern): its payload
and its markups, keyed like the main ones, each on the costo SI in pesos. Display only: no number elsewhere moves.
Spec: handoffs/sell-in-costo-si-feature.md S10, S13 (show); plan handoffs/sell-in-costo-si-t3-inventario.md §10 PR 2.
Invented data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.schemas.costo_si import CostoSiPayload
from app.services.costo_si import columna
from app.services.costo_si.lote import FUENTE_COSTO_SI, FUENTE_LISTA, Costo
from app.services.productos_sell_in_out import MarkupCompanions

D = Decimal
USD_SI = Costo(1, D("10.5"), "USD", FUENTE_COSTO_SI, date(2026, 10, 1), D("1000"), D("10500"))


def test_the_payload_carries_the_cost_in_its_currency_its_source_and_pesos() -> None:
    assert columna.CostoSiMarkups(USD_SI).payload() == CostoSiPayload(
        costo=10.5,
        moneda="USD",
        fuente="costo_si",
        desde=date(2026, 10, 1),
        tipo_cambio=1000.0,
        costo_ars=10500.0,
        markups={},
    )


def test_each_markup_is_on_the_costo_si_in_pesos_keyed_like_the_main_one() -> None:
    acc = columna.CostoSiMarkups(USD_SI)
    acc.record("clasica", 13125.0)
    acc.record("mejor_oferta", 12600.0, percent=False)

    assert acc.payload().markups == {"clasica": 25.0, "mejor_oferta": pytest.approx(0.2)}


def test_a_list_cost_shows_with_its_source_and_its_markups() -> None:
    """Q1: no costo SI = the list cost, marked 'lista'; still one cost everywhere."""
    acc = columna.CostoSiMarkups(Costo(2, D("20000"), "ARS", FUENTE_LISTA, None, None, D("20000")))
    acc.record("clasica", 25000.0)

    assert acc.payload() == CostoSiPayload(
        costo=20000.0, moneda="ARS", fuente="lista", costo_ars=20000.0, markups={"clasica": 25.0}
    )


def test_an_unknown_cost_has_no_payload_and_records_nothing() -> None:
    for costo in (None, Costo(3, None, None, None, None, None, None)):
        acc = columna.CostoSiMarkups(costo)
        acc.record("clasica", 100.0)
        assert acc.payload() is None


def test_without_pesos_the_cost_shows_but_no_markup_is_guessed() -> None:
    """A USD cost with no rate: the USD figure shows, its markups don't (never USD passed off as pesos)."""
    acc = columna.CostoSiMarkups(Costo(4, D("10"), "USD", FUENTE_COSTO_SI, date(2026, 10, 1), None, None))
    acc.record("clasica", 100.0)

    assert acc.payload() == CostoSiPayload(
        costo=10.0, moneda="USD", fuente="costo_si", desde=date(2026, 10, 1), markups={}
    )


def test_the_companions_record_each_site_into_the_costo_si_too() -> None:
    class _Acc:
        def __init__(self) -> None:
            self.got = []

        def record(self, key, limpio, *, percent=True):
            self.got.append((key, limpio, percent))

    ppp, siso = _Acc(), _Acc()
    costo_si = columna.CostoSiMarkups(USD_SI)
    MarkupCompanions(ppp, siso, costo_si).record("rebate", 13125.0, percent=False)

    assert ppp.got == siso.got == [("rebate", 13125.0, False)]
    assert costo_si.payload().markups == {"rebate": pytest.approx(0.25)}
    assert MarkupCompanions(ppp, siso).costo_si is None
