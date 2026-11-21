"""Legacy ML metrics at costo SI (sell-in-costo-si T3 PR 8; spec handoffs/sell-in-costo-si-feature.md S10, S11, S13,
D3, D4; owner L14, L15, L18; plan handoffs/sell-in-costo-si-t3-pr8-plan.md).

The metrics crons (`agregar_metricas_ml_incremental`, `_diario` through it, `_local`) and the /ventas-ml live query
cost every ML sale at the costo SI in force on the sale date (list cost when there is none, Q1), combos as their
components (S11), in the product's cost currency converted at the sale date's rate (L18). TP-Link list 8 keeps its own
cost (D3). The dashboard and rentabilidad totals follow the stored rows. Invented data."""

from __future__ import annotations

import asyncio
import io

from datetime import date, datetime
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.endpoints import ventas_ml
from app.scripts import agregar_metricas_ml_incremental as incremental
from app.scripts import agregar_metricas_ml_local as local
from tests.services.metricas_ml_legacy import _world as w

pytestmark = pytest.mark.postgres

D = Decimal
A, B, ARSP, SIN, COMBO = 6101, 6102, 6103, 6104, 6111
DESDE, HASTA = datetime(2026, 9, 1), datetime(2026, 10, 31, 23, 59, 59)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("metricas_ml_costo_si") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


@pytest.fixture()
def db(engine: Engine) -> Iterator[Session]:
    with sessionmaker(bind=engine)() as session:
        yield session


def _mundo(engine: Engine) -> None:
    """A (USD): list cost 30 since 09-01, costo SI 25 from 10-01 and 22.757 from 10-10. B (USD): costo SI 10 from 10-01.
    ARSP (ARS cost): costo SI 15000 ARS from 10-01, list 14000 ARS. SIN (USD): no costo SI, list 35. COMBO = 2 A + B,
    no cost of its own. USD rate 1000 from 09-01, 1500 from 10-10."""
    w.producto(engine, A, costo="30")
    w.producto(engine, B, costo="11")
    w.producto(engine, ARSP, moneda="ARS", costo="14000")
    w.producto(engine, SIN, costo="35")
    w.producto(engine, COMBO)
    w.combo(engine, COMBO, {A: 2, B: 1})
    w.costo_lista(engine, A, datetime(2026, 9, 1, 9), "30")
    w.costo_lista(engine, B, datetime(2026, 9, 1, 9), "11")
    w.costo_lista(engine, ARSP, datetime(2026, 9, 1, 9), "14000", curr_id=1)
    w.costo_lista(engine, SIN, datetime(2026, 9, 1, 9), "35")
    w.paso(engine, A, 0, date(2026, 10, 1), "25.00000")
    w.paso(engine, A, 1, date(2026, 10, 10), "22.75700")
    w.paso(engine, B, 0, date(2026, 10, 1), "10.00000")
    w.paso(engine, ARSP, 0, date(2026, 10, 1), "15000.00000", moneda="ARS")
    w.tipo_cambio(engine, date(2026, 9, 1), 1000)
    w.tipo_cambio(engine, date(2026, 10, 10), 1500)


def _cron(db: Session, modulo=incremental) -> None:
    filas = modulo.calcular_metricas_locales(db, DESDE, HASTA)
    modulo.process_and_insert(db, filas)
    db.commit()


# --------------------------------------------------------------------------------------------------- the crons


def test_cron_costs_a_usd_sale_at_the_costo_si_in_force_on_its_date(engine: Engine, db: Session) -> None:
    """S13/L14: the sale takes costo SI (25 USD on 10-05, 22.757 USD on 10-12), not the list cost (30 USD), at the sale
    date's rate (1000, then 1500); ganancia and markup follow the new cost."""
    _mundo(engine)
    antes = w.venta_ml(engine, A, datetime(2026, 10, 5, 15), cantidad=2)
    despues = w.venta_ml(engine, A, datetime(2026, 10, 12, 11))

    _cron(db)

    m = w.metrica(engine, antes)
    assert m["costo_unitario_sin_iva"] == D("25000")
    assert m["costo_total_sin_iva"] == D("50000")
    assert m["ganancia"] == m["monto_limpio"] - m["costo_total_sin_iva"]
    assert m["markup_porcentaje"] == round((m["monto_limpio"] / D("50000") - 1) * 100, 2)
    assert w.metrica(engine, despues)["costo_unitario_sin_iva"] == D("34135.5")


def test_cron_keeps_an_ars_cost_in_pesos_without_a_rate(engine: Engine, db: Session) -> None:
    """L18: an ARS-cost product's costo SI is already pesos: 15000, never x the USD rate."""
    _mundo(engine)
    venta = w.venta_ml(engine, ARSP, datetime(2026, 10, 12, 11))

    _cron(db)

    assert w.metrica(engine, venta)["costo_unitario_sin_iva"] == D("15000")


def test_cron_costs_a_combo_as_its_components(engine: Engine, db: Session) -> None:
    """S11: the combo line has no cost of its own: (2 x 25 + 10) USD x 1000 on 10-05."""
    _mundo(engine)
    venta = w.venta_ml(engine, COMBO, datetime(2026, 10, 5, 15))

    _cron(db)

    assert w.metrica(engine, venta)["costo_unitario_sin_iva"] == D("60000")


def test_cron_uses_the_list_cost_when_there_is_no_costo_si(engine: Engine, db: Session) -> None:
    """Q1: no costo SI -> the reader's list cost on that date (35 USD x 1000); before A's first step, A's list cost."""
    _mundo(engine)
    sin = w.venta_ml(engine, SIN, datetime(2026, 10, 5, 15))
    previa = w.venta_ml(engine, A, datetime(2026, 9, 20, 10))

    _cron(db)

    assert w.metrica(engine, sin)["costo_unitario_sin_iva"] == D("35000")
    assert w.metrica(engine, previa)["costo_unitario_sin_iva"] == D("30000")


def test_local_cron_costs_like_the_incremental(engine: Engine, db: Session) -> None:
    """The third copy of the SQL (7d/30d re-runs) reads the same cost."""
    _mundo(engine)
    ventas = [
        w.venta_ml(engine, A, datetime(2026, 10, 5, 15), cantidad=2),
        w.venta_ml(engine, ARSP, datetime(2026, 10, 12, 11)),
        w.venta_ml(engine, COMBO, datetime(2026, 10, 5, 15)),
    ]

    _cron(db, local)

    assert [w.metrica(engine, v)["costo_unitario_sin_iva"] for v in ventas] == [D("25000"), D("15000"), D("60000")]


def test_cron_rerun_picks_up_a_costo_si_change(engine: Engine, db: Session) -> None:
    """L15 inside the window: a step loaded later for 10-03 re-costs the stored sale on the next run."""
    _mundo(engine)
    venta = w.venta_ml(engine, A, datetime(2026, 10, 5, 15))
    _cron(db)
    w.paso(engine, A, 5, date(2026, 10, 3), "20.00000")

    _cron(db, local)

    assert w.metrica(engine, venta)["costo_unitario_sin_iva"] == D("20000")


# --------------------------------------------------------------------------------------------------- /ventas-ml


async def _leer(respuesta) -> bytes:
    return b"".join([parte async for parte in respuesta.body_iterator])


def test_operaciones_con_metricas_costs_at_costo_si(engine: Engine, db: Session) -> None:
    """The live /ventas-ml/operaciones-con-metricas (list 1) cost = costo SI, both currencies and combos."""
    _mundo(engine)
    ventas = {
        w.venta_ml(engine, A, datetime(2026, 10, 5, 15)): D("25000"),
        w.venta_ml(engine, ARSP, datetime(2026, 10, 12, 11)): D("15000"),
        w.venta_ml(engine, COMBO, datetime(2026, 10, 5, 15)): D("60000"),
    }

    filas = ventas_ml.fetch_operaciones_con_metricas(db, from_date="2026-09-01", to_date="2026-10-31", coslis_id=1)

    assert {f["id_operacion"]: D(str(f["costo_sin_iva"])) for f in filas} == ventas


def test_operaciones_con_metricas_list_8_is_unchanged(engine: Engine, db: Session) -> None:
    """D3: the TP-Link dashboard's list 8 cost (28 USD x 1000) is not costo SI."""
    _mundo(engine)
    w.costo_lista(engine, A, datetime(2026, 9, 1, 9), "28", coslis_id=8)
    venta = w.venta_ml(engine, A, datetime(2026, 10, 5, 15))

    filas = ventas_ml.fetch_operaciones_con_metricas(db, from_date="2026-09-01", to_date="2026-10-31", coslis_id=8)

    assert [(f["id_operacion"], D(str(f["costo_sin_iva"]))) for f in filas] == [(venta, D("28000"))]


def test_export_costs_at_costo_si(engine: Engine, db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """/ventas-ml/exportar-operaciones: column 13 "Costo s/IVA" = costo SI."""
    from openpyxl import load_workbook

    _mundo(engine)
    w.venta_ml(engine, A, datetime(2026, 10, 5, 15))
    w.venta_ml(engine, ARSP, datetime(2026, 10, 12, 11))
    monkeypatch.setattr(ventas_ml, "get_pares_marca_cat_usuario_ventas", lambda *_: None)

    respuesta = ventas_ml.exportar_operaciones(
        from_date="2026-09-01",
        to_date="2026-10-31",
        marcas=None,
        categorias=None,
        tiendas_oficiales=None,
        pm_ids=None,
        db=db,
        current_user=None,
    )

    contenido = asyncio.run(_leer(respuesta))
    hoja = load_workbook(io.BytesIO(contenido)).active
    assert hoja.cell(row=1, column=13).value == "Costo s/IVA"
    costos = sorted(D(str(hoja.cell(row=r, column=13).value)) for r in range(2, hoja.max_row + 1))
    assert costos == [D("15000"), D("25000")]
