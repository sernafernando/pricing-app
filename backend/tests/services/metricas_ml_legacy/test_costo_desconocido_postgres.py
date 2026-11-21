"""An unknown cost stays unknown (interface handoffs/sell-in-costo-si-interfaz.md §7: "Raw SQL users of `sql_en_fecha`
(PRs 7/8/9) must treat NULL as unknown: never `COALESCE(costo_si_ars, 0)`"). A sale whose product has no cost at all,
or whose USD cost has no rate on its date, keeps its cost and every figure computed from it (costo total, ganancia,
markup, cost-percentage offsets) as NULL / not recorded, and the gap is logged. Sell-in-costo-si T3 PR 8. Invented
data."""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Iterator, Optional

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.endpoints import ventas_ml
from app.scripts import agregar_metricas_ml_incremental as incremental
from app.scripts import agregar_metricas_ml_local as local
from app.services.costo_si import despues
from tests.services.metricas_ml_legacy import _world as w

pytestmark = pytest.mark.postgres

D = Decimal
A, NADA = 6301, 6302
DESDE, HASTA = datetime(2026, 8, 1), datetime(2026, 10, 31, 23, 59, 59)
SIN_COSTO = "costo SI: no cost for item"


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("metricas_ml_desconocido") as engine:
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
    """A (USD): costo SI 25 from 08-01, but the first USD rate is 1000 on 09-01: an A sale in August has no rate.
    NADA: no cost of any kind."""
    w.producto(engine, A, costo="30")
    w.producto(engine, NADA)
    w.paso(engine, A, 0, date(2026, 8, 1), "25.00000")
    w.tipo_cambio(engine, date(2026, 9, 1), 1000)


def _cron(db: Session, modulo=incremental) -> None:
    modulo.process_and_insert(db, modulo.calcular_metricas_locales(db, DESDE, HASTA))
    db.commit()


def _fila(engine: Engine, mlo_id: int) -> tuple:
    [fila] = w.rows(
        engine,
        "SELECT costo_unitario_sin_iva, costo_total_sin_iva, ganancia, markup_porcentaje, monto_limpio"
        " FROM ml_ventas_metricas WHERE id_operacion = :o",
        o=mlo_id,
    )
    return fila


@pytest.mark.parametrize("modulo", [incremental, local], ids=["incremental", "local"])
def test_cron_keeps_an_unknown_cost_unknown_and_logs_it(
    engine: Engine, db: Session, modulo, caplog: pytest.LogCaptureFixture
) -> None:
    """No cost at all (NADA) and a USD cost without a rate on the sale date (A in August): cost, costo total, ganancia
    and markup are NULL, never 0; the net amount is still computed; each gap is logged."""
    _mundo(engine)
    nada = w.venta_ml(engine, NADA, datetime(2026, 10, 5, 15))
    sin_tc = w.venta_ml(engine, A, datetime(2026, 8, 15, 15))
    conocida = w.venta_ml(engine, A, datetime(2026, 10, 5, 15))

    with caplog.at_level(logging.WARNING):
        _cron(db, modulo)

    for venta in (nada, sin_tc):
        costo, total, ganancia, markup, limpio = _fila(engine, venta)
        assert (costo, total, ganancia, markup) == (None, None, None, None)
        assert limpio is not None
    assert _fila(engine, conocida)[0] == D("25000")
    avisos = [r.getMessage() for r in caplog.records if SIN_COSTO in r.getMessage()]
    assert any(str(NADA) in a for a in avisos) and any(str(A) in a and "2026-08-15" in a for a in avisos)


def _venta_fila(mlo_id: int, item_id: int, costo: Optional[str]) -> SimpleNamespace:
    """A cron row. `cantidad` is an int here: the cron's real rows carry a Decimal quantity, which makes
    `calcular_monto_offset` fail on every per-unit / cost-percentage offset (float * Decimal, swallowed by the cron;
    pre-existing on main, reported separately), so the guard is tested on the offset functions directly."""
    return SimpleNamespace(
        id_operacion=mlo_id,
        item_id=item_id,
        fecha_venta=datetime(2026, 10, 5, 15),
        cantidad=1,
        costo_sin_iva=D(costo) if costo is not None else None,
        cambio_momento=D("1000"),
        mlp_official_store_id=None,
        marca="MARCA DEMO",
        categoria="CAMARAS",
        subcat_id=None,
    )


@pytest.mark.parametrize(
    ("registrar", "tabla"),
    [
        (incremental.registrar_consumo_grupo_offset, "offset_grupo_consumo"),
        (incremental.registrar_consumo_offset_individual, "offset_individual_consumo"),
    ],
    ids=["grupo", "individual"],
)
def test_cron_records_no_cost_percentage_offset_for_an_unknown_cost(
    engine: Engine, db: Session, registrar, tabla: str
) -> None:
    """A 10 %-of-cost offset needs the cost: with it unknown nothing is recorded (no 0 consumption). Control: the
    same offset on a sale with a known cost (25000) records 2500."""
    _mundo(engine)
    w.run(engine, "INSERT INTO offset_grupos (id, nombre, oculto) VALUES (1, 'G', false)")
    grupo = "1" if tabla == "offset_grupo_consumo" else "NULL"
    w.run(
        engine,
        "INSERT INTO offsets_ganancia (id, tipo_offset, porcentaje, moneda, item_id, grupo_id, fecha_desde,"
        f" max_unidades, aplica_ml) VALUES (1, 'porcentaje_costo', 10, 'ARS', :n, {grupo}, '2026-08-01', 100, true),"
        f" (2, 'porcentaje_costo', 10, 'ARS', :a, {grupo}, '2026-08-01', 100, true)",
        n=NADA,
        a=A,
    )

    registrar(db, _venta_fila(1, NADA, None), True)
    registrar(db, _venta_fila(2, A, "25000"), True)
    db.commit()

    assert w.rows(engine, f"SELECT id_operacion, offset_id, monto_offset_aplicado FROM {tabla} ORDER BY id") == [
        (2, 2, D("2500.00"))
    ]


def test_operaciones_con_metricas_returns_an_unknown_cost_as_null(engine: Engine, db: Session) -> None:
    """/ventas-ml/operaciones-con-metricas: costo, costo total and markup of a sale without cost are null, not 0."""
    _mundo(engine)
    nada = w.venta_ml(engine, NADA, datetime(2026, 10, 5, 15))

    [fila] = ventas_ml.fetch_operaciones_con_metricas(db, from_date="2026-08-01", to_date="2026-10-31", coslis_id=1)

    assert fila["id_operacion"] == nada
    assert (fila["costo_sin_iva"], fila["costo_total"], fila["markup_porcentaje"]) == (None, None, None)
    ventas_ml.OperacionConMetricasResponse(**fila)  # the response model accepts it


async def _leer(respuesta) -> bytes:
    return b"".join([parte async for parte in respuesta.body_iterator])


def test_export_leaves_an_unknown_cost_empty(engine: Engine, db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """/ventas-ml/exportar-operaciones: the cost cells of a sale without cost are empty, not 0."""
    from openpyxl import load_workbook

    _mundo(engine)
    w.venta_ml(engine, NADA, datetime(2026, 10, 5, 15))
    monkeypatch.setattr(ventas_ml, "get_pares_marca_cat_usuario_ventas", lambda *_: None)

    respuesta = ventas_ml.exportar_operaciones(
        from_date="2026-08-01",
        to_date="2026-10-31",
        marcas=None,
        categorias=None,
        tiendas_oficiales=None,
        pm_ids=None,
        db=db,
        current_user=None,
    )

    hoja = load_workbook(io.BytesIO(asyncio.run(_leer(respuesta)))).active
    assert [hoja.cell(row=1, column=c).value for c in (13, 14)] == ["Costo s/IVA", "Costo Total"]
    assert [hoja.cell(row=2, column=c).value for c in (13, 14)] == [None, None]


def test_the_hook_sets_an_unknown_cost_to_null_and_leaves_its_offsets(
    engine: Engine, db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    """A costo SI change for A from 08-01 reaches an August sale that has no USD rate: its cost, ganancia and markup
    become NULL (backed up first), its cost-percentage consumption keeps its amount, and the gap is logged."""
    _mundo(engine)
    venta = w.venta_ml(engine, A, datetime(2026, 8, 15, 15))
    w.run(
        engine,
        "INSERT INTO ml_ventas_metricas (id_operacion, item_id, fecha_venta, cantidad, monto_total, monto_limpio,"
        " costo_unitario_sin_iva, costo_total_sin_iva, ganancia, markup_porcentaje)"
        " VALUES (:o, :i, '2026-08-15 15:00', 1, 100000, 80000, 30000, 30000, 50000, 166.67)",
        o=venta,
        i=A,
    )
    w.run(engine, "INSERT INTO offset_grupos (id, nombre, oculto) VALUES (1, 'G', false)")
    w.run(
        engine,
        "INSERT INTO offsets_ganancia (id, tipo_offset, porcentaje, moneda, item_id, grupo_id, fecha_desde)"
        " VALUES (1, 'porcentaje_costo', 10, 'ARS', :i, 1, '2026-08-01')",
        i=A,
    )
    w.run(
        engine,
        "INSERT INTO offset_grupo_consumo (grupo_id, id_operacion, tipo_venta, fecha_venta, item_id, cantidad,"
        " offset_id, monto_offset_aplicado, monto_offset_usd, cotizacion_dolar)"
        " VALUES (1, :o, 'ml', '2026-08-15', :i, 1, 1, 3000, 3, 1000)",
        o=venta,
        i=A,
    )

    with caplog.at_level(logging.WARNING):
        w.paso(engine, A, 9, date(2026, 8, 10), "20.00000")
        despues.despachar(db, A, date(2026, 8, 10))
        db.commit()

    assert _fila(engine, venta)[:4] == (None, None, None, None)
    assert w.rows(engine, "SELECT monto_offset_aplicado FROM offset_grupo_consumo") == [(D("3000.00"),)]
    assert w.rows(engine, "SELECT count(*) FROM costo_si_backups") == [(1,)]
    assert any(SIN_COSTO in r.getMessage() and str(A) in r.getMessage() for r in caplog.records)
