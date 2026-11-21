"""The T4 dry-run predicts the stored GBP metrics the deploy re-costs: Tienda Nube (`ventas_tienda_nube_metricas`)
and ventas fuera ML (`ventas_fuera_ml_metricas`), through the callbacks of sell-in-costo-si T3 PR 9 (#2364,
`costo_si_metricas_gbp`). PR 9's world (P gets a brand loyalty from 10-01) plus GBP invoices of both channels: P
before the change, P after it, another product, a GBP group of P and a combo of P. The crons store them at the cost
before the deploy; the dry-run measures read-only, then the drain recalculates as the deploy does; every stored row
must equal the prediction. Invented data."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.scripts import agregar_metricas_fuera_ml as cron_fuera
from app.scripts import agregar_metricas_tienda_nube as cron_tn
from app.services import costo_si_metricas_gbp as gbp
from app.services.costo_si import despues, impacto, queue, simulacion
from tests.conftest import POSTGRES_TEST_URL
from tests.scripts import test_metricas_fuera_tn_costo_si_postgres as m
from tests.services.costo_si import _world as w
from tests.services.ventas_fuera_pdf import test_costo_si_despues_postgres as vpf
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

P, OTRO, COMBO = vpf.P, vpf.OTRO, vpf.COMBO
CANALES = [
    (impacto.CANAL_FUERA_GBP, m.DF_FUERA, gbp.FUERA, cron_fuera, cron_fuera.obtener_ventas_fuera_ml),
    (impacto.CANAL_TN, m.DF_TN, gbp.TN, cron_tn, cron_tn.obtener_ventas_tienda_nube),
]


def _tablas() -> list:
    vistas, tablas = set(), []
    for tabla in [*vpf._tablas(), *m.TABLAS]:
        if tabla.name not in vistas:
            vistas.add(tabla.name)
            tablas.append(tabla)
    return tablas


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    stubs = vpf._STUBS  # it already creates `usuarios`, the GBP world's only stub
    with throwaway_schema("costo_si_impacto_gbp", _tablas(), stubs, after=vpf._install) as engine:
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
    monkeypatch.setattr(despues, "_CALLBACKS", {gbp.FUERA: gbp.recostear_fuera, gbp.TN: gbp.recostear_tn})
    monkeypatch.setattr(despues, "_cargados", True)
    yield
    w.run(
        engine,
        "TRUNCATE ventas_fuera_linea_overrides, ventas_fuera_operacion_lineas, ventas_fuera_operaciones,"
        " ventas_fuera_pdf_cargas, sell_dirty, ventas_fuera_ml_metricas, ventas_tienda_nube_metricas,"
        " tb_cur_exch_history CASCADE",
    )
    w.clean(engine)


def _costos(engine: Engine) -> dict:
    out = {}
    for canal, _df, tabla, _cron, _obtener in CANALES:
        for fila_id, costo, tc in w.rows(engine, f"SELECT id, costo_total, cotizacion_dolar FROM {tabla}"):
            out[(canal, fila_id)] = (costo, tc)
    return out


def test_the_dry_run_predicts_every_gbp_metric_the_deploy_re_costs(engine: Engine, motor: Engine) -> None:
    vpf._mundo(engine)
    # A purchase on 10-02 under the loyalty: P's costo SI leaves its list cost from that date (10 at 35 x 0.964).
    w.factura(engine, P, date(2026, 10, 2), datetime(2026, 10, 2, 10), 10, "35", previo=0)
    esperadas = set()
    for canal, df_id, tabla, cron, obtener in CANALES:
        (antes,) = m._venta(engine, df_id, [{"item": P, "precio": "30000"}], dia=datetime(2026, 9, 20))
        p, otro = m._venta(engine, df_id, [{"item": P, "precio": "30000"}, {"item": OTRO}], dia=datetime(2026, 10, 5))
        principal, *_ = m._venta(engine, df_id, m._grupo(None, [(P, "1"), (OTRO, "1")]), dia=datetime(2026, 10, 6))
        (combo,) = m._venta(engine, df_id, [{"item": COMBO, "precio": "90000"}], dia=datetime(2026, 10, 7))
        (solo_tc,) = m._venta(engine, df_id, [{"item": P, "precio": "30000"}], dia=datetime(2026, 10, 1))
        with sessionmaker(bind=engine, autoflush=False)() as db:
            cron.process_and_insert(db, obtener(db, "2026-09-01 00:00:00", "2026-10-31 23:59:59"))
            db.commit()
        ids = dict(w.rows(engine, f"SELECT it_transaction, id FROM {tabla}"))
        # P after the change, the group holding P (the crons store its principal line), the combo of P; not P
        # before the change nor OTRO alone
        esperadas |= {(canal, ids[it]) for it in (p, principal, combo, solo_tc)}
        # P on 10-01 keeps its cost (the purchase is on 10-02); only its stored rate is stale: rewritten, delta 0
        w.run(engine, f"UPDATE {tabla} SET cotizacion_dolar = 999 WHERE it_transaction = :i", i=solo_tc)
        assert ids[antes] and ids[otro]
    w.run(engine, "DELETE FROM costo_si_dirty")  # before the deploy nothing is queued
    guardado = _costos(engine)

    with simulacion.simular(motor) as sim:
        informe = impacto.calcular(sim)

    assert _costos(engine) == guardado  # read-only
    prediccion = {
        (c.canal, c.fila_id): (c.antes, c.despues)
        for c in informe.cambios
        if c.canal in (impacto.CANAL_FUERA_GBP, impacto.CANAL_TN)
    }
    with sessionmaker(bind=engine)() as db:
        queue.encolar_vigentes(db)
        db.commit()
    hasta = datetime.now(UTC) + timedelta(minutes=1)
    assert queue.drenar(sessionmaker(bind=engine, autoflush=False), hasta, is_transient=lambda e: False).fallidos == {}

    despues_ = _costos(engine)
    cambiadas = {k for k in despues_ if despues_[k] != guardado[k]}
    assert cambiadas == esperadas
    assert set(prediccion) == cambiadas
    assert {k: (guardado[k][0], despues_[k][0]) for k in prediccion} == prediccion
    assert {c.mes for c in informe.cambios if c.canal == impacto.CANAL_TN} == {date(2026, 10, 1)}
    assert all(isinstance(v, Decimal) for v, _tc in despues_.values() if v is not None)
