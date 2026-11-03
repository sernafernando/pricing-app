"""A cost mode change's cost-bonus follow-up (`bonos_costo.seguir_fifo`): a capped bonus's other product held by a
drain makes the save wait, never fail, and queues the bonus; and odd worlds (USD lots, extreme dates, no lots left)
through preview and confirm."""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from typing import Any, Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.services.sell_in import modos
from app.services.sell_in.costing import LOCK_NAMESPACE, get_costing
from tests.services.sell_in import _bono_world as b
from tests.services.sell_in import _world as si

pytestmark = pytest.mark.postgres
D = date
HOY = D(2026, 11, 10)
R, OTRO = 2964, 950


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("modos_bonos") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    b.clean(engine)


def _s(engine: Engine) -> Session:
    return sessionmaker(bind=engine, autoflush=False)()


def _vista(engine: Engine, modo: str, desde: date) -> modos.VistaPrevia:
    with _s(engine) as db:
        vista = modos.vista_previa(db, R, modo, desde, HOY, 7)
        db.rollback()
    return vista


def _salvar(engine: Engine, modo: str, desde: date, huella: str) -> int:
    with _s(engine) as db:
        modo_id = modos.confirmar(db, R, modo, desde, HOY, 7, huella)
        db.commit()
    return modo_id


def _n(engine: Engine, q: str) -> Any:
    with engine.connect() as c:
        return c.execute(text(q)).scalar()


def test_a_capped_bonus_product_held_by_a_drain_waits_and_queues_the_bonus(engine: Engine) -> None:
    bono = b.bono_costo(engine, "3.00", alcance="modelos", marca=None, modelos=(R, OTRO), tope_unidades=5)
    si.compra(engine, [(R, 100, "1000.00")], D(2026, 10, 1))
    si.venta(engine, "fuera", R, 5, D(2026, 10, 10))
    with _s(engine) as db:
        get_costing().recompute(db, [R], isolate_failures=False)
        db.commit()
    with engine.begin() as c:
        c.execute(text("DELETE FROM sell_in_bono_dirty"))
    vista = _vista(engine, "ponderado", D(2026, 10, 5))

    with engine.connect() as drain:
        drain.execute(text("SELECT pg_advisory_xact_lock(:n, :i)"), {"n": LOCK_NAMESPACE, "i": OTRO})
        t0 = time.monotonic()
        _salvar(engine, "ponderado", D(2026, 10, 5), vista.huella)
        espera = time.monotonic() - t0
        drain.rollback()

    assert espera >= 1.5
    assert _n(engine, "SELECT count(*) FROM sell_in_modos_producto") == 1
    assert _n(engine, "SELECT count(*) FROM auditoria") == 1
    assert _n(engine, f"SELECT count(*) FROM sell_in_bono_dirty WHERE tipo='bono' AND ref={bono}") == 1


def test_usd_lots_with_repeating_decimals_save_what_the_preview_says(engine: Engine) -> None:
    si.compra(engine, [(R, 7, "33.33")], D(2026, 10, 1), moneda="USD", tipo_cambio="1433.37")
    si.compra(engine, [(R, 13, "41.17")], D(2026, 10, 2), moneda="USD", tipo_cambio="1447.91")
    si.venta(engine, "fuera", R, 3, D(2026, 10, 20))
    with _s(engine) as db:
        get_costing().recompute(db, [R], isolate_failures=False)
        db.commit()
    vista = _vista(engine, "ultimo", D(2026, 10, 15))
    _salvar(engine, "ultimo", D(2026, 10, 15), vista.huella)
    assert vista.ventas_cambian == 1


@pytest.mark.parametrize("desde", [D(1, 1, 1), D(1900, 1, 1), D(9999, 12, 31)])
@pytest.mark.parametrize("modo", ["ponderado", "ultimo", "fifo"])
def test_extreme_dates_do_not_blow_up(engine: Engine, modo, desde) -> None:
    si.compra(engine, [(R, 10, "100.00")], D(2026, 10, 1))
    si.venta(engine, "fuera", R, 3, D(2026, 10, 20))
    vista = _vista(engine, modo, desde)
    _salvar(engine, modo, desde, vista.huella)


@pytest.mark.parametrize("modo", ["ponderado", "ultimo", "fifo"])
def test_a_product_with_no_lots_or_all_sold(engine: Engine, modo) -> None:
    assert _vista(engine, modo, HOY).unidades_restantes == 0
    si.compra(engine, [(R, 10, "100.00")], D(2026, 10, 1))
    si.venta(engine, "fuera", R, 10, D(2026, 10, 20))
    vista = _vista(engine, modo, D(2026, 10, 1))
    assert (vista.unidades_restantes, vista.descuento_unit) == (0, None)
    assert vista.sin_asignar_despues == Decimal("0.00")
