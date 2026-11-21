"""The ML metrics cron records the per-unit and cost-percentage offset consumptions of its sales.

`calcular_monto_offset` multiplied a float by the row's quantity, which the cron reads from
`tb_mercadolibre_orders_detail.mlo_quantity` (Numeric, a Decimal): every `monto_por_unidad` and `porcentaje_costo`
offset raised TypeError, and `registrar_consumo_*` swallowed it with a print, so none of those consumptions was ever
recorded. Now they are, and a failure to record one is logged with its traceback instead of printed. Costo SI T3 PR 8.
Invented data.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.scripts import agregar_metricas_ml_incremental as incremental
from tests.services.metricas_ml_legacy import _world as w

pytestmark = pytest.mark.postgres

D = Decimal
A = 6401
DESDE, HASTA = datetime(2026, 10, 1), datetime(2026, 10, 31, 23, 59, 59)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("metricas_ml_offsets") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


@pytest.fixture()
def db(engine: Engine) -> Iterator[Session]:
    with sessionmaker(bind=engine)() as session:
        yield session


def _mundo(engine: Engine) -> int:
    """A (USD): costo SI 25 at 1000 = 25000 a unit; one sale of 2 units on 10-05. Offsets of A, all capped (the cron
    only records capped offsets): group 1 at 10 % of the cost; individual 5 % of the cost and USD 3 per unit."""
    w.producto(engine, A, costo="30")
    w.paso(engine, A, 0, date(2026, 10, 1), "25.00000")
    w.tipo_cambio(engine, date(2026, 10, 1), 1000)
    w.run(engine, "INSERT INTO offset_grupos (id, nombre, oculto) VALUES (1, 'G', false)")
    w.run(
        engine,
        "INSERT INTO offsets_ganancia (id, tipo_offset, porcentaje, monto, moneda, item_id, grupo_id, fecha_desde,"
        " max_unidades, aplica_ml) VALUES"
        " (1, 'porcentaje_costo', 10, NULL, 'ARS', :a, 1, '2026-10-01', 100, true),"
        " (2, 'porcentaje_costo', 5, NULL, 'ARS', :a, NULL, '2026-10-01', 100, true),"
        " (3, 'monto_por_unidad', NULL, 3, 'USD', :a, NULL, '2026-10-01', 100, true)",
        a=A,
    )
    return w.venta_ml(engine, A, datetime(2026, 10, 5, 15), cantidad=2)


def _cron(db: Session) -> None:
    incremental.process_and_insert(db, incremental.calcular_metricas_locales(db, DESDE, HASTA))
    db.commit()


def test_the_cron_records_cost_percentage_and_per_unit_offset_consumptions(engine: Engine, db: Session) -> None:
    """Group 10 % of 2 x 25000 = 5000; individual 5 % = 2500 and USD 3 x 2 = USD 6 (pesos at the stored rate); each
    summary carries its consumption."""
    venta = _mundo(engine)

    _cron(db)

    [(grupo_ars, grupo_unidades)] = w.rows(
        engine, "SELECT monto_offset_aplicado, cantidad FROM offset_grupo_consumo WHERE id_operacion = :o", o=venta
    )
    assert (grupo_ars, grupo_unidades) == (D("5000.00"), 2)
    individuales = w.rows(
        engine,
        "SELECT offset_id, monto_offset_aplicado, monto_offset_usd, cotizacion_dolar FROM offset_individual_consumo"
        " WHERE id_operacion = :o ORDER BY offset_id",
        o=venta,
    )
    assert [(o, ars) for o, ars, _, _ in individuales][:1] == [(2, D("2500.00"))]
    [(_, por_unidad_ars, por_unidad_usd, cotizacion)] = [fila for fila in individuales if fila[0] == 3]
    assert por_unidad_usd == D("6.00")
    assert por_unidad_ars == (6 * cotizacion).quantize(D("0.01"))
    assert w.rows(engine, "SELECT total_monto_ars, total_unidades FROM offset_grupo_resumen") == [(D("5000.00"), 2)]
    assert w.rows(engine, "SELECT offset_id, total_monto_ars FROM offset_individual_resumen ORDER BY offset_id") == [
        (2, D("2500.00")),
        (3, por_unidad_ars),
    ]


def test_a_quantity_change_moves_the_consumption(engine: Engine, db: Session) -> None:
    """Re-run after the order went from 2 to 3 units: the 10 % group consumption becomes 7500."""
    venta = _mundo(engine)
    _cron(db)
    w.run(engine, "UPDATE tb_mercadolibre_orders_detail SET mlo_quantity = 3 WHERE mlo_id = :o", o=venta)

    _cron(db)

    assert w.rows(engine, "SELECT monto_offset_aplicado, cantidad FROM offset_grupo_consumo") == [(D("7500.00"), 3)]
    assert w.rows(engine, "SELECT total_monto_ars, total_unidades FROM offset_grupo_resumen") == [(D("7500.00"), 3)]


def test_a_consumption_that_fails_is_logged_with_its_operation(
    engine: Engine, db: Session, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Recording an offset must not stop the cron, but a failure is logged (error level, with the operation and the
    traceback), never just printed."""
    venta = _mundo(engine)

    def falla(*args, **kwargs):
        raise ValueError("offset roto")

    monkeypatch.setattr(incremental, "calcular_monto_offset", falla)
    with caplog.at_level(logging.ERROR):
        _cron(db)

    errores = [r for r in caplog.records if r.levelno >= logging.ERROR and str(venta) in r.getMessage()]
    assert {"grupo", "individual"} <= {"grupo" if "grupo" in r.getMessage() else "individual" for r in errores}
    assert all(r.exc_info and "offset roto" in str(r.exc_info[1]) for r in errores)
    assert w.rows(engine, "SELECT count(*) FROM ml_ventas_metricas WHERE id_operacion = :o", o=venta) == [(1,)]
