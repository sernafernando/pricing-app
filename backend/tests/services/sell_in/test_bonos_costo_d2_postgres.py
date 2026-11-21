"""D2 (sell-in-costo-si T3 PR 7, L4.2): a sale costed at costo SI takes no % or per-unit sale-cost bonus, in every
channel: costo SI already discounts that bonus from the purchase cost (`costo_si.fuentes`), so applying it again on
the sale would count it twice. A sale of a product with no costo SI on its date (list cost, Q1) keeps it, and a
`monto_total` split (not in costo SI) keeps applying (orchestrator, PR 7 doubt 2). Invented data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.services.sell_in import bonos_costo
from tests.services.sell_in import _bono_world as b
from tests.services.sell_in import _world as w
from tests.services.sell_in.test_bonos_monto_total_postgres import _crear

D = date
EN_SI, SIN_SI = 2964, 2270  # both TP-LINK: the brand bonuses reach them


def _run(engine: Engine, sql: str, **params) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql), params)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("sell_in_bonos_d2") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    _run(engine, "DELETE FROM costo_si_pasos")
    b.clean(engine)


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()


def _costo_si(engine: Engine, item_id: int, desde: date) -> None:
    _run(
        engine,
        "INSERT INTO costo_si_pasos (item_id, orden, tipo, fecha, cantidad, stock_antes, stock_base, stock_despues,"
        " promedio_usd, moneda) VALUES (:i, 0, 'inicio', :f, 0, 0, 0, 0, 40, 'USD')",
        i=item_id,
        f=desde,
    )


def _venta(engine: Engine, canal: str, item_id: int, dia: date, unidades: int = 2) -> int:
    ref = w.venta(engine, canal, item_id, unidades, dia)
    if canal != "ml":  # ML's cost comes from `mcosto` (30 for the sale)
        w.update_venta(engine, canal, ref, costo_total=Decimal("1000.00") * unidades)
    return ref


def _recalcular(engine: Engine, *item_ids: int) -> None:
    with sessionmaker(bind=engine)() as db:
        bonos_costo.recalcular(db, item_ids)
        db.commit()


def _filas(engine: Engine):
    """`(bono_id, venta_ref, item_id)`."""
    return sorted((r[0], r[2], r[3]) for r in b.bono_consumos(engine))


@pytest.mark.postgres
class TestD2:
    def test_a_sale_at_costo_si_gets_no_percentage_bonus_in_any_channel(self, engine: Engine) -> None:
        bono = b.bono_costo(engine, "3.00")
        _costo_si(engine, EN_SI, D(2026, 10, 1))
        for canal in ("ml", "fuera", "tn"):
            _venta(engine, canal, EN_SI, D(2026, 10, 5))
        lista = _venta(engine, "fuera", SIN_SI, D(2026, 10, 5))

        _recalcular(engine, EN_SI, SIN_SI)

        assert _filas(engine) == [(bono, lista, SIN_SI)]

    def test_a_sale_dated_before_its_costo_si_starts_keeps_the_bonus(self, engine: Engine) -> None:
        bono = b.bono_costo(engine, "3.00")
        _costo_si(engine, EN_SI, D(2026, 10, 10))
        antes = _venta(engine, "fuera", EN_SI, D(2026, 10, 5))
        _venta(engine, "fuera", EN_SI, D(2026, 10, 12))

        _recalcular(engine, EN_SI)

        assert _filas(engine) == [(bono, antes, EN_SI)]

    def test_a_per_unit_bonus_is_skipped_too(self, engine: Engine) -> None:
        b.bono_costo(engine, monto_unit="50.00")
        _costo_si(engine, EN_SI, D(2026, 10, 1))
        _venta(engine, "fuera", EN_SI, D(2026, 10, 5))

        _recalcular(engine, EN_SI)

        assert _filas(engine) == []

    def test_a_row_written_before_the_costo_si_existed_is_removed(self, engine: Engine) -> None:
        bono = b.bono_costo(engine, "3.00")
        ref = _venta(engine, "fuera", EN_SI, D(2026, 10, 5))
        _recalcular(engine, EN_SI)
        assert _filas(engine) == [(bono, ref, EN_SI)]

        _costo_si(engine, EN_SI, D(2026, 10, 1))
        _recalcular(engine, EN_SI)

        assert _filas(engine) == []

    def test_a_total_bonus_keeps_applying_on_a_sale_at_costo_si(self, db: Session, engine: Engine) -> None:
        total = _crear(db, reparto_criterio="unidades")
        db.commit()
        _costo_si(engine, EN_SI, D(2026, 10, 1))
        ref = _venta(engine, "fuera", EN_SI, D(2026, 10, 5))

        _recalcular(engine, EN_SI)

        assert _filas(engine) == [(total, ref, EN_SI)]
