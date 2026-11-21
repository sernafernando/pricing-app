"""The offset recalculation endpoints and scripts treat an unknown sale cost like the ML cron does (costo SI interface
§7): a `porcentaje_costo` offset records no consumption for a sale whose cost is NULL, never one of 0, and the skip is
logged. Before, the individual endpoint and both scripts recorded a 0 consumption; the group endpoint dropped it
without a trace. Sales with a known cost are recorded as before. Costo SI T3 PR 8. Invented data.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.endpoints.offsets_ganancia import _consumo_grupos, _consumo_individual
from app.models.offset_ganancia import OffsetGanancia
from app.scripts import recalcular_consumo_grupos, recalcular_consumo_offsets
from tests.services.metricas_ml_legacy import _world as w

pytestmark = pytest.mark.postgres

D = Decimal
A = 6501
SIN_COSTO, CON_COSTO = 810001, 810002
AVISO = "has no known cost, no consumption recorded"
# No ventas por fuera in this world: the recalculation reads them from the PDF tables, which it does not have.
SIN_VENTAS_FUERA = (
    "(SELECT NULL::int AS id, NULL::timestamp AS fecha_venta, NULL::int AS item_id, NULL::int AS cantidad,"
    " NULL::varchar AS tipo_documento, NULL::numeric AS costo_total, NULL::numeric AS cotizacion_dolar,"
    " NULL::varchar AS marca, NULL::varchar AS categoria, NULL::int AS subcategoria_id WHERE false)"
)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("metricas_ml_recalculo") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for modulo in (_consumo_grupos, recalcular_consumo_grupos):
        monkeypatch.setattr(modulo, "VENTAS_FUERA_OFFSETS_SQL", SIN_VENTAS_FUERA)
    for modulo in (_consumo_grupos, _consumo_individual):
        monkeypatch.setattr(modulo, "verificar_permiso", lambda *_: True)
    yield
    w.clean(engine)


@pytest.fixture()
def db(engine: Engine) -> Iterator[Session]:
    with sessionmaker(bind=engine)() as session:
        yield session


def _mundo(engine: Engine, grupo: bool) -> None:
    """Two stored ML sales of A on 10-05, 1 unit each: one without a known cost (NULL), one at 25000. One 10 %-of-cost
    offset of A, capped, in group 1 or individual."""
    w.producto(engine, A, costo="30")
    w.tipo_cambio(engine, date(2026, 10, 1), 1000)
    for mlo_id, costo in ((SIN_COSTO, None), (CON_COSTO, 25000)):
        w.run(
            engine,
            "INSERT INTO ml_ventas_metricas (id_operacion, item_id, fecha_venta, cantidad, monto_total, monto_limpio,"
            " costo_unitario_sin_iva, costo_total_sin_iva, cotizacion_dolar, marca, categoria)"
            " VALUES (:o, :i, '2026-10-05 15:00', 1, 100000, 80000, :c, :c, 1000, 'MARCA DEMO', 'CAMARAS')",
            o=mlo_id,
            i=A,
            c=costo,
        )
    w.run(engine, "INSERT INTO offset_grupos (id, nombre, oculto) VALUES (1, 'G', false)")
    w.run(
        engine,
        "INSERT INTO offsets_ganancia (id, tipo_offset, porcentaje, moneda, item_id, grupo_id, fecha_desde,"
        " max_unidades, aplica_ml) VALUES (1, 'porcentaje_costo', 10, 'ARS', :a, :g, '2026-10-01', 100, true)",
        a=A,
        g=1 if grupo else None,
    )


def _consumos(engine: Engine, tabla: str) -> list:
    return w.rows(engine, f"SELECT id_operacion, monto_offset_aplicado FROM {tabla} ORDER BY id_operacion")


def _avisado(caplog: pytest.LogCaptureFixture) -> bool:
    return any(AVISO in r.getMessage() and str(SIN_COSTO) in r.getMessage() for r in caplog.records)


def test_individual_endpoint_skips_and_logs_an_unknown_cost(
    engine: Engine, db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    _mundo(engine, grupo=False)
    with caplog.at_level(logging.WARNING):
        _consumo_individual.recalcular_consumo_offset_individual(1, db=db, current_user=None)
    db.commit()

    assert _consumos(engine, "offset_individual_consumo") == [(CON_COSTO, D("2500.00"))]
    assert _avisado(caplog)


def test_group_endpoint_skips_and_logs_an_unknown_cost(
    engine: Engine, db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    _mundo(engine, grupo=True)
    with caplog.at_level(logging.WARNING):
        _consumo_grupos.recalcular_consumo_grupo(1, db=db, current_user=None)
    db.commit()

    assert _consumos(engine, "offset_grupo_consumo") == [(CON_COSTO, D("2500.00"))]
    assert _avisado(caplog)


@pytest.mark.parametrize("script", [recalcular_consumo_offsets, recalcular_consumo_grupos], ids=["offsets", "grupos"])
def test_group_scripts_skip_and_log_an_unknown_cost(
    engine: Engine, db: Session, caplog: pytest.LogCaptureFixture, script
) -> None:
    _mundo(engine, grupo=True)
    with caplog.at_level(logging.WARNING):
        script.recalcular_grupo(db, 1, 1000.0, verbose=False)
    db.commit()

    assert _consumos(engine, "offset_grupo_consumo") == [(CON_COSTO, D("2500.00"))]
    assert _avisado(caplog)


def test_individual_script_skips_and_logs_an_unknown_cost(
    engine: Engine, db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    _mundo(engine, grupo=False)
    offset = db.query(OffsetGanancia).filter(OffsetGanancia.id == 1).one()
    with caplog.at_level(logging.WARNING):
        recalcular_consumo_offsets.recalcular_offset_individual(db, offset, 1000.0, verbose=False)
    db.commit()

    assert _consumos(engine, "offset_individual_consumo") == [(CON_COSTO, D("2500.00"))]
    assert _avisado(caplog)
