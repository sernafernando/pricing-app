"""The T4 dry-run predicts exactly what the deploy's history recalc will store (sell-in-costo-si T4, plan
handoffs/sell-in-costo-si-t4-plan.md §2; owner L17 "cuando deployamos se debería disparar"). The same world is
measured read-only first, then recalculated for real the way the deploy does it (every product with a sell in queued,
the drain with the real area callbacks), and every stored value must equal the prediction. Invented data."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.models.ml_venta_metrica import MLVentaMetrica
from app.models.notificacion import Notificacion
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_consumo import OffsetGrupoConsumo, OffsetGrupoResumen
from app.models.offset_individual_consumo import OffsetIndividualConsumo, OffsetIndividualResumen
from app.models.producto import ProductoPricing
from app.services import recalcular_markups_service as rms
from app.services.costo_si import despues, impacto, queue, simulacion
from app.services.costo_si.despues import metricas_ml_legacy
from app.services.costo_si.despues import pricing as despues_pricing
from tests.conftest import POSTGRES_TEST_URL
from tests.services.costo_si import _world as w
from tests.services.costo_si.test_despues_pricing_postgres import _PRICING
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

D = Decimal
P, COMBO, SIN_SELL_IN = 5701, 5702, 5703
PRECIO = 250_000.0
_ML = [
    MLVentaMetrica.__table__,
    OffsetGrupo.__table__,
    OffsetGanancia.__table__,
    OffsetGrupoConsumo.__table__,
    OffsetGrupoResumen.__table__,
    OffsetIndividualConsumo.__table__,
    OffsetIndividualResumen.__table__,
    Notificacion.__table__,
]


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("costo_si_impacto", [*w.TABLES, *_PRICING, *_ML], w.STUBS, after=w.install) as engine:
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
    """The callbacks on main that re-cost what this world stores (ML legacy metrics, stored markups); shipping is
    not what this tests (every product ships at 0)."""
    monkeypatch.setattr(despues, "_CALLBACKS", {})
    monkeypatch.setattr(despues, "_cargados", True)
    despues.registrar("metricas_ml_legacy", metricas_ml_legacy.recostear)
    despues.registrar("pricing", despues_pricing.recalcular_markups)
    monkeypatch.setattr(rms, "resolver_costos_envio_batch", lambda db, ids: {})
    yield
    for tabla in ("ml_ventas_metricas", "productos_pricing", "comisiones_base", "comisiones_versiones"):
        w.run(engine, f"DELETE FROM {tabla}")
    w.clean(engine)


def _mundo(engine: Engine) -> None:
    """P: list cost USD 40 today, 25 on the day its first sell in (a 3.6 % brand bonus from 10-01) applies, so its
    costo SI is 25 from 10-01. COMBO = 2 x P. SIN_SELL_IN: list cost only. USD rate 1000 from 09-01."""
    w.producto(engine, P, costo="40")
    w.costo_lista(engine, P, datetime(2026, 9, 1), "25")
    w.producto(engine, COMBO, costo="90")
    w.producto(engine, SIN_SELL_IN, marca="OTRA", costo="10")
    w.run(engine, "UPDATE productos_erp SET iva = 21")
    w.run(
        engine,
        "INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES (:c, :p, 2)",
        c=COMBO,
        p=P,
    )
    w.tipo_cambio(engine, date(2026, 9, 1), 1000)
    w.bono_marca(engine, "3.6", date(2026, 10, 1), date(2026, 12, 31))
    w.run(engine, "DELETE FROM costo_si_dirty")  # before the deploy nothing is queued
    w.run(
        engine, "INSERT INTO comisiones_versiones (id, nombre, fecha_desde, activo) VALUES (1, 'T', '2000-01-01', true)"
    )
    w.run(engine, "INSERT INTO comisiones_base (version_id, grupo_id, comision_base) VALUES (1, 1, 12)")
    with sessionmaker(bind=engine)() as db:
        for item in (P, COMBO, SIN_SELL_IN):
            db.add(ProductoPricing(item_id=item, precio_lista_ml=PRECIO, markup_calculado=999))
        db.commit()


_ids = iter(range(810_000, 820_000))


def _venta(engine: Engine, item_id: int, cuando: datetime, cantidad: int, costo_unitario: str) -> int:
    """A stored legacy ML sale, costed the way the crons did before costo SI (list cost in pesos)."""
    op = next(_ids)
    total = D(costo_unitario) * cantidad
    w.run(
        engine,
        "INSERT INTO ml_ventas_metricas (id_operacion, item_id, fecha_venta, cantidad, monto_total, monto_limpio,"
        " costo_unitario_sin_iva, costo_total_sin_iva, ganancia, markup_porcentaje)"
        " VALUES (:op, :i, :f, :q, 200000, 150000, :u, :t, 150000 - :t, 0)",
        op=op,
        i=item_id,
        f=cuando,
        q=cantidad,
        u=D(costo_unitario),
        t=total,
    )
    return op


def _guardado(engine: Engine) -> dict:
    return {
        r[0]: r[1]
        for r in w.rows(engine, "SELECT id_operacion, costo_total_sin_iva FROM ml_ventas_metricas ORDER BY 1")
    }


_CAMPOS = [markup for _, markup in rms.MARKUPS_GUARDADOS]


def _markups(engine: Engine) -> dict:
    """(item, stored markup column) -> value."""
    filas = w.rows(engine, f"SELECT item_id, {', '.join(_CAMPOS)} FROM productos_pricing")
    return {(f[0], campo): valor for f in filas for campo, valor in zip(_CAMPOS, f[1:])}


def _deploy(engine: Engine) -> None:
    """What the T4 migration triggers: every product with a sell in queued for a whole recompute, then the drain."""
    with sessionmaker(bind=engine)() as db:
        queue.encolar_vigentes(db)
        db.commit()
    drenado = queue.drenar(
        sessionmaker(bind=engine, autoflush=False),
        datetime.now(UTC) + timedelta(minutes=1),
        is_transient=lambda exc: False,
    )
    assert drenado.fallidos == {}


def test_the_dry_run_predicts_every_ml_sale_the_deploy_re_costs_and_writes_nothing(
    engine: Engine, motor: Engine
) -> None:
    _mundo(engine)
    antes_sep = _venta(engine, P, datetime(2026, 9, 20, 12), 1, "40000")  # before its costo SI: untouched
    oct_ = _venta(engine, P, datetime(2026, 10, 15, 12), 2, "40000")
    combo = _venta(engine, COMBO, datetime(2026, 11, 2, 12), 1, "90000")
    lista = _venta(engine, SIN_SELL_IN, datetime(2026, 10, 15, 12), 1, "10000")
    ya_al_dia = _venta(engine, P, datetime(2026, 10, 20, 12), 1, "25000")  # already at its costo SI: not rewritten
    guardado = _guardado(engine)

    with simulacion.simular(motor) as sim:
        informe = impacto.calcular(sim)

    assert _guardado(engine) == guardado  # read-only
    assert informe.pasos.fallidos == {}
    assert informe.pasos.desdes == {P: date(2026, 10, 1)}
    prediccion = {c.fila_id: (c.antes, c.despues) for c in informe.cambios if c.canal == impacto.CANAL_ML_LEGACY}
    assert prediccion == {oct_: (D("80000.00"), D("50000.00")), combo: (D("90000.00"), D("50000.00"))}
    assert {c.mes for c in informe.cambios} == {date(2026, 10, 1), date(2026, 11, 1)}

    _deploy(engine)

    despues_ = _guardado(engine)
    assert {op for op in despues_ if despues_[op] != guardado[op]} == set(prediccion)
    assert {op: (guardado[op], despues_[op]) for op in prediccion} == prediccion
    assert all(despues_[op] == guardado[op] for op in (antes_sep, lista, ya_al_dia))


def test_the_dry_run_predicts_the_stored_markups_the_deploy_rewrites(engine: Engine, motor: Engine) -> None:
    _mundo(engine)
    guardado = _markups(engine)

    with simulacion.simular(motor) as sim:
        informe = impacto.calcular(sim)

    assert _markups(engine) == guardado  # read-only
    prediccion = {(m.item_id, m.campo): (m.antes, m.despues) for m in informe.markups}
    assert {(P, "markup_calculado"), (COMBO, "markup_calculado")} <= set(prediccion)
    assert {item for item, _ in prediccion} == {P, COMBO}  # no sell in: SIN_SELL_IN is not recomputed

    _deploy(engine)

    despues_ = _markups(engine)
    assert {k for k in despues_ if despues_[k] != guardado[k]} == set(prediccion)
    assert {k: (guardado[k], despues_[k]) for k in prediccion} == prediccion


def test_a_product_the_engine_cannot_compute_is_reported_with_its_reason_and_the_rest_goes_on(
    engine: Engine, motor: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mundo(engine)
    _venta(engine, P, datetime(2026, 10, 15, 12), 1, "40000")

    real = impacto.fuentes.entrada

    def falla(db, item_id):
        if item_id == P:
            raise ValueError("invoice 1: no exchange rate for 2026-10-02")
        return real(db, item_id)

    monkeypatch.setattr(impacto.fuentes, "entrada", falla)
    with simulacion.simular(motor) as sim:
        informe = impacto.calcular(sim)

    assert informe.pasos.fallidos == {P: "ValueError: invoice 1: no exchange rate for 2026-10-02"}
    assert informe.cambios == []


def test_the_script_writes_the_report_from_the_url_in_the_environment(
    engine: Engine, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from app.scripts import costo_si_t4_dry_run as script

    _mundo(engine)
    _venta(engine, P, datetime(2026, 10, 15, 12), 1, "40000")
    with engine.connect() as conn:
        esquema = conn.execute(text("SELECT current_schema()")).scalar()
    real = simulacion.motor_solo_lectura
    monkeypatch.setattr(
        simulacion,
        "motor_solo_lectura",
        lambda url: real(url, connect_args={"options": f"-csearch_path={esquema}"}),
    )
    monkeypatch.setenv("T4_URL", POSTGRES_TEST_URL)

    assert script.main(["--out", str(tmp_path), "--url-env", "T4_URL"]) == 0

    md = (tmp_path / "resumen.md").read_text()
    assert "| ml_legacy | 2026-10 | 1 | 40000.00 | 25000.00 | -15000.00 | 0 | 0.00 |" in md
    assert script.main(["--out", str(tmp_path), "--url-env", "NO_EXISTE_T4"]) == 2
