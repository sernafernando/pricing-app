"""Migration `20261128_costo_si_t4_recalculo` (sell-in-costo-si T4, owner L17: "cuando deployamos se debería
disparar"): the one-shot history recalc fired by `alembic upgrade head` on deploy. It only snapshots and enqueues; the
existing drain does the work. On a real Postgres, in a throwaway schema: the ML legacy / markups world of the dry-run
tests plus every table the recalc re-costs. Invented data."""

from __future__ import annotations

import importlib.util
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Iterator

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.models.configuracion import Configuracion
from app.models.sell_in import SellInBonoConsumo
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica
from app.models.venta_fuera_pdf import VentaFueraOperacion, VentaFueraOperacionLinea, VentaFueraPdfCarga
from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica
from app.services.costo_si import despues, queue, recompute
from app.services.costo_si.despues import ml_ventas
from app.services.ml_orders_ingestion import recongelar_costo_si as rc
from tests.services.costo_si import _world as w
from tests.services.costo_si import test_impacto_ml_congelado_postgres as tc
from tests.services.costo_si import test_impacto_postgres as tp
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261128_costo_si_t4_recalculo"
D = Decimal
_EXTRA = [
    MlOrderItemCosto.__table__,
    VentaFueraPdfCarga.__table__,
    VentaFueraOperacion.__table__,
    VentaFueraOperacionLinea.__table__,
    VentaTiendaNubeMetrica.__table__,
    VentaFueraMLMetrica.__table__,
    Configuracion.__table__,
    SellInBonoConsumo.__table__,
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
    "sell_in_bono_consumos",  # D2 follows the cost: the re-freeze drain rewrites it (`_bonos_costo`)
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


def test_upgrade_snapshots_every_re_costed_table_queues_the_scope_and_invalidates_its_steps(engine: Engine) -> None:
    venta = tp._venta(engine, tp.P, datetime(2026, 10, 5, 12), 1, "99999")
    _historia(engine)
    pasos = w.rows(
        engine, f"SELECT orden, fecha, promedio_usd, fuente_tc FROM costo_si_pasos WHERE item_id = {tp.P} ORDER BY 1"
    )
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
    # the history stays readable (same cost); only its first step is marked, so the recompute always sees a change
    assert w.rows(
        engine, f"SELECT orden, fecha, promedio_usd, fuente_tc FROM costo_si_pasos WHERE item_id = {tp.P} ORDER BY 1"
    ) == [(o, f, p, "t4_reset" if o == 0 else tc) for o, f, p, tc in pasos]
    (respaldo,) = w.rows(
        engine, f"SELECT desde, pasos FROM costo_si_backups WHERE item_id = {tp.P} AND motivo = 't4 reset'"
    )
    assert respaldo[0] == pasos[0][1]
    assert [(p["orden"], p["fecha"], p["fuente_tc"]) for p in respaldo[1]] == [
        (o, f.isoformat(), tc) for o, f, _, tc in pasos
    ]
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


def test_a_parked_product_keeps_its_pre_t4_steps_and_cost(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-closed: a product the drain cannot recompute parks with its pre-T4 history (only the first step marked),
    so every reader keeps its pre-T4 cost instead of the list cost."""
    venta = tp._venta(engine, tp.P, datetime(2026, 10, 15, 12), 2, "40000")
    _historia(engine)
    pasos = w.rows(engine, f"SELECT orden, fecha, promedio_usd FROM costo_si_pasos WHERE item_id = {tp.P} ORDER BY 1")
    guardado = tp._guardado(engine)[venta]
    _step(engine, "upgrade")

    def falla(db, item_id, **kw):
        raise RuntimeError("caido")

    monkeypatch.setattr(recompute, "recalcular", falla)
    fabrica = sessionmaker(bind=engine, autoflush=False)
    for _ in range(queue.MAX_ATTEMPTS):
        queue.drenar(fabrica, datetime.now(UTC) + timedelta(minutes=1), is_transient=lambda e: False)

    assert _cola(engine)[tp.P][1] == queue.MAX_ATTEMPTS
    assert (
        w.rows(engine, f"SELECT orden, fecha, promedio_usd FROM costo_si_pasos WHERE item_id = {tp.P} ORDER BY 1")
        == pasos
    )
    assert tp._guardado(engine)[venta] == guardado


# --- Independent verification of #2371 (handoffs/sell-in-costo-si-t4-verificacion.md): F1-F4 ---------------------

_FOTOS = {
    "ml_ventas_metricas": "SELECT id, costo_unitario_sin_iva, costo_total_sin_iva, ganancia, markup_porcentaje"
    " FROM ml_ventas_metricas ORDER BY id",
    "productos_pricing": f"SELECT item_id, {', '.join(tp._CAMPOS)} FROM productos_pricing ORDER BY item_id",
    "offset_grupo_consumo": "SELECT id, monto_offset_aplicado, monto_offset_usd FROM offset_grupo_consumo ORDER BY id",
    "offset_grupo_resumen": "SELECT id, total_monto_ars, total_monto_usd FROM offset_grupo_resumen ORDER BY id",
    "ml_order_item_costos": "SELECT id, costo_origen, moneda, tipo_cambio, tipo_cambio_fecha, costo_unitario_ars,"
    " fuente, costo_fecha FROM ml_order_item_costos ORDER BY id",
    "costo_si_pasos": "SELECT to_jsonb(p) - 'calculado_at' - 'id' FROM costo_si_pasos p ORDER BY item_id, orden",
}


def _fotos(engine: Engine) -> dict:
    return {k: w.rows(engine, sql) for k, sql in _FOTOS.items()}


def _con_recongelado(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ML re-freeze too (PR 7: `despues.ml_ventas` queues, `recongelar_costo_si.drenar` re-freezes); the D2
    bonuses it recomputes are not this world's."""
    despues.registrar("ml_ventas", ml_ventas.encolar)
    monkeypatch.setattr(rc, "_bonos_costo", lambda db, item_id: None)


def _drenar_todo(engine: Engine) -> None:
    _drenar(engine)
    hasta = datetime.now(UTC) + timedelta(minutes=1)
    assert rc.drenar(sessionmaker(bind=engine, autoflush=False), hasta, is_transient=lambda e: False).fallidos == {}


def _offsets(engine: Engine, id_operacion: int) -> None:
    w.run(engine, "INSERT INTO offset_grupos (id, nombre) VALUES (1, 'g')")
    w.run(
        engine,
        "INSERT INTO offsets_ganancia (id, tipo_offset, porcentaje, fecha_desde, grupo_id, aplica_ml)"
        " VALUES (1, 'porcentaje_costo', 10, '2026-01-01', 1, true)",
    )
    w.run(
        engine,
        "INSERT INTO offset_grupo_consumo (id, grupo_id, id_operacion, tipo_venta, fecha_venta, item_id, cantidad,"
        " offset_id, monto_offset_aplicado, monto_offset_usd, cotizacion_dolar)"
        " VALUES (1, 1, :op, 'ml', '2026-10-15', :i, 2, 1, 8000, 8, 1000)",
        op=id_operacion,
        i=tp.P,
    )
    w.run(
        engine,
        "INSERT INTO offset_grupo_resumen (id, grupo_id, total_monto_ars, total_monto_usd) VALUES (1, 1, 8000, 8)",
    )


def test_f1_a_product_whose_sell_in_is_gone_gets_its_sales_back_to_list_cost(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F1: P has stored steps, then its bonus is deleted (the trigger queues it) before the drain ran. Its stored
    steps must still trigger the callbacks (history gone = a change), as they would without T4."""
    w.factura(engine, tp.P, date(2026, 10, 5), datetime(2026, 10, 5, 10), 10, "30", previo=0)
    venta = tp._venta(engine, tp.P, datetime(2026, 10, 15, 12), 2, "40000")
    _historia(engine)
    con_si = tp._guardado(engine)[venta]
    w.run(engine, "DELETE FROM sell_in_bonos_marca")

    _step(engine, "upgrade")
    _drenar(engine)

    assert con_si != tp._guardado(engine)[venta] == D("50000.00")  # list 25 USD x 1000 x 2, as without T4
    assert w.rows(engine, f"SELECT count(*) FROM costo_si_pasos WHERE item_id = {tp.P}") == [(0,)]


def test_f2_a_parked_product_re_queued_after_the_fix_re_freezes_the_sales_of_the_window(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2: P parks, a sale is frozen meanwhile at list cost, the cause is
    fixed: `REENCOLAR_SQL` (also after the product was recomputed once) makes the drain re-dispatch from the first step, so the window sale gets its costo SI."""
    _con_recongelado(monkeypatch)
    tc._congelada(engine, tp.P, datetime(2026, 10, 15, 15, tzinfo=UTC), 1, "25000", "costo_si")
    _historia(engine)
    _drenar_todo(engine)
    _step(engine, "upgrade")
    real = recompute.recalcular

    def falla(db, item_id, **kw):
        if item_id == tp.P:
            raise RuntimeError("caido")
        return real(db, item_id, **kw)

    monkeypatch.setattr(recompute, "recalcular", falla)
    fabrica = sessionmaker(bind=engine, autoflush=False)
    for _ in range(queue.MAX_ATTEMPTS):
        queue.drenar(fabrica, datetime.now(UTC) + timedelta(minutes=1), is_transient=lambda e: False)
    assert _cola(engine)[tp.P][1] == queue.MAX_ATTEMPTS
    ventana = tc._congelada(engine, tp.P, datetime(2026, 11, 3, 15, tzinfo=UTC), 1, "40000", "erp_publicacion")
    monkeypatch.setattr(recompute, "recalcular", real)

    w.run(engine, _module().REENCOLAR_SQL, item=tp.P)
    _drenar_todo(engine)

    (fila,) = w.rows(engine, f"SELECT fuente FROM ml_order_item_costos WHERE order_id = {ventana}")
    assert fila[0] != "erp_publicacion"
    assert w.rows(engine, f"SELECT count(*) FROM costo_si_pasos WHERE item_id = {tp.P}") != [(0,)]
    assert _cola(engine) == {}


def test_f3_f4_the_rollback_sql_restores_every_re_costed_value_and_keeps_later_offset_increments(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F3/F4: `ROLLBACK_SQL` (the PR's documented rollback, in order) brings back every value the recalc rewrote,
    the steps included; an offset resumen keeps what was added to it after the deploy."""
    _con_recongelado(monkeypatch)
    venta = tp._venta(engine, tp.P, datetime(2026, 10, 15, 12), 2, "40000")
    tc._congelada(engine, tp.P, datetime(2026, 10, 15, 15, tzinfo=UTC), 2, "40000", "erp_publicacion")
    _offsets(engine, venta)
    _historia(engine)
    # stale stored values the recalc rewrites (the history is already stored: only the reset makes callbacks fire)
    w.run(
        engine,
        "UPDATE ml_ventas_metricas SET costo_unitario_sin_iva = 40000, costo_total_sin_iva = 80000"
        f" WHERE id_operacion = {venta}",
    )
    w.run(engine, "UPDATE offset_grupo_consumo SET monto_offset_aplicado = 8000, monto_offset_usd = 8")
    w.run(engine, "UPDATE offset_grupo_resumen SET total_monto_ars = 8000, total_monto_usd = 8")
    w.run(
        engine,
        "UPDATE ml_order_item_costos SET costo_unitario_ars = 40000, costo_origen = 40, fuente = 'erp_publicacion',"
        " costo_fecha = NULL",
    )
    w.run(engine, "UPDATE productos_pricing SET markup_calculado = 999")
    antes = _fotos(engine)
    _step(engine, "upgrade")
    _drenar_todo(engine)
    despues_ = _fotos(engine)
    assert {k for k in antes if antes[k] != despues_[k]} >= {
        "ml_ventas_metricas",
        "productos_pricing",
        "offset_grupo_consumo",
        "offset_grupo_resumen",
        "ml_order_item_costos",
    }
    w.run(engine, "UPDATE offset_grupo_resumen SET total_monto_ars = total_monto_ars + 500")  # a later sale

    for sentencia in _module().ROLLBACK_SQL:
        w.run(engine, sentencia)

    restaurado = _fotos(engine)
    resumen = restaurado.pop("offset_grupo_resumen")
    previo = antes.pop("offset_grupo_resumen")
    assert restaurado == antes
    assert [(i, ars - 500, usd) for i, ars, usd in resumen] == previo


@pytest.mark.parametrize(
    "variante,esperado",
    [
        pytest.param("combo", None, id="became_a_combo"),  # in scope (bonus still active), entrada None
        pytest.param("compra_sin_factura", D("50000.00"), id="sell_in_without_invoice"),
    ],
)
def test_f1_recheck_a_product_in_scope_the_engine_cannot_compute_ends_as_without_t4(
    engine: Engine, variante: str, esperado
) -> None:
    """Recheck of F1: a product with a live reason but no computable entrada (a combo; a Compras sell in whose
    purchase has no invoice yet) and stale stored steps ends exactly as a plain drain without T4 leaves it."""
    w.factura(engine, tp.P, date(2026, 10, 5), datetime(2026, 10, 5, 10), 10, "30", previo=0)
    venta = tp._venta(engine, tp.P, datetime(2026, 10, 15, 12), 2, "40000")
    _historia(engine)
    con_si = tp._guardado(engine)[venta]
    if variante == "combo":
        w.run(
            engine,
            f"INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES ({tp.P}, {tp.Q}, 1)",
        )
    else:
        w.run(engine, "DELETE FROM sell_in_bonos_marca")
        w.run(engine, "INSERT INTO pedidos_compra (id, tipo_cambio) VALUES (987654, NULL)")
        w.sell_in_compra(engine, tp.P, 987654, "5", date(2026, 11, 1))

    _step(engine, "upgrade")
    _drenar(engine)

    assert con_si != esperado
    assert tp._guardado(engine)[venta] == esperado


def test_f2_reencolar_re_dispatches_a_product_already_recomputed_after_t4(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2: `REENCOLAR_SQL` on a product whose current history the drain already stored (the T4 mark is gone) still
    re-dispatches from its first step: a sale frozen at list cost meanwhile gets its costo SI."""
    _con_recongelado(monkeypatch)
    tc._congelada(engine, tp.P, datetime(2026, 10, 15, 15, tzinfo=UTC), 1, "25000", "costo_si")
    _historia(engine)
    _step(engine, "upgrade")
    _drenar_todo(engine)
    assert w.rows(engine, "SELECT count(*) FROM costo_si_pasos WHERE fuente_tc = 't4_reset'") == [(0,)]
    ventana = tc._congelada(engine, tp.P, datetime(2026, 11, 3, 15, tzinfo=UTC), 1, "40000", "erp_publicacion")

    w.run(engine, _module().REENCOLAR_SQL, item=tp.P)
    _drenar_todo(engine)

    (fila,) = w.rows(engine, f"SELECT fuente FROM ml_order_item_costos WHERE order_id = {ventana}")
    assert fila[0] != "erp_publicacion"
