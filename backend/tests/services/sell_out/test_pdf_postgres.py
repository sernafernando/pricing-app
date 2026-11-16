"""Sell out on ventas por fuera from the PDF reports (VPF T4, S15/S18/L14).

A campaign credits the PDF lines under canal `fuera` (`venta_ref` = line id, orchestrator L20), never the GBP sync
rows; a percentage on cost takes Costo D = 'Precio Costo' x 1.065 (owner, L14).
Invented data only (the repo is public).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator, List

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.services.sell_out import queue as sell_out_queue
from app.services.sell_out.asignacion import recalcular
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

D = date
TP = {"marca": "TP-LINK"}


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_out_pdf") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _recalcular(engine: Engine, *ids: int) -> None:
    with sessionmaker(bind=engine)() as db:
        recalcular(db, ids)
        db.commit()


def _filas(engine: Engine, campana_id: int) -> List[tuple]:
    return [(r[1], r[2], r[5], r[6]) for r in w.consumos(engine, campana_id)]


class TestCredito:
    def test_a_pdf_line_is_credited_under_canal_fuera(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [TP])])
        pdf = w.venta(engine, "fuera", 2964, 2, D(2026, 11, 2))

        _recalcular(engine, campana)

        assert _filas(engine, campana) == [("fuera", pdf, 2, Decimal("20.00"))]

    def test_a_gbp_synced_sale_is_not_credited(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [TP])])
        w.venta(engine, "gbp", 2964, 2, D(2026, 11, 2))

        _recalcular(engine, campana)

        assert _filas(engine, campana) == []

    def test_a_credit_note_line_nets_its_sale(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [TP])])
        pdf = w.venta(engine, "fuera", 2964, 3, D(2026, 11, 2), cliente=101)
        w.venta(engine, "fuera", 2964, 1, D(2026, 11, 5), signo=-1, cliente=101)

        _recalcular(engine, campana)

        assert _filas(engine, campana) == [("fuera", pdf, 2, Decimal("20.00"))]

    def test_percentage_on_cost_takes_costo_d(self, engine: Engine) -> None:
        """10% of Costo D: 'Precio Costo' 1000.00 for 2 units x 1.065 = 1065.00 -> 106.50."""
        grupo = w.grupo(engine, [TP])
        campana = w.campana(
            engine, [grupo], tipo="porcentaje", monto_unit=None, porcentaje="10", base_porcentaje="costo"
        )
        pdf = w.venta(engine, "fuera", 2964, 2, D(2026, 11, 2), precio_costo=Decimal("1000.00"))

        _recalcular(engine, campana)

        assert _filas(engine, campana) == [("fuera", pdf, 2, Decimal("106.50"))]

    def test_percentage_on_net_price_takes_the_line_price(self, engine: Engine) -> None:
        grupo = w.grupo(engine, [TP])
        campana = w.campana(
            engine, [grupo], tipo="porcentaje", monto_unit=None, porcentaje="10", base_porcentaje="precio_neto"
        )
        pdf = w.venta(engine, "fuera", 2964, 2, D(2026, 11, 2), precio=Decimal("2000.00"))

        _recalcular(engine, campana)

        assert _filas(engine, campana) == [("fuera", pdf, 2, Decimal("200.00"))]


class TestCola:
    def test_a_pdf_line_queues_the_campaigns_that_reach_it(self, engine: Engine) -> None:
        campana = w.campana(engine, [w.grupo(engine, [TP])])
        w.campana(engine, [w.grupo(engine, [{"marca": "MERCUSYS"}])])  # does not reach it
        pdf = w.venta(engine, "fuera", 2964, 1, D(2026, 11, 2))

        with sessionmaker(bind=engine)() as db:
            assert sell_out_queue.campanas_de_ventas(db, [("fuera", pdf)]) == {campana}
