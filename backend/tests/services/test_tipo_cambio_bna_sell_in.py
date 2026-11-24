"""A BNA update no longer queues the USD sell-in cost bonuses (tactical sell in USD S2, S5): since sell-in-costo-si T5
PR A (L24) a cost bonus is never applied per sale, so there is nothing to re-convert.

Postgres only (the queue). Exercises the storing half of the update (`guardar_cotizacion_bna`)."""

from __future__ import annotations

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


def test_a_new_rate_queues_no_sell_in_cost_bonus(engine: Engine) -> None:
    """sell-in-costo-si T5 PR A, L24 ("no podemos descontarselo dos veces"): a cost bonus is never applied per sale any
    more (costo SI holds the loyalty through its invoices), so a BNA update has nothing of sell in to re-convert."""
    _bono(engine, "al_cobro")
    _bono(engine, "dia_venta")
    b.clear_queue(engine)

    _actualizar(engine)

    assert b.queued(engine) == []
    with engine.connect() as conn:
        assert conn.execute(text("SELECT venta FROM tipo_cambio WHERE moneda = 'USD'")).scalars().all() == [1450.0]
