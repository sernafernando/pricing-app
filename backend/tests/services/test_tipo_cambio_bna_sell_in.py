"""A BNA update queues the USD sell-in cost bonuses it can move (tactical sell in USD S2, S5), in the transaction that
stores the rate, like sell out's campaigns: an `al_cobro` one whose collection has no rate yet ("estimated at today's
BNA, recomputed daily until the collection rate is loaded") and a `dia_venta` one still running. No new cron: the
daily BNA update queues them and the existing `sell_in.bono` worker recomputes them.

Postgres only (the queue). Exercises the storing half of the update (`guardar_cotizacion_bna`)."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Iterator, Optional

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.services import tipo_cambio_service
from tests.services.sell_in import _bono_world as b

pytestmark = pytest.mark.postgres

HOY = date.today()


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("tipo_cambio_bna_sell_in") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    b.clean(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tactical_cobranzas"))
        conn.execute(text("DELETE FROM tacticals"))


def _bono(
    engine: Engine,
    tc_modo: str,
    *,
    moneda: str = "USD",
    hasta: date = HOY + timedelta(days=30),
    tipo_cambio: Optional[str] = None,
    cobro: Optional[str] = None,
) -> int:
    with engine.begin() as conn:
        tactical = conn.execute(
            text(
                "INSERT INTO tacticals (tipo, nombre, marca, fecha_desde, fecha_hasta, moneda, tc_modo, tipo_cambio, "
                "usuario_id) VALUES ('sell_in', 'Synthetic', 'TP-LINK', :d, :h, 'USD', :m, :tc, 7) RETURNING id"
            ),
            {"d": HOY - timedelta(days=60), "h": hasta, "m": tc_modo, "tc": tipo_cambio},
        ).scalar()
        if cobro is not None:
            conn.execute(
                text(
                    "INSERT INTO tactical_cobranzas (tactical_id, fecha_cobro, tipo_cambio, usuario_id) "
                    "VALUES (:t, :f, :tc, 7)"
                ),
                {"t": tactical, "f": HOY, "tc": cobro},
            )
        bono = conn.execute(
            text(
                "INSERT INTO sell_in_bonos_marca (base, alcance, marca, tipo, monto_unit, moneda, fecha_desde, "
                "fecha_hasta, usuario_id, tactical_id, tactical_linea) VALUES ('costo_venta', 'marca', 'TP-LINK', "
                "'por_unidad', 10, :mon, :d, :h, 7, :t, 1) RETURNING id"
            ),
            {"mon": moneda, "d": HOY - timedelta(days=60), "h": hasta, "t": tactical},
        ).scalar()
    return bono


def _actualizar(engine: Engine, venta: float = 1450.0) -> None:
    with sessionmaker(bind=engine)() as db:
        tipo_cambio_service.guardar_cotizacion_bna(db, 1400.0, venta)


def test_a_new_rate_queues_the_usd_cost_bonuses_it_can_move(engine: Engine) -> None:
    sin_tasa = _bono(engine, "al_cobro")
    corriendo = _bono(engine, "dia_venta")
    _bono(engine, "al_cobro", cobro="1350")  # its collection rate is final
    _bono(engine, "dia_venta", hasta=HOY - timedelta(days=1))  # ended: its sales' dates already have their BNA
    _bono(engine, "fijo", tipo_cambio="1400")
    _bono(engine, "al_cobro", moneda="ARS")  # a % of the ARS cost of a USD tactical: no rate
    b.clear_queue(engine)

    _actualizar(engine)

    assert b.queued(engine) == sorted([("bono", sin_tasa), ("bono", corriendo)])


def test_the_same_rate_again_queues_nothing(engine: Engine) -> None:
    bono = _bono(engine, "al_cobro")
    _actualizar(engine)
    b.clear_queue(engine)

    _actualizar(engine)
    assert b.queued(engine) == []

    _actualizar(engine, 1460.0)
    assert b.queued(engine) == [("bono", bono)]


def test_the_rate_is_stored_even_when_queueing_the_cost_bonuses_fails(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _rota(db, fecha):
        db.execute(text("SELECT * FROM tabla_que_no_existe"))  # aborts the transaction without a savepoint

    monkeypatch.setattr(tipo_cambio_service.bonos_costo, "encolar_por_bna", _rota)

    with caplog.at_level(logging.ERROR, logger=tipo_cambio_service.__name__):
        _actualizar(engine)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT venta FROM tipo_cambio WHERE moneda = 'USD'")).scalars().all() == [1450.0]
    assert any("sell-in" in r.getMessage() for r in caplog.records)
