"""A BNA update queues the sell-out campaigns it can move (sell-in-sell-out T7 S3),
in the transaction that stores the rate: the unrated `al_cobro` ones and the USD
ones still running. A rewrite of the same rate queues nothing.

Postgres only (the queue). Exercises the storing half of the update
(`guardar_cotizacion_bna`): the scrape needs `lxml`, which is not in
requirements; `tests.services.sell_out._world`.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.services import tipo_cambio_service
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

ROUTERS = {"marca": "TP-LINK", "categoria": "Routers"}


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("tipo_cambio_bna_sell_out") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _actualizar(engine: Engine, venta: float = 1450.0) -> None:
    with sessionmaker(bind=engine)() as db:
        tipo_cambio_service.guardar_cotizacion_bna(db, 1400.0, venta)


def test_a_new_rate_queues_the_usd_campaigns_it_can_move(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    hoy = date.today()
    ayer = hoy - timedelta(days=1)
    sin_tasa = w.campana(engine, [g], ayer - timedelta(days=30), ayer, moneda="USD", tc_modo="al_cobro")
    corriendo = w.campana(engine, [g], hoy, hoy + timedelta(days=30), moneda="USD", tc_modo="dia_venta")
    w.campana(engine, [g], ayer - timedelta(days=30), ayer, moneda="USD", tc_modo="fijo", tipo_cambio="1400")
    w.campana(engine, [g], hoy, hoy + timedelta(days=30))  # ARS

    _actualizar(engine)

    assert [row[0] for row in w.queued(engine)] == [sin_tasa, corriendo]


def test_the_same_rate_again_queues_nothing_and_a_changed_one_does(engine: Engine) -> None:
    hoy = date.today()
    cid = w.campana(engine, [w.grupo(engine, [ROUTERS])], hoy, hoy, moneda="USD", tc_modo="al_cobro")
    _actualizar(engine)
    w.clear_queue(engine)

    _actualizar(engine)
    assert w.queued(engine) == []

    _actualizar(engine, 1460.0)
    assert [row[0] for row in w.queued(engine)] == [cid]
