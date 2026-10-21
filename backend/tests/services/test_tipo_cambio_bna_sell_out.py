"""A BNA update queues the sell-out campaigns it can move (sell-in-sell-out T7 S3),
in the transaction that stores the rate: the unrated `al_cobro` ones and the USD
ones still running. A rewrite of the same rate queues nothing.

Postgres only (the queue). Exercises the storing half of the update
(`guardar_cotizacion_bna`): the scrape needs `lxml`, which is not in
requirements; `tests.services.sell_out._world`.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
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


def _tasas(engine: Engine) -> list:
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT venta FROM tipo_cambio WHERE moneda = 'USD'"))]


def test_the_rate_is_stored_even_when_queueing_fails(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _rota(db, fecha):
        db.execute(text("SELECT * FROM tabla_que_no_existe"))  # aborts the transaction without a savepoint

    monkeypatch.setattr(tipo_cambio_service.sell_out_queue, "enqueue_por_bna", _rota)

    with caplog.at_level(logging.ERROR, logger=tipo_cambio_service.__name__):
        _actualizar(engine)

    assert _tasas(engine) == [1450.0]
    assert any("sell-out" in r.getMessage() for r in caplog.records)


def test_a_failed_update_leaves_the_session_usable(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    def _caida(*args, **kwargs):
        raise RuntimeError("BNA caído")

    monkeypatch.setattr(tipo_cambio_service.requests, "post", _caida)
    with sessionmaker(bind=engine)() as db:
        with pytest.raises(Exception):
            db.execute(text("SELECT * FROM tabla_que_no_existe"))  # a statement failed before the update

        assert tipo_cambio_service.actualizar_tipo_cambio_bna(db)["status"] == "error"

        assert db.execute(text("SELECT 1")).scalar() == 1  # rolled back, not left aborted
