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

    def test_a_return_frees_units_for_later_sales_even_after_the_campaign(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])], tope_unidades=2)
        vendida = w.venta(engine, "fuera", 2964, 2, D(2026, 11, 2), cliente=55)
        w.venta(engine, "fuera", 2964, 1, D(2026, 11, 3), signo=-1, cliente=55)
        siguiente = w.venta(engine, "ml", 2964, 3, D(2026, 11, 4))
        w.venta(engine, "fuera", 2964, 1, D(2026, 12, 15), signo=-1, cliente=55)  # after the campaign

        _recalcular(engine, campana)

        # The first return frees 1 for the next sale; the late one takes the credit back from its own sale.
        assert _filas(engine, campana) == [("ml", siguiente, 1, Decimal("10.00"))]
        assert vendida not in [f[1] for f in _filas(engine, campana)]

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

    def test_a_percentage_campaign_is_refused_until_its_base_is_decided(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])], tipo="porcentaje", monto_unit=None, porcentaje="5")
        w.venta(engine, "ml", 2964, 2, D(2026, 11, 2))

        with pytest.raises(SellOutAsignacionError):
            _recalcular(engine, campana)


class TestTipoDeCambio:
    def test_a_usd_row_freezes_the_bna_rate_of_its_sale_day(self, engine: Engine) -> None:
        w.tipo_cambio(engine, D(2026, 10, 30), 1400)
        w.tipo_cambio(engine, D(2026, 11, 3), 1450.5)
        w.tipo_cambio(engine, D(2026, 11, 3), 99999, moneda="EUR")
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])], moneda="USD", tc_modo="dia_venta")
        lunes = w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
        martes = w.venta(engine, "ml", 2964, 1, D(2026, 11, 3))

        _recalcular(engine, campana)
        assert [(r[2], r[7]) for r in w.consumos(engine)] == [(lunes, Decimal("1400")), (martes, Decimal("1450.5"))]

        # Frozen: a corrected rate does not rewrite a row that did not change.
        w.execute(engine, "UPDATE tipo_cambio SET venta = 1 WHERE moneda = 'USD'")
        assert _recalcular(engine, campana).inserted == 0
        assert [r[7] for r in w.consumos(engine)] == [Decimal("1400"), Decimal("1450.5")]

    def test_a_sale_day_campaign_without_a_rate_is_refused(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])], moneda="USD", tc_modo="dia_venta")
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))

        with pytest.raises(SellOutAsignacionError):
            _recalcular(engine, campana)

    def test_an_al_cobro_row_without_a_rate_keeps_it_empty(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [TP_ROUTERS])], moneda="USD", tc_modo="al_cobro")
        ref = w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))

        _recalcular(engine, campana)

        assert [(r[2], r[7]) for r in w.consumos(engine)] == [(ref, None)]


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
