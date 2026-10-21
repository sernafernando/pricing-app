"""Sell-out allocation against real tables (T7 S2): which sales a campaign
reaches (`alcance`) and the rebuild of its `sell_out_consumos` (`asignacion`).

Postgres only: the rebuild takes a per-campaign advisory lock. Runs in a
throwaway schema (`_world`).
"""

from __future__ import annotations

import threading
import time
from datetime import date
from decimal import Decimal
from typing import Iterator, List

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import sessionmaker

from app.services.sell_out import alcance, asignacion
from app.services.sell_out.asignacion import SellOutAsignacionError, recalcular
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

D = date
TP_ROUTERS = {"marca": "TP-LINK", "categoria": "Routers"}


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_out_asig") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _recalcular(engine: Engine, *ids: int):
    with sessionmaker(bind=engine)() as db:
        result = recalcular(db, ids)
        db.commit()
    return result


def _filas(engine: Engine, campana_id: int) -> List[tuple]:
    """`(canal, venta_ref, unidades, monto)` of one campaign, in sale order."""
    return [(r[1], r[2], r[5], r[6]) for r in w.consumos(engine, campana_id)]


class TestAlcance:
    def test_filters_and_within_a_row_and_or_across_rows_and_groups(self, engine: Engine) -> None:
        routers = w.grupo(engine, [TP_ROUTERS])
        otros = w.grupo(engine, [{"item_id": 950}, {"subcategoria_id": 12, "marca": "TP-LINK"}])
        campana = w.campana(engine, [routers, otros])
        ajena = w.campana(engine, [routers])

        with sessionmaker(bind=engine)() as db:
            productos = alcance.productos(db, [campana])

        assert productos == {campana: {2964: Decimal("21.0"), 950: Decimal("21.0"), 2270: Decimal("10.5")}}
        assert ajena not in productos

    def test_a_filter_row_with_nothing_set_reaches_nothing(self, engine: Engine) -> None:
        vacio = w.grupo(engine, [{"marca": "", "categoria": None, "subcategoria_id": 0}])
        campana = w.campana(engine, [vacio])

        with sessionmaker(bind=engine)() as db:
            assert alcance.productos(db, [campana]) == {}


class TestAsignacion:
    def test_sales_of_every_channel_in_scope_and_dates_take_the_credit(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])])
        ml = w.venta(engine, "ml", 2964, 2, D(2026, 11, 2))
        fuera = w.venta(engine, "fuera", 2964, 1, D(2026, 11, 3))
        tn = w.venta(engine, "tn", 2964, 3, D(2026, 11, 30))
        w.venta(engine, "fuera", 2964, 5, D(2026, 10, 31))  # before the campaign
        w.venta(engine, "ml", 2964, 5, D(2026, 12, 1))  # after it
        w.venta(engine, "ml", 2270, 5, D(2026, 11, 2))  # a switch: not in the group

        result = _recalcular(engine, campana)

        assert w.consumos(engine) == [
            (campana, "ml", ml, 2964, D(2026, 11, 2), 2, Decimal("20.00"), None),
            (campana, "fuera", fuera, 2964, D(2026, 11, 3), 1, Decimal("10.00"), None),
            (campana, "tn", tn, 2964, D(2026, 11, 30), 3, Decimal("30.00"), None),
        ]
        assert (result.campanas, result.inserted, result.deleted) == (1, 3, 0)

    def test_one_cap_for_every_product_and_channel_in_sale_date_order(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [{"marca": "TP-LINK"}])], tope_unidades=4)
        tarde = w.venta(engine, "ml", 2964, 3, D(2026, 11, 5))
        switch = w.venta(engine, "fuera", 2270, 2, D(2026, 11, 3))
        _recalcular(engine, campana)
        assert _filas(engine, campana) == [("fuera", switch, 2, Decimal("20.00")), ("ml", tarde, 2, Decimal("20.00"))]

        # A late sale dated earlier displaces the later one from the cap.
        temprana = w.venta(engine, "tn", 2964, 1, D(2026, 11, 1))
        _recalcular(engine, campana)

        assert _filas(engine, campana) == [
            ("tn", temprana, 1, Decimal("10.00")),
            ("fuera", switch, 2, Decimal("20.00")),
            ("ml", tarde, 1, Decimal("10.00")),
        ]

    def test_a_rerun_writes_nothing(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])], tope_unidades=3)
        w.venta(engine, "ml", 2964, 2, D(2026, 11, 2))
        w.venta(engine, "fuera", 2964, 2, D(2026, 11, 3))
        _recalcular(engine, campana)
        ids = w.consumo_ids(engine)

        result = _recalcular(engine, campana)

        assert (result.inserted, result.deleted) == (0, 0)
        assert w.consumo_ids(engine) == ids

    def test_a_deleted_sale_frees_its_units_for_the_next_one(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])], tope_unidades=2)
        cancelada = w.venta(engine, "ml", 2964, 2, D(2026, 11, 2))
        siguiente = w.venta(engine, "ml", 2964, 2, D(2026, 11, 3))
        _recalcular(engine, campana)
        w.delete_venta(engine, "ml", cancelada)

        result = _recalcular(engine, campana)

        assert _filas(engine, campana) == [("ml", siguiente, 2, Decimal("20.00"))]
        assert (result.inserted, result.deleted) == (1, 1)

    def test_a_return_after_the_campaign_ends_counts_as_a_sale(self, engine: Engine) -> None:
        """Owner 2026-10-21: "si el producto se devuelve después del cierre de la campaña computa como venta"."""
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])], tope_unidades=2)
        vendida = w.venta(engine, "fuera", 2964, 2, D(2026, 11, 2), cliente=55)
        w.venta(engine, "fuera", 2964, 1, D(2026, 11, 3), signo=-1, cliente=55)
        siguiente = w.venta(engine, "ml", 2964, 3, D(2026, 11, 4))
        w.venta(engine, "fuera", 2964, 1, D(2026, 12, 1), signo=-1, cliente=55)  # the day after the end

        _recalcular(engine, campana)

        # The return inside the window frees 1 for the next sale; the late one keeps the credit.
        assert _filas(engine, campana) == [
            ("fuera", vendida, 1, Decimal("10.00")),
            ("ml", siguiente, 1, Decimal("10.00")),
        ]

    def test_a_return_after_one_campaign_but_inside_a_linked_one_frees_only_the_linked_one(
        self, engine: Engine
    ) -> None:
        routers = w.grupo(engine, [TP_ROUTERS])
        noviembre = w.campana(engine, [routers])
        larga = w.campana(engine, [routers], hasta=D(2026, 12, 31), monto_unit="1.00")
        vendida = w.venta(engine, "fuera", 2964, 2, D(2026, 11, 2), cliente=55)
        w.venta(engine, "fuera", 2964, 2, D(2026, 12, 1), signo=-1, cliente=55)

        _recalcular(engine, noviembre)

        assert _filas(engine, noviembre) == [("fuera", vendida, 2, Decimal("20.00"))]
        assert _filas(engine, larga) == []

    def test_a_return_on_the_last_day_of_the_campaign_frees_its_units(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])])
        w.venta(engine, "fuera", 2964, 2, D(2026, 11, 2), cliente=55)
        w.venta(engine, "fuera", 2964, 2, D(2026, 11, 30), signo=-1, cliente=55)

        _recalcular(engine, campana)

        assert _filas(engine, campana) == []

    def test_a_return_of_a_sale_before_the_campaign_takes_no_credit_from_another_sale(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])], tope_unidades=2)
        w.venta(engine, "fuera", 2964, 1, D(2026, 10, 30), cliente=55)  # before the campaign
        ajena = w.venta(engine, "fuera", 2964, 2, D(2026, 11, 2), cliente=99)
        w.venta(engine, "fuera", 2964, 1, D(2026, 11, 3), signo=-1, cliente=55)  # returns the October sale
        tarde = w.venta(engine, "ml", 2964, 1, D(2026, 11, 4))

        _recalcular(engine, campana)

        assert _filas(engine, campana) == [("fuera", ajena, 2, Decimal("20.00"))]
        assert tarde not in [f[1] for f in _filas(engine, campana)]

    def test_an_unlinked_return_still_frees_the_latest_earlier_sale(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])])
        a = w.venta(engine, "fuera", 2964, 2, D(2026, 11, 2), cliente=55)
        b = w.venta(engine, "fuera", 2964, 2, D(2026, 11, 3), cliente=55)
        w.venta(engine, "fuera", 2964, 1, D(2026, 11, 4), signo=-1, cliente=55)  # two candidates: not linked

        _recalcular(engine, campana)

        assert _filas(engine, campana) == [("fuera", a, 2, Decimal("20.00")), ("fuera", b, 1, Decimal("10.00"))]

    def test_an_amount_with_vat_is_applied_net_of_each_product_own_vat(self, engine: Engine) -> None:
        campana = w.campana(
            engine, [w.grupo(engine, [{"marca": "TP-LINK"}])], monto_unit="121.00", monto_incluye_iva=True
        )
        router = w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
        switch = w.venta(engine, "ml", 2270, 2, D(2026, 11, 2))

        _recalcular(engine, campana)

        assert _filas(engine, campana) == [("ml", router, 1, Decimal("100.00")), ("ml", switch, 2, Decimal("219.00"))]

    def test_a_voided_campaign_loses_its_rows(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])])
        w.venta(engine, "ml", 2964, 2, D(2026, 11, 2))
        _recalcular(engine, campana)
        w.execute(engine, "UPDATE sell_out_campanas SET estado = 'anulada' WHERE id = :c", c=campana)

        result = _recalcular(engine, campana)

        assert w.consumos(engine) == []
        assert result.deleted == 1


class TestTipoDeCambio:
    def test_a_sale_day_row_carries_its_day_bna_and_follows_a_correction(self, engine: Engine) -> None:
        w.tipo_cambio(engine, D(2026, 10, 30), 1400)
        w.tipo_cambio(engine, D(2026, 11, 3), 1450.5)
        w.tipo_cambio(engine, D(2026, 11, 3), 99999, moneda="EUR")
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])], moneda="USD", tc_modo="dia_venta")
        lunes = w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
        martes = w.venta(engine, "ml", 2964, 1, D(2026, 11, 3))

        _recalcular(engine, campana)
        assert [(r[2], r[7]) for r in w.consumos(engine)] == [(lunes, Decimal("1400")), (martes, Decimal("1450.5"))]

        # A corrected rate is a change: the rows take it (owner: dynamic follows BNA).
        w.execute(engine, "UPDATE tipo_cambio SET venta = 1 WHERE moneda = 'USD'")
        assert _recalcular(engine, campana).inserted == 2
        assert [r[7] for r in w.consumos(engine)] == [Decimal("1"), Decimal("1")]
        assert _recalcular(engine, campana).inserted == 0  # and then it is stable

    def test_a_sale_day_row_written_before_its_day_rate_takes_it_when_it_arrives(self, engine: Engine) -> None:
        w.tipo_cambio(engine, D(2026, 11, 1), 500)
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])], moneda="USD", tc_modo="dia_venta")
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 3))
        _recalcular(engine, campana)
        assert [r[7] for r in w.consumos(engine)] == [Decimal("500")]  # the latest on or before its day

        w.tipo_cambio(engine, D(2026, 11, 3), 1000)  # the sale day's BNA is published later
        _recalcular(engine, campana)

        assert [r[7] for r in w.consumos(engine)] == [Decimal("1000")]

    def test_an_al_cobro_row_follows_the_latest_bna_until_the_rate_is_set_then_takes_it(self, engine: Engine) -> None:
        w.tipo_cambio(engine, D(2026, 11, 1), 500)
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])], moneda="USD", tc_modo="al_cobro")
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
        _recalcular(engine, campana)
        assert [(r[6], r[7]) for r in w.consumos(engine)] == [(Decimal("10.00"), Decimal("500"))]

        w.tipo_cambio(engine, D(2026, 11, 25), 2000)  # a newer BNA, after the sale day
        _recalcular(engine, campana)
        assert [(r[6], r[7]) for r in w.consumos(engine)] == [(Decimal("10.00"), Decimal("2000"))]

        w.execute(
            engine, "UPDATE sell_out_campanas SET tipo_cambio = 4000, tc_definido_en = now() WHERE id = :c", c=campana
        )
        _recalcular(engine, campana)
        assert [r[7] for r in w.consumos(engine)] == [Decimal("4000")]

    def test_a_rate_with_more_decimals_than_stored_does_not_rewrite_the_row_every_time(self, engine: Engine) -> None:
        w.tipo_cambio(engine, D(2026, 11, 1), 1450.1234567)
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])], moneda="USD", tc_modo="dia_venta")
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
        _recalcular(engine, campana)

        assert (_recalcular(engine, campana).inserted, _recalcular(engine, campana).deleted) == (0, 0)

    def test_a_sale_day_campaign_without_a_rate_is_refused(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])], moneda="USD", tc_modo="dia_venta")
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))

        with pytest.raises(SellOutAsignacionError):
            _recalcular(engine, campana)

    @pytest.mark.parametrize("tc_modo", ["fijo", "al_cobro"])
    def test_a_usd_row_without_a_bna_rate_is_refused_whatever_the_mode(self, engine: Engine, tc_modo: str) -> None:
        tc = {"tipo_cambio": "1000"} if tc_modo == "fijo" else {}
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])], moneda="USD", tc_modo=tc_modo, **tc)
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))

        with pytest.raises(SellOutAsignacionError):
            _recalcular(engine, campana)


def _ml(engine: Engine, item: int, qty: int, dia: date, gross: str, mcosto: str) -> int:
    ref = w.venta(engine, "ml", item, qty, dia)
    w.execute(
        engine, "UPDATE ml_sale_lines SET gross = :g, mcosto = :c WHERE item_row_id = :r", g=gross, c=mcosto, r=ref
    )
    return ref


def _fuera(engine: Engine, item: int, qty: int, dia: date, monto: str, costo: str) -> int:
    ref = w.venta(engine, "fuera", item, qty, dia)
    w.execute(
        engine,
        "UPDATE ventas_fuera_ml_metricas SET monto_total = :m, costo_total = :c WHERE it_transaction = :r",
        m=monto,
        c=costo,
        r=ref,
    )
    return ref


def _porcentaje(engine: Engine, base: str, **values) -> int:
    grupo = w.grupo(engine, [{"marca": "TP-LINK"}])
    return w.campana(
        engine, [grupo], tipo="porcentaje", monto_unit=None, porcentaje="10", base_porcentaje=base, **values
    )


class TestPorcentaje:
    """A percentage of a base per unit without VAT (owner 2026-10-20): the cost recorded on the sale
    (`costo`) or its net price (`precio_neto`), converted with the campaign's own `tc_modo`."""

    def test_cost_base_in_pesos_is_the_cost_recorded_on_each_sale(self, engine: Engine) -> None:
        campana = _porcentaje(engine, "costo")
        fuera = _fuera(engine, 2964, 2, D(2026, 11, 2), monto="9999.00", costo="1000.00")
        ml = _ml(engine, 2270, 2, D(2026, 11, 3), gross="9999", mcosto="30")

        _recalcular(engine, campana)

        assert _filas(engine, campana) == [("fuera", fuera, 2, Decimal("100.00")), ("ml", ml, 2, Decimal("3.00"))]

    def test_net_price_base_strips_vat_from_ml_and_takes_the_net_amount_elsewhere(self, engine: Engine) -> None:
        campana = _porcentaje(engine, "precio_neto")
        fuera = _fuera(engine, 2964, 2, D(2026, 11, 2), monto="2000.00", costo="1.00")
        router = _ml(engine, 2964, 2, D(2026, 11, 3), gross="242", mcosto="1")  # VAT 21
        switch = _ml(engine, 2270, 1, D(2026, 11, 4), gross="221", mcosto="1")  # VAT 10.5

        _recalcular(engine, campana)

        assert _filas(engine, campana) == [
            ("fuera", fuera, 2, Decimal("200.00")),
            ("ml", router, 2, Decimal("20.00")),
            ("ml", switch, 1, Decimal("20.00")),
        ]

    def test_usd_fixed_rate_converts_at_the_campaign_rate(self, engine: Engine) -> None:
        w.tipo_cambio(engine, D(2026, 11, 1), 500)
        campana = _porcentaje(engine, "costo", moneda="USD", tc_modo="fijo", tipo_cambio="1000")
        ref = _fuera(engine, 2964, 2, D(2026, 11, 2), monto="1.00", costo="20000.00")

        _recalcular(engine, campana)

        assert [(r[2], r[6], r[7]) for r in w.consumos(engine)] == [(ref, Decimal("2.00"), Decimal("500"))]

    def test_usd_sale_day_converts_at_each_sale_day_bna(self, engine: Engine) -> None:
        w.tipo_cambio(engine, D(2026, 11, 1), 500)
        w.tipo_cambio(engine, D(2026, 11, 3), 1000)
        campana = _porcentaje(engine, "precio_neto", moneda="USD", tc_modo="dia_venta")
        a = _fuera(engine, 2964, 1, D(2026, 11, 2), monto="10000.00", costo="1.00")
        b = _fuera(engine, 2964, 1, D(2026, 11, 3), monto="10000.00", costo="1.00")

        _recalcular(engine, campana)

        assert _filas(engine, campana) == [("fuera", a, 1, Decimal("2.00")), ("fuera", b, 1, Decimal("1.00"))]

    def test_usd_al_cobro_follows_the_latest_bna_until_its_rate_is_set(self, engine: Engine) -> None:
        w.tipo_cambio(engine, D(2026, 11, 1), 500)
        w.tipo_cambio(engine, D(2026, 11, 20), 1000)
        campana = _porcentaje(engine, "costo", moneda="USD", tc_modo="al_cobro")
        ref = _fuera(engine, 2964, 1, D(2026, 11, 2), monto="1.00", costo="20000.00")
        _recalcular(engine, campana)
        assert _filas(engine, campana) == [("fuera", ref, 1, Decimal("2.00"))]

        w.tipo_cambio(engine, D(2026, 11, 25), 2000)  # BNA moves: the estimate moves with it
        _recalcular(engine, campana)
        assert _filas(engine, campana) == [("fuera", ref, 1, Decimal("1.00"))]

        w.execute(
            engine,
            "UPDATE sell_out_campanas SET tipo_cambio = 4000, tc_definido_en = now() WHERE id = :c",
            c=campana,
        )
        _recalcular(engine, campana)
        assert [(r[6], r[7]) for r in w.consumos(engine)] == [(Decimal("0.50"), Decimal("4000"))]

    def test_the_money_cap_applies_to_the_percentage_amounts(self, engine: Engine) -> None:
        campana = _porcentaje(engine, "costo", tope_monto="150.00")
        a = _fuera(engine, 2964, 1, D(2026, 11, 2), monto="1.00", costo="1000.00")
        b = _fuera(engine, 2964, 1, D(2026, 11, 3), monto="1.00", costo="1000.00")

        _recalcular(engine, campana)

        assert _filas(engine, campana) == [("fuera", a, 1, Decimal("100.00")), ("fuera", b, 1, Decimal("50.00"))]

    @pytest.mark.parametrize("base", ["costo", "precio_neto"])
    def test_an_unsettled_ml_sale_waits_without_holding_units(self, engine: Engine, base: str) -> None:
        """An unsettled ML order (no gross, no cost) is skipped and counted, not a failure: it holds no
        units, so the cap goes to the next sale until it settles and the campaign is rebuilt."""
        campana = _porcentaje(engine, base, tope_unidades=1)
        _ml(engine, 2964, 1, D(2026, 11, 2), gross="0", mcosto="0")
        _ml(engine, 2964, 2, D(2026, 11, 2), gross="0", mcosto="0")
        ref = _fuera(engine, 2964, 1, D(2026, 11, 3), monto="1000.00", costo="1000.00")

        result = _recalcular(engine, campana)

        assert _filas(engine, campana) == [("fuera", ref, 1, Decimal("100.00"))]
        assert result.pendientes_base == {campana: 2}

    def test_a_return_of_a_sale_waiting_for_its_base_takes_no_credit_from_another_sale(self, engine: Engine) -> None:
        campana = _porcentaje(engine, "costo")
        sin_costo = w.venta(engine, "fuera", 2964, 1, D(2026, 11, 2), cliente=55)
        w.execute(
            engine, "UPDATE ventas_fuera_ml_metricas SET costo_total = NULL WHERE it_transaction = :r", r=sin_costo
        )
        ajena = _fuera(engine, 2964, 1, D(2026, 11, 2), monto="1.00", costo="1000.00")  # another customer
        w.execute(engine, "UPDATE ventas_fuera_ml_metricas SET cust_id = 99 WHERE it_transaction = :r", r=ajena)
        w.venta(engine, "fuera", 2964, 1, D(2026, 11, 3), signo=-1, cliente=55)  # returns the waiting sale

        result = _recalcular(engine, campana)

        assert _filas(engine, campana) == [("fuera", ajena, 1, Decimal("100.00"))]
        assert result.pendientes_base == {campana: 1}

    def test_a_sale_without_its_cost_waits_on_a_cost_base(self, engine: Engine) -> None:
        campana = _porcentaje(engine, "costo")
        sin_costo = w.venta(engine, "fuera", 2964, 1, D(2026, 11, 2))
        w.execute(
            engine, "UPDATE ventas_fuera_ml_metricas SET costo_total = NULL WHERE it_transaction = :r", r=sin_costo
        )

        result = _recalcular(engine, campana)

        assert (w.consumos(engine), result.pendientes_base) == ([], {campana: 1})


class TestPorcentajeSinIva:
    @pytest.fixture()
    def sin_iva(self, engine: Engine) -> Iterator[None]:
        w.execute(engine, "UPDATE productos_erp SET iva = NULL WHERE item_id = 2964")
        yield
        w.execute(engine, "UPDATE productos_erp SET iva = 21 WHERE item_id = 2964")

    def test_an_ml_net_price_of_a_product_without_vat_rate_fails(self, engine: Engine, sin_iva: None) -> None:
        campana = _porcentaje(engine, "precio_neto")
        _ml(engine, 2964, 1, D(2026, 11, 2), gross="121", mcosto="1")

        with pytest.raises(SellOutAsignacionError):
            _recalcular(engine, campana)


class TestExclusividad:
    def test_a_non_stackable_campaign_takes_precedence_by_id_and_leaves_what_its_cap_does_not_take(
        self, engine: Engine
    ) -> None:
        routers = w.grupo(engine, [TP_ROUTERS])
        exclusiva = w.campana(engine, [routers], acumulable=False, tope_unidades=3)
        segunda = w.campana(engine, [routers], monto_unit="1.00")
        a = w.venta(engine, "ml", 2964, 2, D(2026, 11, 2))
        b = w.venta(engine, "ml", 2964, 2, D(2026, 11, 3))

        # Rebuilding only the second one also rebuilds the campaign it depends on.
        result = _recalcular(engine, segunda)

        assert _filas(engine, exclusiva) == [("ml", a, 2, Decimal("20.00")), ("ml", b, 1, Decimal("10.00"))]
        assert _filas(engine, segunda) == [("ml", b, 1, Decimal("1.00"))]
        assert result.campanas == 2

    def test_the_lower_id_takes_precedence_also_when_only_the_later_one_is_not_stackable(self, engine: Engine) -> None:
        routers = w.grupo(engine, [TP_ROUTERS])
        primera = w.campana(engine, [routers], tope_unidades=1)
        exclusiva = w.campana(engine, [routers], acumulable=False, monto_unit="1.00")
        ref = w.venta(engine, "ml", 2964, 3, D(2026, 11, 2))

        _recalcular(engine, exclusiva)

        assert _filas(engine, primera) == [("ml", ref, 1, Decimal("10.00"))]
        assert _filas(engine, exclusiva) == [("ml", ref, 2, Decimal("2.00"))]

    def test_campaigns_linked_through_shared_products_are_rebuilt_together_transitively(self, engine: Engine) -> None:
        routers = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])], acumulable=False)
        marca = w.campana(engine, [w.grupo(engine, [{"marca": "TP-LINK"}])])
        switches = w.campana(engine, [w.grupo(engine, [{"categoria": "Switches"}])], acumulable=False)
        w.campana(engine, [w.grupo(engine, [{"marca": "MERCUSYS"}])])  # shares nothing
        w.venta(engine, "ml", 2270, 1, D(2026, 11, 2))

        result = _recalcular(engine, routers)

        assert result.campanas == 3
        assert [(r[0], r[5]) for r in w.consumos(engine)] == [(marca, 1)]
        assert switches not in [r[0] for r in w.consumos(engine)]

    def test_stackable_campaigns_both_take_every_unit(self, engine: Engine) -> None:
        routers = w.grupo(engine, [TP_ROUTERS])
        una = w.campana(engine, [routers])
        otra = w.campana(engine, [routers], monto_unit="1.00")
        ref = w.venta(engine, "ml", 2964, 2, D(2026, 11, 2))

        _recalcular(engine, una, otra)

        assert _filas(engine, una) == [("ml", ref, 2, Decimal("20.00"))]
        assert _filas(engine, otra) == [("ml", ref, 2, Decimal("2.00"))]

    def test_a_return_gives_back_to_the_campaign_with_precedence_first(self, engine: Engine) -> None:
        routers = w.grupo(engine, [TP_ROUTERS])
        exclusiva = w.campana(engine, [routers], acumulable=False, tope_unidades=2)
        segunda = w.campana(engine, [routers], monto_unit="1.00")
        vendida = w.venta(engine, "fuera", 2964, 3, D(2026, 11, 2), cliente=55)
        w.venta(engine, "fuera", 2964, 3, D(2026, 11, 3), signo=-1, cliente=55)
        siguiente = w.venta(engine, "ml", 2964, 4, D(2026, 11, 4))

        _recalcular(engine, exclusiva)

        # The return frees 2 in the exclusive campaign and 1 in the second one: the next sale takes both.
        assert _filas(engine, exclusiva) == [("ml", siguiente, 2, Decimal("20.00"))]
        assert _filas(engine, segunda) == [("ml", siguiente, 2, Decimal("2.00"))]
        assert vendida not in [f[1] for f in _filas(engine, segunda)]

    def test_stackable_campaigns_before_an_exclusive_one_share_the_same_units(self, engine: Engine) -> None:
        routers = w.grupo(engine, [TP_ROUTERS])
        una = w.campana(engine, [routers], tope_unidades=1)
        otra = w.campana(engine, [routers], tope_unidades=1)
        exclusiva = w.campana(engine, [routers], acumulable=False, monto_unit="1.00")
        ref = w.venta(engine, "ml", 2964, 3, D(2026, 11, 2))

        _recalcular(engine, exclusiva)

        # `una` and `otra` stack: both credit the SAME unit, so 2 of the 3 are still free.
        assert [_filas(engine, c) for c in (una, otra)] == [[("ml", ref, 1, Decimal("10.00"))]] * 2
        assert _filas(engine, exclusiva) == [("ml", ref, 2, Decimal("2.00"))]

    def test_an_exclusive_and_a_stackable_campaign_before_it_hold_different_units(self, engine: Engine) -> None:
        routers = w.grupo(engine, [TP_ROUTERS])
        primera = w.campana(engine, [routers], acumulable=False, tope_unidades=1)
        segunda = w.campana(engine, [routers], tope_unidades=1)
        tercera = w.campana(engine, [routers], acumulable=False, monto_unit="1.00")
        ref = w.venta(engine, "ml", 2964, 3, D(2026, 11, 2))

        _recalcular(engine, tercera)

        assert _filas(engine, primera) == [("ml", ref, 1, Decimal("10.00"))]
        assert _filas(engine, segunda) == [("ml", ref, 1, Decimal("10.00"))]
        assert _filas(engine, tercera) == [("ml", ref, 1, Decimal("1.00"))]

    def test_voiding_the_exclusive_campaign_hands_its_units_to_the_other(self, engine: Engine) -> None:
        routers = w.grupo(engine, [TP_ROUTERS])
        exclusiva = w.campana(engine, [routers], acumulable=False)
        segunda = w.campana(engine, [routers], monto_unit="1.00")
        ref = w.venta(engine, "ml", 2964, 2, D(2026, 11, 2))
        _recalcular(engine, segunda)
        assert _filas(engine, segunda) == []
        w.execute(engine, "UPDATE sell_out_campanas SET estado = 'anulada' WHERE id = :c", c=exclusiva)

        _recalcular(engine, exclusiva)

        assert w.consumos(engine) == [(segunda, "ml", ref, 2964, D(2026, 11, 2), 2, Decimal("2.00"), None)]


class TestQueryCount:
    def test_the_reads_of_a_call_do_not_grow_with_its_campaigns_and_sales(self, engine: Engine) -> None:
        assert _selects(engine, 1) == _selects(engine, 4)


def _selects(engine: Engine, n: int) -> int:
    w.clean(engine)
    w.tipo_cambio(engine, D(2026, 10, 1), 1000)
    routers = w.grupo(engine, [TP_ROUTERS])
    ids = [w.campana(engine, [routers], moneda="USD", tc_modo="dia_venta", acumulable=i > 0) for i in range(n)]
    for i in range(n):
        for canal in ("ml", "fuera", "tn"):
            w.venta(engine, canal, 2964, 1, D(2026, 11, 1 + i))
        w.venta(engine, "fuera", 2964, 1, D(2026, 11, 2 + i), signo=-1)
    selects: List[str] = []

    def contar(conn, cursor, statement, parameters, context, executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(engine, "before_cursor_execute", contar)
    try:
        result = _recalcular(engine, *ids)
    finally:
        event.remove(engine, "before_cursor_execute", contar)
    assert result.inserted > 0
    return len(selects)


def _waiting_on_advisory_lock(engine: Engine) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = :ns AND NOT granted"),
                {"ns": asignacion.LOCK_NAMESPACE},
            ).scalar()
        )


class TestConcurrency:
    def test_two_rebuilds_of_one_campaign_serialize(self, engine: Engine) -> None:
        """The second rebuild waits on the campaign's advisory lock until the first commits,
        then reads its rows and writes nothing: no duplicate consumptions."""
        assert asignacion.LOCK_NAMESPACE not in (0x5E11, 0x5E12)  # sell-in costing and brand bonus
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])])
        w.venta(engine, "ml", 2964, 2, D(2026, 11, 2))
        Session_ = sessionmaker(bind=engine)
        primera = Session_()
        segunda: dict = {}

        def rebuild() -> None:
            with Session_() as db:
                try:
                    segunda["result"] = recalcular(db, [campana])
                    db.commit()
                except Exception as exc:  # noqa: BLE001 - surfaced by the assertion below
                    segunda["error"] = exc

        try:
            assert recalcular(primera, [campana]).inserted == 1  # holds the lock, uncommitted
            hilo = threading.Thread(target=rebuild)
            hilo.start()
            deadline = time.monotonic() + 10
            while not _waiting_on_advisory_lock(engine):
                assert time.monotonic() < deadline, "the second rebuild never waited on the lock"
                time.sleep(0.02)
            primera.commit()
        finally:
            primera.close()
        hilo.join(timeout=10)

        assert "error" not in segunda, segunda.get("error")
        assert (segunda["result"].inserted, segunda["result"].deleted) == (0, 0)
        assert len(w.consumos(engine)) == 1
