"""A profit offset pending approval records no consumption (tacticals approval S10): neither the ML cron
(`agregar_metricas_ml_incremental`), nor the recalculation endpoints, nor the recalculation scripts. The approved
offsets next to it are recorded as before. Invented data, the worlds of `test_offsets_consumo_postgres.py` and
`test_offsets_recalculo_postgres.py`."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Iterator

import pytest
from fastapi import HTTPException
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.endpoints.offsets_ganancia import _consumo_grupos, _consumo_individual
from app.models.offset_ganancia import OffsetGanancia
from app.scripts import agregar_metricas_ml_incremental as incremental
from app.scripts import recalcular_consumo_grupos, recalcular_consumo_offsets
from tests.services.metricas_ml_legacy import _world as w
from tests.services.metricas_ml_legacy.test_offsets_recalculo_postgres import SIN_VENTAS_FUERA

pytestmark = pytest.mark.postgres

D = Decimal
A = 6601
VENTA = 820001


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("metricas_ml_offsets_pendientes") as engine:
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


def _offsets(engine: Engine, estado_grupo: str, estado_individual: str, estado_otro: str = "activa") -> None:
    """Capped 10 %-of-cost offsets of A: id 1 in group 1, id 2 individual, id 3 individual 5 % (the approved
    neighbour)."""
    w.run(engine, "INSERT INTO offset_grupos (id, nombre, oculto) VALUES (1, 'G', false)")
    w.run(
        engine,
        "INSERT INTO offsets_ganancia (id, tipo_offset, porcentaje, moneda, item_id, grupo_id, fecha_desde,"
        " max_unidades, aplica_ml, estado) VALUES"
        " (1, 'porcentaje_costo', 10, 'ARS', :a, 1, '2026-10-01', 100, true, :g),"
        " (2, 'porcentaje_costo', 10, 'ARS', :a, NULL, '2026-10-01', 100, true, :i),"
        " (3, 'porcentaje_costo', 5, 'ARS', :a, NULL, '2026-10-01', 100, true, :o)",
        a=A,
        g=estado_grupo,
        i=estado_individual,
        o=estado_otro,
    )


def _vendido(engine: Engine) -> None:
    """One stored ML sale of A on 10-05, 1 unit at a cost of 25000."""
    w.producto(engine, A, costo="30")
    w.tipo_cambio(engine, date(2026, 10, 1), 1000)
    w.run(
        engine,
        "INSERT INTO ml_ventas_metricas (id_operacion, item_id, fecha_venta, cantidad, monto_total, monto_limpio,"
        " costo_unitario_sin_iva, costo_total_sin_iva, cotizacion_dolar, marca, categoria)"
        " VALUES (:o, :i, '2026-10-05 15:00', 1, 100000, 80000, 25000, 25000, 1000, 'MARCA DEMO', 'CAMARAS')",
        o=VENTA,
        i=A,
    )


def _individuales(engine: Engine) -> list:
    return w.rows(engine, "SELECT offset_id, monto_offset_aplicado FROM offset_individual_consumo ORDER BY offset_id")


def _de_grupo(engine: Engine) -> list:
    return w.rows(engine, "SELECT offset_id, monto_offset_aplicado FROM offset_grupo_consumo")


def test_the_cron_records_nothing_for_pending_offsets_and_the_approved_one_as_before(engine, db) -> None:
    w.producto(engine, A, costo="30")
    w.paso(engine, A, 0, date(2026, 10, 1), "25.00000")
    w.tipo_cambio(engine, date(2026, 10, 1), 1000)
    _offsets(engine, "pendiente", "pendiente")
    w.venta_ml(engine, A, datetime(2026, 10, 5, 15), cantidad=2)

    incremental.process_and_insert(
        db, incremental.calcular_metricas_locales(db, datetime(2026, 10, 1), datetime(2026, 10, 31, 23, 59, 59))
    )
    db.commit()

    assert _de_grupo(engine) == []
    assert _individuales(engine) == [(3, D("2500.00"))]  # 5 % of 2 x 25000: the approved neighbour


def test_the_individual_endpoint_refuses_a_pending_offset_and_changes_nothing(engine, db) -> None:
    _vendido(engine)
    _offsets(engine, "activa", "pendiente")

    with pytest.raises(HTTPException) as exc:
        _consumo_individual.recalcular_consumo_offset_individual(2, db=db, current_user=None)

    assert exc.value.status_code == 409
    assert "pendiente de aprobación" in exc.value.detail
    _consumo_individual.recalcular_consumo_offset_individual(3, db=db, current_user=None)  # the approved one
    db.commit()
    assert _individuales(engine) == [(3, D("1250.00"))]


def test_the_group_endpoint_leaves_a_pending_offset_out(engine, db) -> None:
    _vendido(engine)
    _offsets(engine, "pendiente", "activa")

    _consumo_grupos.recalcular_consumo_grupo(1, db=db, current_user=None)
    db.commit()

    assert _de_grupo(engine) == []


@pytest.mark.parametrize("script", [recalcular_consumo_offsets, recalcular_consumo_grupos], ids=["offsets", "grupos"])
def test_the_group_scripts_leave_a_pending_offset_out(engine, db, script) -> None:
    _vendido(engine)
    _offsets(engine, "pendiente", "activa")

    script.recalcular_grupo(db, 1, 1000.0, verbose=False)
    db.commit()

    assert _de_grupo(engine) == []


@pytest.mark.parametrize("estado,esperado", [("pendiente", []), ("activa", [(2, D("2500.00"))])])
def test_the_individual_script_records_only_an_approved_offset(engine, db, estado, esperado) -> None:
    _vendido(engine)
    _offsets(engine, "activa", estado)
    offset = db.query(OffsetGanancia).filter(OffsetGanancia.id == 2).one()

    recalcular_consumo_offsets.recalcular_offset_individual(db, offset, 1000.0, verbose=False)
    db.commit()

    assert _individuales(engine) == esperado
