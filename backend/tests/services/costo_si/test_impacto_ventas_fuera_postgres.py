"""The T4 dry-run predicts the ventas por fuera PDF lines the deploy re-costs (`despues.ventas_fuera`, sell-in-costo-si
T3 PR 9: `costo_erp.recostear`, which the dry-run calls in its report-only mode). PR 9's own world: lines before the
change, of another product, of a combo, of a broken-down combo (L19) and with a manual cost. Measured read-only, then
recalculated as the deploy does; every stored line must equal the prediction. Invented data."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.services.costo_si import despues, impacto, queue, simulacion
from app.services.costo_si.despues import ventas_fuera
from tests.conftest import POSTGRES_TEST_URL
from tests.services.costo_si import _world as w
from tests.services.ventas_fuera_pdf import test_costo_si_despues_postgres as vpf
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

Q, COMBO_PQ = 5620, 5621  # Q: same brand as P, so the loyalty gives it a costo SI too; COMBO_PQ = P + Q


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("costo_si_impacto_vpf", vpf._tablas(), vpf._STUBS, after=vpf._install) as engine:
        yield engine


@pytest.fixture()
def motor(engine: Engine) -> Iterator[Engine]:
    with engine.connect() as conn:
        esquema = conn.execute(text("SELECT current_schema()")).scalar()
    motor = simulacion.motor_solo_lectura(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={esquema}"})
    yield motor
    motor.dispose()


@pytest.fixture(autouse=True)
def _callbacks_del_deploy(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(despues, "_CALLBACKS", {"ventas_fuera": ventas_fuera.recostear_desde})
    monkeypatch.setattr(despues, "_cargados", True)
    yield
    w.run(
        engine,
        "TRUNCATE ventas_fuera_linea_overrides, ventas_fuera_operacion_lineas, ventas_fuera_operaciones,"
        " ventas_fuera_pdf_cargas, sell_dirty CASCADE",
    )
    w.clean(engine)


def test_the_dry_run_predicts_every_pdf_line_the_deploy_re_costs(engine: Engine, motor: Engine) -> None:
    lineas = vpf._mundo(engine)
    w.producto(engine, Q, costo="30")
    w.costo_lista(engine, Q, datetime(2026, 9, 1), "20")
    # A purchase on 10-05 with the brand loyalty: Q's costo SI becomes 30 x (1 - 0.036) = 28.92, not its list 20.
    w.factura(engine, Q, date(2026, 10, 5), datetime(2026, 10, 5, 10), 10, "30", previo=0)
    # And one for P on 10-02, so neither product's costo SI equals its list cost: a combo of both must read both.
    w.factura(engine, vpf.P, date(2026, 10, 2), datetime(2026, 10, 2, 10), 10, "35", previo=0)
    w.producto(engine, COMBO_PQ, marca="OTRA MARCA")
    w.run(
        engine,
        f"INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES ({COMBO_PQ}, {vpf.P}, 1),"
        f" ({COMBO_PQ}, {Q}, 1)",
    )
    (lineas["pq"],) = vpf._venta(engine, 6, date(2026, 10, 10), [(COMBO_PQ, "1")])
    w.run(engine, "DELETE FROM costo_si_dirty")  # before the deploy nothing is queued
    guardado = vpf._costos(engine)

    with simulacion.simular(motor) as sim:
        informe = impacto.calcular(sim)

    assert vpf._costos(engine) == guardado  # read-only
    prediccion = {c.fila_id: (c.antes, c.despues) for c in informe.cambios if c.canal == impacto.CANAL_FUERA}
    assert set(prediccion) == {lineas[k] for k in ("p2", "p1", "combo", "parte", "pq")}
    assert {c.mes for c in informe.cambios if c.canal == impacto.CANAL_FUERA} == {date(2026, 10, 1)}

    with sessionmaker(bind=engine)() as db:
        queue.encolar_vigentes(db)
        db.commit()
    hasta = datetime.now(UTC) + timedelta(minutes=1)
    assert queue.drenar(sessionmaker(bind=engine, autoflush=False), hasta, is_transient=lambda e: False).fallidos == {}

    despues_ = vpf._costos(engine)
    assert {i for i in despues_ if despues_[i] != guardado[i]} == set(prediccion)
    assert {i: (guardado[i], despues_[i]) for i in prediccion} == prediccion
