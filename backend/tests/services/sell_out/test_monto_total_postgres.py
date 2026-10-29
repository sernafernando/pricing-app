"""A `monto_total` campaign's rebuild against real tables (T26b, S34/S35): each product's manual share
spreads over that product's sales in the campaign's dates, by units, into `sell_out_consumos`.

Postgres only, in a throwaway schema (`_world`).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator, List

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import sessionmaker

from app.services.sell_out import tope
from app.services.sell_out.asignacion import SellOutAsignacionError, recalcular
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

D = date
TP_LINK = {"marca": "TP-LINK"}


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_out_mt") as engine:
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
    """`(venta_ref, item_id, unidades, monto)` of one campaign, in sale order."""
    return [(r[2], r[3], r[5], r[6]) for r in w.consumos(engine, campana_id)]


class TestReparto:
    def test_shares_by_percent_and_fixed_spread_over_each_product_sales_by_units(self, engine: Engine) -> None:
        campana = w.monto_total(engine, [w.grupo(engine, [TP_LINK])], "1000.00")
        w.reparto(engine, campana, 2964, porcentaje="60")
        w.reparto(engine, campana, 2270, monto="100.00")
        ml = w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
        fuera = w.venta(engine, "fuera", 2964, 2, D(2026, 11, 3))
        tn = w.venta(engine, "tn", 2270, 4, D(2026, 11, 30))
        w.venta(engine, "ml", 2964, 5, D(2026, 12, 1))  # after the campaign
        w.venta(engine, "ml", 950, 5, D(2026, 11, 2))  # outside its groups

        _recalcular(engine, campana)

        # 300.00 is left unassigned: no row carries it.
        assert _filas(engine, campana) == [
            (ml, 2964, 1, Decimal("200.00")),
            (fuera, 2964, 2, Decimal("400.00")),
            (tn, 2270, 4, Decimal("100.00")),
        ]

    def test_cents_add_up_exactly_to_the_share(self, engine: Engine) -> None:
        campana = w.monto_total(engine, [w.grupo(engine, [TP_LINK])], "100.00")
        w.reparto(engine, campana, 2964, porcentaje="100")
        for dia in (2, 3, 4):
            w.venta(engine, "ml", 2964, 1, D(2026, 11, dia))

        _recalcular(engine, campana)

        assert [f[3] for f in _filas(engine, campana)] == [Decimal("33.33"), Decimal("33.34"), Decimal("33.33")]

    def test_a_negative_total_writes_negative_rows(self, engine: Engine) -> None:
        campana = w.monto_total(engine, [w.grupo(engine, [TP_LINK])], "-13662075.00")
        w.reparto(engine, campana, 2964, porcentaje="60")
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
        w.venta(engine, "tn", 2964, 1, D(2026, 11, 3))

        _recalcular(engine, campana)

        assert [f[3] for f in _filas(engine, campana)] == [Decimal("-4098622.50"), Decimal("-4098622.50")]

    def test_a_share_without_sales_or_out_of_reach_and_a_product_without_share_write_nothing(
        self, engine: Engine
    ) -> None:
        campana = w.monto_total(engine, [w.grupo(engine, [{"marca": "TP-LINK", "categoria": "Routers"}])], "500.00")
        w.reparto(engine, campana, 2964, monto="100.00")  # no sale in the dates
        w.reparto(engine, campana, 950, monto="100.00")  # not in the groups' reach
        w.venta(engine, "ml", 2964, 3, D(2026, 10, 31))
        w.venta(engine, "ml", 950, 3, D(2026, 11, 2))

        _recalcular(engine, campana)

        assert w.consumos(engine) == []

    def test_a_share_loaded_with_vat_is_net_of_its_product_vat(self, engine: Engine) -> None:
        campana = w.monto_total(engine, [w.grupo(engine, [TP_LINK])], "1000.00", monto_incluye_iva=True)
        w.reparto(engine, campana, 2964, monto="121.00")
        w.reparto(engine, campana, 2270, monto="110.50")
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
        w.venta(engine, "ml", 2270, 1, D(2026, 11, 2))

        _recalcular(engine, campana)

        assert [(f[1], f[3]) for f in _filas(engine, campana)] == [(2964, Decimal("100.00")), (2270, Decimal("100.00"))]

    def test_a_return_inside_the_dates_moves_the_share_to_the_units_kept(self, engine: Engine) -> None:
        campana = w.monto_total(engine, [w.grupo(engine, [TP_LINK])], "100.00")
        w.reparto(engine, campana, 2964, monto="100.00")
        a = w.venta(engine, "fuera", 2964, 2, D(2026, 11, 2), cliente=55)
        b = w.venta(engine, "ml", 2964, 1, D(2026, 11, 3))
        w.venta(engine, "fuera", 2964, 1, D(2026, 11, 4), signo=-1, cliente=55)

        _recalcular(engine, campana)

        assert _filas(engine, campana) == [(a, 2964, 1, Decimal("50.00")), (b, 2964, 1, Decimal("50.00"))]

    def test_a_rerun_writes_nothing_and_a_changed_share_rewrites(self, engine: Engine) -> None:
        campana = w.monto_total(engine, [w.grupo(engine, [TP_LINK])], "100.00")
        w.reparto(engine, campana, 2964, monto="90.00")
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 3))
        _recalcular(engine, campana)

        assert (_recalcular(engine, campana).inserted, _recalcular(engine, campana).deleted) == (0, 0)

        w.execute(engine, "UPDATE sell_out_campana_items SET reparto_monto = 50 WHERE campana_id = :c", c=campana)
        result = _recalcular(engine, campana)
        assert (result.inserted, result.deleted) == (2, 2)
        assert [f[3] for f in _filas(engine, campana)] == [Decimal("25.00"), Decimal("25.00")]

    def test_a_voided_campaign_loses_its_rows(self, engine: Engine) -> None:
        campana = w.monto_total(engine, [w.grupo(engine, [TP_LINK])], "-100.00")
        w.reparto(engine, campana, 2964, monto="-100.00")
        w.venta(engine, "ml", 2964, 2, D(2026, 11, 2))
        _recalcular(engine, campana)
        w.execute(engine, "UPDATE sell_out_campanas SET estado = 'anulada' WHERE id = :c", c=campana)

        assert _recalcular(engine, campana).deleted == 1
        assert w.consumos(engine) == []


class TestMoneda:
    def test_a_usd_sale_day_row_carries_its_day_bna(self, engine: Engine) -> None:
        w.tipo_cambio(engine, D(2026, 11, 2), 1400)
        w.tipo_cambio(engine, D(2026, 11, 3), 1450.5)
        campana = w.monto_total(engine, [w.grupo(engine, [TP_LINK])], "10.00", moneda="USD", tc_modo="dia_venta")
        w.reparto(engine, campana, 2964, monto="10.00")
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 3))

        _recalcular(engine, campana)

        assert [(r[6], r[7]) for r in w.consumos(engine)] == [
            (Decimal("5.00"), Decimal("1400")),
            (Decimal("5.00"), Decimal("1450.5")),
        ]

    def test_a_usd_fixed_rate_row_carries_the_campaign_rate(self, engine: Engine) -> None:
        campana = w.monto_total(
            engine, [w.grupo(engine, [TP_LINK])], "10.00", moneda="USD", tc_modo="fijo", tipo_cambio="1000"
        )
        w.reparto(engine, campana, 2964, monto="10.00")
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))

        _recalcular(engine, campana)

        assert [(r[6], r[7]) for r in w.consumos(engine)] == [(Decimal("10.00"), Decimal("1000"))]

    def test_a_usd_sale_day_campaign_without_a_rate_is_refused(self, engine: Engine) -> None:
        campana = w.monto_total(engine, [w.grupo(engine, [TP_LINK])], "10.00", moneda="USD", tc_modo="dia_venta")
        w.reparto(engine, campana, 2964, monto="10.00")
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))

        with pytest.raises(SellOutAsignacionError):
            _recalcular(engine, campana)


class TestExclusividad:
    def test_an_exclusive_campaign_before_it_does_not_limit_its_units(self, engine: Engine) -> None:
        tp = w.grupo(engine, [TP_LINK])
        exclusiva = w.campana(engine, [tp], acumulable=False)
        total = w.monto_total(engine, [tp], "30.00")
        w.reparto(engine, total, 2964, monto="30.00")
        a = w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
        b = w.venta(engine, "ml", 2964, 2, D(2026, 11, 3))

        _recalcular(engine, total)

        assert _filas(engine, exclusiva) == [(a, 2964, 1, Decimal("10.00")), (b, 2964, 2, Decimal("20.00"))]
        assert _filas(engine, total) == [(a, 2964, 1, Decimal("10.00")), (b, 2964, 2, Decimal("20.00"))]

    def test_it_holds_no_units_an_exclusive_campaign_after_it_would_lose(self, engine: Engine) -> None:
        tp = w.grupo(engine, [TP_LINK])
        total = w.monto_total(engine, [tp], "30.00", acumulable=False)
        w.reparto(engine, total, 2964, monto="30.00")
        despues = w.campana(engine, [tp], acumulable=False)
        ref = w.venta(engine, "ml", 2964, 3, D(2026, 11, 2))

        _recalcular(engine, despues)

        assert _filas(engine, despues) == [(ref, 2964, 3, Decimal("30.00"))]
        assert _filas(engine, total) == [(ref, 2964, 3, Decimal("30.00"))]


class TestRepartoInvalido:
    @pytest.mark.parametrize(
        ("total", "monto", "error"), [("100.00", "100.01", "exceed"), ("-100.00", "10.00", "sign")]
    )
    def test_an_invalid_split_fails_its_campaign_and_writes_nothing(
        self, engine: Engine, total: str, monto: str, error: str
    ) -> None:
        campana = w.monto_total(engine, [w.grupo(engine, [TP_LINK])], total)
        w.reparto(engine, campana, 2964, monto=monto)
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))

        with pytest.raises(SellOutAsignacionError, match=f"campaign {campana}: .*{error}"):
            _recalcular(engine, campana)

        assert w.consumos(engine) == []

    def test_a_shared_product_without_vat_rate_fails_naming_campaign_and_product(self, engine: Engine) -> None:
        campana = w.monto_total(engine, [w.grupo(engine, [TP_LINK])], "100.00", monto_incluye_iva=True)
        w.reparto(engine, campana, 2964, monto="50.00")
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
        w.execute(engine, "UPDATE productos_erp SET iva = NULL WHERE item_id = 2964")
        try:
            with pytest.raises(SellOutAsignacionError, match=f"campaign {campana}: product 2964 has no VAT rate"):
                _recalcular(engine, campana)
        finally:
            w.execute(engine, "UPDATE productos_erp SET iva = 21 WHERE item_id = 2964")


class TestSigno:
    def test_a_negative_per_unit_amount_is_never_written(self, engine: Engine, monkeypatch) -> None:
        campana = w.campana(engine, [w.grupo(engine, [TP_LINK])])
        ref = w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
        negativo = tope.Consumo("ml", ref, 2964, D(2026, 11, 2), 1, Decimal("-10.00"))
        monkeypatch.setattr(tope, "asignar", lambda *a, **k: [negativo])

        with pytest.raises(SellOutAsignacionError):
            _recalcular(engine, campana)

        assert w.consumos(engine) == []


class TestQueryCount:
    def test_the_reads_do_not_grow_with_its_campaigns_and_shares(self, engine: Engine) -> None:
        assert _selects(engine, 1) == _selects(engine, 3)


def _selects(engine: Engine, n: int) -> int:
    w.clean(engine)
    tp = w.grupo(engine, [TP_LINK])
    ids = [w.monto_total(engine, [tp], "100.00") for _ in range(n)]
    for cid in ids:
        w.reparto(engine, cid, 2964, porcentaje="50")
        w.reparto(engine, cid, 2270, monto="10.00")
    for i in range(n):
        w.venta(engine, "ml", 2964, 1, D(2026, 11, 1 + i))
        w.venta(engine, "fuera", 2270, 1, D(2026, 11, 1 + i))
    selects: List[str] = []

    def contar(conn, cursor, statement, parameters, context, executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(engine, "before_cursor_execute", contar)
    try:
        assert _recalcular(engine, *ids).inserted > 0
    finally:
        event.remove(engine, "before_cursor_execute", contar)
    return len(selects)
