"""The T4 dry-run predicts the ML sale costs the deploy re-freezes (`ml_order_item_costos`, sell-in-costo-si T3 PR 7
`recongelar_costo_si`; T4 plan §2, orchestrator G1: "PR 7 lands before T4 — build against its interface"). The same
world is measured read-only, then recalculated as the deploy does (costo SI drain, then PR 7's re-freeze drain), and
every stored row must equal the prediction. Invented data."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.services.costo_si import despues, impacto, queue, simulacion
from app.services.costo_si.despues import ml_ventas
from app.services.ml_orders_ingestion import recongelar_costo_si as rc
from tests.conftest import POSTGRES_TEST_URL
from tests.services.costo_si import _world as w
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

D = Decimal
P, COMBO, SIN_SELL_IN, SIN_COSTO, COMBO_SIN_COSTO, PC = 5801, 5802, 5803, 5804, 5805, 5806
_ids = iter(range(830_000, 840_000))


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("costo_si_impacto_ml", w.TABLES, w.STUBS, after=w.install) as engine:
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
    monkeypatch.setattr(despues, "_CALLBACKS", {})
    monkeypatch.setattr(despues, "_cargados", True)
    despues.registrar("ml_ventas", ml_ventas.encolar)
    yield
    w.clean(engine)


def _mundo(engine: Engine) -> None:
    """P: list cost USD 40 today, 25 when its first sell in (a brand bonus from 10-01) applies: costo SI 25 from
    10-01. COMBO = 2 x P. SIN_SELL_IN: list cost only. PC (cat 47, own list cost USD 300) = 1 x P + 1 x SIN_SELL_IN,
    the reader's 'lista' sum (L22). USD rate 1000 from 09-01."""
    w.producto(engine, P, costo="40")
    w.costo_lista(engine, P, datetime(2026, 9, 1), "25")
    w.producto(engine, COMBO, costo="90")
    w.producto(engine, SIN_SELL_IN, marca="OTRA", costo="10")
    w.producto(engine, SIN_COSTO, marca="OTRA", costo="0")  # no cost anywhere
    w.producto(engine, COMBO_SIN_COSTO, costo="0")
    w.producto(engine, PC, cat_id=47, costo="300")
    w.run(engine, "UPDATE productos_erp SET iva = 21")
    partes = ((COMBO, P, 2), (COMBO_SIN_COSTO, P, 1), (COMBO_SIN_COSTO, SIN_COSTO, 1), (PC, P, 1), (PC, SIN_SELL_IN, 1))
    for combo, componente, cantidad in partes:
        w.run(
            engine,
            "INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES (:c, :p, :q)",
            c=combo,
            p=componente,
            q=cantidad,
        )
    w.tipo_cambio(engine, date(2026, 9, 1), 1000)
    w.bono_marca(engine, "3.6", date(2026, 10, 1), date(2026, 12, 31))
    w.run(engine, "DELETE FROM costo_si_dirty")


def _congelada(engine: Engine, item_id: int, cuando: datetime, cantidad: int, unitario: str, fuente: str) -> int:
    """A sale frozen before costo SI: USD list cost x the sale-date rate 1000, as `congelar` stored it."""
    order_id = next(_ids)
    mla = f"MLA{order_id}"
    w.run(
        engine,
        "INSERT INTO ml_orders_ops (order_id, status, date_created) VALUES (:o, 'paid', :c)",
        o=order_id,
        c=cuando,
    )
    w.run(
        engine,
        "INSERT INTO ml_order_items_ops (order_id, item_id, variation_id, quantity) VALUES (:o, :m, NULL, :q)",
        o=order_id,
        m=mla,
        q=cantidad,
    )
    w.run(
        engine,
        "INSERT INTO ml_order_item_costos (order_id, item_id, variation_id, costo_origen, moneda, tipo_cambio,"
        " tipo_cambio_fecha, costo_unitario_ars, iva_pct, precio_unitario, costo_fecha, fuente, producto_item_id)"
        " VALUES (:o, :m, NULL, :u / 1000, 'USD', 1000, '2026-09-01', :u, 21, 100000, NULL, :f, :i)",
        o=order_id,
        m=mla,
        u=D(unitario),
        f=fuente,
        i=item_id,
    )
    return order_id


def _guardado(engine: Engine) -> dict:
    return {
        r[0]: r[1:] for r in w.rows(engine, "SELECT order_id, costo_unitario_ars, fuente FROM ml_order_item_costos")
    }


def _deploy(engine: Engine) -> None:
    with sessionmaker(bind=engine)() as db:
        queue.encolar_vigentes(db)
        db.commit()
    hasta = datetime.now(UTC) + timedelta(minutes=1)
    assert queue.drenar(sessionmaker(bind=engine, autoflush=False), hasta, is_transient=lambda e: False).fallidos == {}
    assert rc.drenar(sessionmaker(bind=engine, autoflush=False), hasta, is_transient=lambda e: False).fallidos == {}


def test_the_dry_run_predicts_every_ml_sale_the_deploy_re_freezes(engine: Engine, motor: Engine) -> None:
    _mundo(engine)
    antes = _congelada(engine, P, datetime(2026, 9, 20, 15, tzinfo=UTC), 1, "40000", "erp_publicacion")
    oct_ = _congelada(engine, P, datetime(2026, 10, 15, 15, tzinfo=UTC), 2, "40000", "erp_publicacion")
    combo = _congelada(engine, COMBO, datetime(2026, 11, 2, 15, tzinfo=UTC), 1, "90000", "combo")
    lista = _congelada(engine, SIN_SELL_IN, datetime(2026, 10, 15, 15, tzinfo=UTC), 1, "10000", "erp_publicacion")
    # A combo sold before P's costo SI starts: its list-cost sum (2 x 25) differs from what it froze, but it is
    # before the date the recompute hands the callback, so it stays.
    combo_antes = _congelada(engine, COMBO, datetime(2026, 9, 20, 15, tzinfo=UTC), 1, "80000", "combo")
    # A combo with a component that has no cost: unknown on its date, the re-freeze keeps what it froze.
    desconocido = _congelada(engine, COMBO_SIN_COSTO, datetime(2026, 10, 20, 15, tzinfo=UTC), 1, "40000", "combo")
    # A PC frozen before L22 at its own list cost (300 x 1000): the deploy re-freezes it to its components' sum.
    pc = _congelada(engine, PC, datetime(2026, 11, 2, 15, tzinfo=UTC), 1, "300000", "erp_publicacion")
    guardado = _guardado(engine)

    with simulacion.simular(motor) as sim:
        informe = impacto.calcular(sim)

    assert _guardado(engine) == guardado  # read-only
    prediccion = {c.fila_id: (c.antes, c.despues) for c in informe.cambios if c.canal == impacto.CANAL_ML_CONGELADO}
    filas = {r[0]: r[1] for r in w.rows(engine, "SELECT id, order_id FROM ml_order_item_costos")}
    assert {filas[i] for i in prediccion} == {oct_, combo, pc}
    assert prediccion[next(i for i, o in filas.items() if o == oct_)] == (D("80000.0000"), D("48200.0000"))
    assert prediccion[next(i for i, o in filas.items() if o == pc)] == (D("300000.0000"), D("34100.0000"))  # 24.1 + 10

    _deploy(engine)

    despues_ = _guardado(engine)
    assert {o for o in despues_ if despues_[o] != guardado[o]} == {oct_, combo, pc}
    assert despues_[pc] == (D("34100.0000"), "combo")
    for fila_id, (antes_, despues_total) in prediccion.items():
        order_id = filas[fila_id]
        cantidad = 2 if order_id == oct_ else 1
        assert (guardado[order_id][0] * cantidad, despues_[order_id][0] * cantidad) == (antes_, despues_total)
    assert all(despues_[o] == guardado[o] for o in (antes, lista, combo_antes, desconocido))
