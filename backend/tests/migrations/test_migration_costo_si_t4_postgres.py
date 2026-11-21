"""Migration `20261128_costo_si_t4_recalculo` (sell-in-costo-si T4, owner L17: "cuando deployamos se debería
disparar"): the one-shot history recalc fired by `alembic upgrade head` on deploy. It only snapshots and enqueues; the
existing drain does the work. On a real Postgres, in a throwaway schema: the ML legacy / markups world of the dry-run
tests plus every table the recalc re-costs. Invented data."""

from __future__ import annotations

import importlib.util
import os
from datetime import UTC, date, datetime, timedelta
from typing import Iterator

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.models.configuracion import Configuracion
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica
from app.models.venta_fuera_pdf import VentaFueraOperacion, VentaFueraOperacionLinea, VentaFueraPdfCarga
from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica
from app.services.costo_si import queue
from tests.services.costo_si import _world as w
from tests.services.costo_si import test_impacto_postgres as tp
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261128_costo_si_t4_recalculo"
_EXTRA = [
    MlOrderItemCosto.__table__,
    VentaFueraPdfCarga.__table__,
    VentaFueraOperacion.__table__,
    VentaFueraOperacionLinea.__table__,
    VentaTiendaNubeMetrica.__table__,
    VentaFueraMLMetrica.__table__,
    Configuracion.__table__,
]
# Every table whose stored values the recalc re-costs (plan §1.5, orchestrator G4)
RESPALDADAS = [
    "productos_pricing",
    "ml_order_item_costos",
    "ml_ventas_metricas",
    "offset_grupo_consumo",
    "offset_individual_consumo",
    "offset_grupo_resumen",
    "offset_individual_resumen",
    "ventas_fuera_operacion_lineas",
    "ventas_tienda_nube_metricas",
    "ventas_fuera_ml_metricas",
]
OTRO = 5799  # queued by a trigger before the deploy, outside the scope: left as it is


def _module():
    path = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
    spec = importlib.util.spec_from_file_location(f"{_REVISION}_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    tablas = list({t.name: t for t in [*w.TABLES, *tp._PRICING, *tp._ML, *_EXTRA]}.values())
    with throwaway_schema("costo_si_t4_mig", tablas, w.STUBS, after=w.install) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _mundo(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from app.services import recalcular_markups_service as rms
    from app.services.costo_si import despues
    from app.services.costo_si.despues import metricas_ml_legacy
    from app.services.costo_si.despues import pricing as despues_pricing

    monkeypatch.setattr(despues, "_CALLBACKS", {})
    monkeypatch.setattr(despues, "_cargados", True)
    despues.registrar("metricas_ml_legacy", metricas_ml_legacy.recostear)
    despues.registrar("pricing", despues_pricing.recalcular_markups)
    monkeypatch.setattr(rms, "resolver_costos_envio_batch", lambda db, ids: {})
    tp._mundo(engine)
    yield
    for tabla in RESPALDADAS:
        w.run(engine, f"DROP TABLE IF EXISTS costo_si_t4_respaldo_{tabla}")
    for tabla in (
        "ml_ventas_metricas",
        "productos_pricing",
        "comisiones_base",
        "comisiones_versiones",
        "configuracion",
    ):
        w.run(engine, f"DELETE FROM {tabla}")
    w.clean(engine)


def _drenar(engine: Engine) -> None:
    hasta = datetime.now(UTC) + timedelta(minutes=1)
    assert queue.drenar(sessionmaker(bind=engine, autoflush=False), hasta, is_transient=lambda e: False).fallidos == {}


def _historia(engine: Engine) -> None:
    """A costo SI history already stored before T4 (T2 deployed earlier): the daily pass queues, the drain stores."""
    with sessionmaker(bind=engine)() as db:
        queue.encolar_vigentes(db)
        db.commit()
    _drenar(engine)


def _cola(engine: Engine) -> dict:
    return {r[0]: r[1:] for r in w.rows(engine, "SELECT item_id, desde, attempts, last_error FROM costo_si_dirty")}


def test_upgrade_snapshots_every_re_costed_table_queues_the_scope_and_resets_its_steps(engine: Engine) -> None:
    venta = tp._venta(engine, tp.P, datetime(2026, 10, 5, 12), 1, "99999")
    _historia(engine)
    pasos = w.rows(engine, f"SELECT orden, fecha, promedio_usd FROM costo_si_pasos WHERE item_id = {tp.P} ORDER BY 1")
    assert pasos
    w.run(
        engine,
        "INSERT INTO costo_si_dirty (item_id, desde, attempts, last_error) VALUES (:i, '2026-11-01', 3, 'x')",
        i=OTRO,
    )
    w.run(
        engine,
        f"INSERT INTO costo_si_dirty (item_id, desde, attempts, last_error) VALUES ({tp.P}, '2026-11-01', 4,"
        " 'caido') ON CONFLICT (item_id) DO UPDATE SET attempts = 4, last_error = 'caido'",
    )
    with sessionmaker(bind=engine)() as db:
        alcance = set(queue.productos_vigentes(db))
    antes = {t: w.rows(engine, f"SELECT to_jsonb(t) FROM {t} t ORDER BY 1") for t in RESPALDADAS}

    _step(engine, "upgrade")

    for t in RESPALDADAS:
        assert w.rows(engine, f"SELECT to_jsonb(t) FROM costo_si_t4_respaldo_{t} t ORDER BY 1") == antes[t], t
    assert w.rows(engine, f"SELECT count(*) FROM ml_ventas_metricas WHERE id_operacion = {venta}") == [(1,)]
    cola = _cola(engine)
    assert cola[tp.P] == (None, 0, None)  # the whole history, a fresh retry budget
    assert cola[OTRO] == (date(2026, 11, 1), 3, "x")
    assert set(cola) == alcance | {OTRO} and all(cola[i] == (None, 0, None) for i in alcance)
    assert w.rows(engine, f"SELECT count(*) FROM costo_si_pasos WHERE item_id = {tp.P}") == [(0,)]
    (respaldo,) = w.rows(
        engine, f"SELECT desde, pasos FROM costo_si_backups WHERE item_id = {tp.P} AND motivo = 't4 reset'"
    )
    assert respaldo[0] == pasos[0][1]
    assert [(p["orden"], p["fecha"]) for p in respaldo[1]] == [(o, f.isoformat()) for o, f, _ in pasos]
    (marca,) = w.rows(engine, "SELECT valor FROM configuracion WHERE clave = 'costo_si_t4_encolado_at'")
    assert marca[0]


def test_the_drain_after_it_re_costs_even_a_history_that_did_not_change(engine: Engine) -> None:
    """Plan §1.3: with the steps already stored, a plain re-queue changes nothing and no callback runs; the reset
    makes every product re-dispatch from its first step, so a stale stored sale is re-costed."""
    venta = tp._venta(engine, tp.P, datetime(2026, 10, 5, 12), 1, "99999")
    _historia(engine)
    correcto = tp._guardado(engine)[venta]
    w.run(
        engine,
        f"UPDATE ml_ventas_metricas SET costo_unitario_sin_iva = 1, costo_total_sin_iva = 1"
        f" WHERE id_operacion = {venta}",
    )
    _historia(engine)
    assert tp._guardado(engine)[venta] == 1  # without the reset: nothing re-costed

    _step(engine, "upgrade")
    _drenar(engine)

    assert tp._guardado(engine)[venta] == correcto
    assert _cola(engine) == {}


def test_a_second_upgrade_keeps_the_first_snapshot_and_backs_up_no_step_twice(engine: Engine) -> None:
    tp._venta(engine, tp.P, datetime(2026, 10, 5, 12), 1, "99999")
    _historia(engine)
    _step(engine, "upgrade")
    primera = w.rows(engine, "SELECT to_jsonb(t) FROM costo_si_t4_respaldo_ml_ventas_metricas t ORDER BY 1")
    marca = w.rows(engine, "SELECT valor FROM configuracion WHERE clave = 'costo_si_t4_encolado_at'")
    w.run(engine, "UPDATE ml_ventas_metricas SET costo_total_sin_iva = 7")

    _step(engine, "upgrade")

    assert w.rows(engine, "SELECT to_jsonb(t) FROM costo_si_t4_respaldo_ml_ventas_metricas t ORDER BY 1") == primera
    assert w.rows(engine, "SELECT count(*) FROM costo_si_backups WHERE motivo = 't4 reset'") == [(1,)]
    assert w.rows(engine, "SELECT valor FROM configuracion WHERE clave = 'costo_si_t4_encolado_at'") == marca
    assert _cola(engine)[tp.P] == (None, 0, None)


def test_downgrade_keeps_the_snapshots_and_the_queue(engine: Engine) -> None:
    """A data migration: nothing to undo automatically; restoring a snapshot is a manual, deliberate step."""
    _step(engine, "upgrade")
    cola = _cola(engine)

    _step(engine, "downgrade")

    assert w.rows(engine, "SELECT count(*) FROM costo_si_t4_respaldo_productos_pricing") == [(3,)]
    assert _cola(engine) == cola
