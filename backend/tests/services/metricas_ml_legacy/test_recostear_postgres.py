"""After a costo SI recompute, the stored legacy ML metrics follow (owner L15; sell-in-costo-si T3 PR 8, plan
handoffs/sell-in-costo-si-t3-pr8-plan.md; interface handoffs/sell-in-costo-si-interfaz.md §3), and the low-markup
notification and the dashboard / rentabilidad totals read the costo SI cost. Invented data."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Iterator, List

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.scripts import agregar_metricas_ml_incremental as incremental
from app.scripts import agregar_metricas_ml_local as local
from app.services.costo_si import despues
from app.services.costo_si.despues import metricas_ml_legacy
from tests.services.metricas_ml_legacy import _world as w

pytestmark = pytest.mark.postgres

D = Decimal
A, B, OTRO, COMBO, PC = 6201, 6202, 6203, 6211, 6212
DESDE, HASTA = datetime(2026, 9, 1), datetime(2026, 10, 31, 23, 59, 59)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("metricas_ml_recostear") as engine:
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
    """A (USD): costo SI 25 from 10-01. B (USD): costo SI 10 from 10-01. OTRO (USD): costo SI 40 from 10-01. COMBO =
    2 A + B. PC (cat 47) contains A but has its own costo SI 300 from 10-01. USD rate 1000."""
    for item in (A, B, OTRO, COMBO):
        w.producto(engine, item, costo="30")
    w.producto(engine, PC, cat_id=47)
    w.combo(engine, COMBO, {A: 2, B: 1})
    w.combo(engine, PC, {A: 1})
    w.paso(engine, A, 0, date(2026, 10, 1), "25.00000")
    w.paso(engine, B, 0, date(2026, 10, 1), "10.00000")
    w.paso(engine, OTRO, 0, date(2026, 10, 1), "40.00000")
    w.paso(engine, PC, 0, date(2026, 10, 1), "300.00000")
    w.tipo_cambio(engine, date(2026, 9, 1), 1000)


def _cron(db: Session) -> None:
    incremental.process_and_insert(db, incremental.calcular_metricas_locales(db, DESDE, HASTA))
    db.commit()


def _cambio(engine: Engine, db: Session, item_id: int, fecha: date, promedio: str) -> None:
    """A new costo SI step for `item_id` from `fecha`, then what the drain dispatches after it (same transaction)."""
    w.paso(engine, item_id, 9, fecha, promedio)
    despues.despachar(db, item_id, fecha)
    db.commit()


def _costo(engine: Engine, mlo_id: int) -> Decimal:
    return w.metrica(engine, mlo_id)["costo_unitario_sin_iva"]


def _backups(engine: Engine) -> List[tuple]:
    return w.rows(engine, "SELECT item_id, desde, motivo, pasos FROM costo_si_backups ORDER BY id")


# ------------------------------------------------------------------------------------------------- the hook


def test_a_costo_si_change_recosts_the_stored_sales_from_its_date_on(engine: Engine, db: Session) -> None:
    """L15: a step from 10-03 (20 USD) re-costs A's sales on or after 10-03 (one 48+ days before today: no 30-day
    window); A's sales before 10-03 and other products stay; price, commission, shipping and limpio untouched (D4)."""
    _mundo(engine)
    previa = w.venta_ml(engine, A, datetime(2026, 10, 2, 10))
    afectada = w.venta_ml(engine, A, datetime(2026, 10, 5, 15), cantidad=2)
    otra = w.venta_ml(engine, OTRO, datetime(2026, 10, 5, 15))
    _cron(db)
    # a sale before d still holding a pre-costo-SI cost: rewriting it is T4's job (dry-run + owner OK), not this hook's
    w.run(engine, "UPDATE ml_ventas_metricas SET costo_unitario_sin_iva = 30000 WHERE id_operacion = :o", o=previa)
    antes = w.metrica(engine, afectada)

    _cambio(engine, db, A, date(2026, 10, 3), "20.00000")

    m = w.metrica(engine, afectada)
    assert m["costo_unitario_sin_iva"] == D("20000")
    assert m["costo_total_sin_iva"] == D("40000")
    assert m["ganancia"] == m["monto_limpio"] - D("40000")
    assert m["markup_porcentaje"] == round((m["monto_limpio"] / D("40000") - 1) * 100, 2)
    assert {k: m[k] for k in ("monto_total", "monto_limpio", "comision_ml", "costo_envio_ml")} == {
        k: antes[k] for k in ("monto_total", "monto_limpio", "comision_ml", "costo_envio_ml")
    }
    assert _costo(engine, previa) == D("30000")
    assert _costo(engine, otra) == D("40000")


def test_the_hook_recosts_the_combos_that_contain_the_product(engine: Engine, db: Session) -> None:
    """S11: COMBO = 2 A + B follows A's change ((2 x 20 + 10) x 1000); the PC containing A keeps its own cost."""
    _mundo(engine)
    combo = w.venta_ml(engine, COMBO, datetime(2026, 10, 5, 15))
    pc = w.venta_ml(engine, PC, datetime(2026, 10, 5, 15))
    _cron(db)
    assert (_costo(engine, combo), _costo(engine, pc)) == (D("60000"), D("300000"))

    _cambio(engine, db, A, date(2026, 10, 3), "20.00000")

    assert (_costo(engine, combo), _costo(engine, pc)) == (D("50000"), D("300000"))


def test_the_hook_equals_a_cron_rerun(engine: Engine, db: Session) -> None:
    """The SQL formulas match the Python calculator: re-running the cron over the hook's rows changes nothing beyond
    the cent (`monto_limpio` is stored rounded)."""
    _mundo(engine)
    ventas = [w.venta_ml(engine, A, datetime(2026, 10, 5, 15), cantidad=3, precio="12345.67")]
    _cron(db)
    _cambio(engine, db, A, date(2026, 10, 3), "21.12345")
    hook = w.metrica(engine, ventas[0])

    local.process_and_insert(db, local.calcular_metricas_locales(db, DESDE, HASTA))
    db.commit()

    cron = w.metrica(engine, ventas[0])
    assert hook["costo_unitario_sin_iva"] == cron["costo_unitario_sin_iva"]
    assert hook["costo_total_sin_iva"] == cron["costo_total_sin_iva"]
    assert abs(hook["ganancia"] - cron["ganancia"]) <= D("0.01")
    assert abs(hook["markup_porcentaje"] - cron["markup_porcentaje"]) <= D("0.01")


def test_the_hook_clamps_the_markup_like_the_calculator(engine: Engine, db: Session) -> None:
    """A near-zero cost gives the calculator's bound (NUMERIC(10, 2)), and a zero cost a 0 markup, never an error."""
    _mundo(engine)
    venta = w.venta_ml(engine, A, datetime(2026, 10, 5, 15))
    cero = w.venta_ml(engine, A, datetime(2026, 10, 8, 15))
    _cron(db)

    w.paso(engine, A, 8, date(2026, 10, 7), "0.00000")
    _cambio(engine, db, A, date(2026, 10, 3), "0.00001")

    assert w.metrica(engine, venta)["markup_porcentaje"] == D("99999999.99")
    assert (w.metrica(engine, cero)["costo_unitario_sin_iva"], w.metrica(engine, cero)["markup_porcentaje"]) == (
        D("0"),
        D("0"),
    )


def _offsets(engine: Engine, mlo_id: int) -> None:
    """A 10 %-of-cost offset and a fixed-amount offset, each with a group and an individual consumption of the sale
    at cost 50000 (2 x 25000) and rate 1000, and their summaries."""
    w.run(engine, "INSERT INTO offset_grupos (id, nombre, oculto) VALUES (1, 'G', false)")
    w.run(
        engine,
        "INSERT INTO offsets_ganancia (id, tipo_offset, porcentaje, monto, moneda, item_id, grupo_id, fecha_desde) "
        "VALUES (1, 'porcentaje_costo', 10, NULL, 'ARS', :i, 1, '2026-09-01'),"
        " (2, 'monto_fijo', NULL, 777, 'ARS', :i, 1, '2026-09-01')",
        i=A,
    )
    for offset_id, monto, usd in ((1, "5000", "5"), (2, "777", "0.78")):
        params = dict(o=mlo_id, i=A, off=offset_id, m=D(monto), u=D(usd))
        w.run(
            engine,
            "INSERT INTO offset_grupo_consumo (grupo_id, id_operacion, tipo_venta, fecha_venta, item_id, cantidad,"
            " offset_id, monto_offset_aplicado, monto_offset_usd, cotizacion_dolar)"
            " VALUES (1, :o, 'ml', '2026-10-05', :i, 2, :off, :m, :u, 1000)",
            **params,
        )
        w.run(
            engine,
            "INSERT INTO offset_individual_consumo (offset_id, id_operacion, tipo_venta, fecha_venta, item_id,"
            " cantidad, monto_offset_aplicado, monto_offset_usd, cotizacion_dolar)"
            " VALUES (:off, :o, 'ml', '2026-10-05', :i, 2, :m, :u, 1000)",
            **params,
        )
        w.run(
            engine,
            "INSERT INTO offset_individual_resumen (offset_id, total_unidades, total_monto_ars, total_monto_usd,"
            " cantidad_ventas) VALUES (:off, 2, :m, :u, 1)",
            **params,
        )
    w.run(
        engine,
        "INSERT INTO offset_grupo_resumen (grupo_id, total_unidades, total_monto_ars, total_monto_usd, cantidad_ventas)"
        " VALUES (1, 4, 5777, 5.78, 2)",
    )


def test_the_hook_moves_cost_percentage_offsets_by_the_difference(engine: Engine, db: Session) -> None:
    """A 10 % of cost offset follows the cost (5000 -> 4000 ARS, 5 -> 4 USD) in its consumptions and summaries; a
    fixed-amount offset does not move."""
    _mundo(engine)
    venta = w.venta_ml(engine, A, datetime(2026, 10, 5, 15), cantidad=2)
    _cron(db)
    _offsets(engine, venta)

    _cambio(engine, db, A, date(2026, 10, 3), "20.00000")

    q = "SELECT offset_id, monto_offset_aplicado, monto_offset_usd FROM {} ORDER BY offset_id"
    esperado = [(1, D("4000.00"), D("4.00")), (2, D("777.00"), D("0.78"))]
    assert w.rows(engine, q.format("offset_grupo_consumo")) == esperado
    assert w.rows(engine, q.format("offset_individual_consumo")) == esperado
    assert w.rows(engine, "SELECT total_monto_ars, total_monto_usd FROM offset_grupo_resumen") == [
        (D("4777.00"), D("4.78"))
    ]
    assert w.rows(
        engine, "SELECT offset_id, total_monto_ars, total_monto_usd FROM offset_individual_resumen ORDER BY 1"
    ) == [(1, D("4000.00"), D("4.00")), (2, D("777.00"), D("0.78"))]


_OFFSET_TABLAS = (
    "offset_grupo_consumo",
    "offset_individual_consumo",
    "offset_grupo_resumen",
    "offset_individual_resumen",
)


def _offsets_estado(engine: Engine) -> list:
    return [w.rows(engine, f"SELECT * FROM {tabla} ORDER BY id") for tabla in _OFFSET_TABLAS]


def test_a_second_hook_call_leaves_offsets_and_summaries_unchanged(engine: Engine, db: Session) -> None:
    """Idempotent: nothing changed since the first call, so consumptions and summaries stay exactly as they were."""
    _mundo(engine)
    venta = w.venta_ml(engine, A, datetime(2026, 10, 5, 15), cantidad=2)
    _cron(db)
    _offsets(engine, venta)
    _cambio(engine, db, A, date(2026, 10, 3), "20.00000")
    antes = _offsets_estado(engine)

    despues.despachar(db, A, date(2026, 10, 3))
    db.commit()

    assert _offsets_estado(engine) == antes


def test_summaries_stay_equal_to_their_consumptions_on_sub_cent_amounts(engine: Engine, db: Session) -> None:
    """Two sales whose 10 % offset is sub-cent (21.12345 USD x 1000 x 3 x 10 % = 6337.035 each): every consumption is
    stored at 6337.04 and the group summary moves by exactly what they moved (12674.08), with no cent drift."""
    _mundo(engine)
    ventas = [w.venta_ml(engine, A, datetime(2026, 10, d, 15), cantidad=3) for d in (5, 6)]
    _cron(db)
    w.run(engine, "INSERT INTO offset_grupos (id, nombre, oculto) VALUES (1, 'G', false)")
    w.run(
        engine,
        "INSERT INTO offsets_ganancia (id, tipo_offset, porcentaje, moneda, item_id, grupo_id, fecha_desde)"
        " VALUES (1, 'porcentaje_costo', 10, 'ARS', :i, 1, '2026-09-01')",
        i=A,
    )
    for venta in ventas:  # at the cron's cost: 25000 x 3 x 10 %
        w.run(
            engine,
            "INSERT INTO offset_grupo_consumo (grupo_id, id_operacion, tipo_venta, fecha_venta, item_id, cantidad,"
            " offset_id, monto_offset_aplicado, monto_offset_usd, cotizacion_dolar)"
            " VALUES (1, :o, 'ml', '2026-10-05', :i, 3, 1, 7500, 7.5, 1000)",
            o=venta,
            i=A,
        )
    w.run(
        engine,
        "INSERT INTO offset_grupo_resumen (grupo_id, total_unidades, total_monto_ars, total_monto_usd, cantidad_ventas)"
        " VALUES (1, 6, 15000, 15, 2)",
    )

    _cambio(engine, db, A, date(2026, 10, 3), "21.12345")

    consumos = w.rows(engine, "SELECT monto_offset_aplicado, monto_offset_usd FROM offset_grupo_consumo ORDER BY id")
    assert consumos == [(D("6337.04"), D("6.34"))] * 2
    assert w.rows(engine, "SELECT total_monto_ars, total_monto_usd FROM offset_grupo_resumen") == [
        (D("12674.08"), D("12.68"))
    ]


def test_the_hook_backs_up_the_previous_values_once(engine: Engine, db: Session) -> None:
    """Backup first: one costo_si_backups row (motivo 'ml_ventas_metricas') with the exact previous values of the
    sales and offset consumptions it changed; a second call with nothing new writes nothing."""
    _mundo(engine)
    venta = w.venta_ml(engine, A, datetime(2026, 10, 5, 15), cantidad=2)
    _cron(db)
    _offsets(engine, venta)
    antes = w.metrica(engine, venta)

    _cambio(engine, db, A, date(2026, 10, 3), "20.00000")
    despues.despachar(db, A, date(2026, 10, 3))
    db.commit()

    [(item, desde, motivo, pasos)] = _backups(engine)
    pasos = pasos if isinstance(pasos, dict) else json.loads(pasos)
    assert (item, desde, motivo) == (A, date(2026, 10, 3), "ml_ventas_metricas")
    [fila] = pasos["ventas"]
    assert fila["id_operacion"] == venta
    assert D(str(fila["costo_unitario_sin_iva"])) == antes["costo_unitario_sin_iva"]
    assert D(str(fila["costo_total_sin_iva"])) == antes["costo_total_sin_iva"]
    assert D(str(fila["ganancia"])) == antes["ganancia"]
    assert D(str(fila["markup_porcentaje"])) == antes["markup_porcentaje"]
    assert sorted((c["tabla"], D(str(c["monto_offset_aplicado"]))) for c in pasos["consumos"]) == [
        ("offset_grupo_consumo", D("5000.00")),
        ("offset_individual_consumo", D("5000.00")),
    ]


def test_the_hook_is_one_set_based_statement_for_thousands_of_sales(engine: Engine, db: Session) -> None:
    """~3,000 stored sales of A: the hook issues ONE statement for all of them (the other statements are the
    reader's read-only combos lookup), and every row is re-costed."""
    _mundo(engine)
    w.run(
        engine,
        "INSERT INTO ml_ventas_metricas (id_operacion, item_id, fecha_venta, cantidad, monto_total, monto_limpio,"
        " costo_unitario_sin_iva, costo_total_sin_iva, ganancia, markup_porcentaje)"
        " SELECT 900000 + g, :i, '2026-10-05 12:00', 1, 100000, 80000, 25000, 25000, 55000, 220"
        " FROM generate_series(1, 3000) g",
        i=A,
    )
    w.paso(engine, A, 9, date(2026, 10, 3), "20.00000")
    sentencias: List[str] = []

    def contar(conn, cursor, statement, *args) -> None:
        sentencias.append(statement)

    event.listen(engine, "before_cursor_execute", contar)
    try:
        metricas_ml_legacy.recostear(db, A, date(2026, 10, 3))
    finally:
        event.remove(engine, "before_cursor_execute", contar)
    db.commit()

    escrituras = [s for s in sentencias if "UPDATE ml_ventas_metricas" in s]
    assert len(escrituras) == 1
    lecturas = [s for s in sentencias if s not in escrituras]
    # the only other statements are the reader's combos lookup (lote.combos_con): read-only, independent of the rows
    assert lecturas and all(s.lstrip().startswith("SELECT") and "ml_ventas_metricas" not in s for s in lecturas)
    assert w.rows(
        engine, "SELECT count(*), min(costo_unitario_sin_iva), max(costo_unitario_sin_iva) FROM ml_ventas_metricas"
    ) == [(3000, D("20000.000000"), D("20000.000000"))]


def test_the_hook_is_registered_for_the_drain() -> None:
    """Interface §3: the module registers itself at import, so `queue.drenar` reaches it through `despachar`."""
    despues._cargar()
    assert despues._CALLBACKS["metricas_ml_legacy"] is metricas_ml_legacy.recostear


# ------------------------------------------------------------------------------------- notification and readers


def test_low_markup_notification_shows_the_current_costo_si(
    engine: Engine, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The notification's "costo actual" is today's costo SI in pesos (25 USD x 1000), not the list cost (30 USD);
    its wording does not change (Q3)."""
    _mundo(engine)
    w.run(engine, "INSERT INTO usuarios (id, nombre, activo) VALUES (1, 'PM', true)")
    w.run(
        engine,
        "INSERT INTO productos_pricing (item_id, markup_calculado, preservar_porcentaje_web) VALUES (:i, 10, false)",
        i=A,
    )
    venta = w.venta_ml(engine, A, datetime(2026, 10, 5, 15), precio="1000")

    class Permisos:
        def __init__(self, db: Session) -> None:
            pass

        def tiene_permiso(self, usuario, permiso: str) -> bool:
            return True

    for modulo in (incremental, local):
        monkeypatch.setattr(modulo, "PermisosService", Permisos)
    _cron(db)

    [(costo_actual, tc_actual, mensaje)] = w.rows(
        engine,
        "SELECT costo_actual, tipo_cambio_actual, mensaje FROM notificaciones WHERE id_operacion = :o",
        o=venta,
    )
    assert (costo_actual, tc_actual) == (D("25000.00"), D("1000.00"))
    assert mensaje.startswith("⚠️ Markup: ")


def test_low_markup_notification_keeps_an_ars_cost_without_a_rate(
    engine: Engine, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L18: an ARS-cost product's current costo SI is already pesos: costo actual 15000, no USD rate."""
    _mundo(engine)
    w.producto(engine, 6213, moneda="ARS", costo="14000")
    w.paso(engine, 6213, 0, date(2026, 10, 1), "15000.00000", moneda="ARS")
    w.run(engine, "INSERT INTO usuarios (id, nombre, activo) VALUES (1, 'PM', true)")
    w.run(
        engine,
        "INSERT INTO productos_pricing (item_id, markup_calculado, preservar_porcentaje_web) VALUES (6213, 10, false)",
    )
    venta = w.venta_ml(engine, 6213, datetime(2026, 10, 5, 15), precio="1000")

    class Permisos:
        def __init__(self, db: Session) -> None:
            pass

        def tiene_permiso(self, usuario, permiso: str) -> bool:
            return True

    monkeypatch.setattr(incremental, "PermisosService", Permisos)
    _cron(db)

    assert w.rows(
        engine, "SELECT costo_actual, tipo_cambio_actual FROM notificaciones WHERE id_operacion = :o", o=venta
    ) == [(D("15000.00"), None)]


def test_dashboard_totals_follow_the_stored_cost(engine: Engine, db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Follower, no code change: /dashboard-ml/metricas-generales sums `ml_ventas_metricas`, which now holds costo SI
    (25 USD x 1000 x 2), and its markup is over that cost."""
    from app.api.endpoints import dashboard_ml

    _mundo(engine)
    w.venta_ml(engine, A, datetime(2026, 10, 5, 15), cantidad=2)
    _cron(db)
    monkeypatch.setattr(dashboard_ml, "aplicar_filtro_marcas_pm", lambda query, *_: query)

    r = dashboard_ml.get_metricas_generales(
        fecha_desde="2026-10-01",
        fecha_hasta="2026-10-31",
        marcas=None,
        categorias=None,
        tiendas_oficiales=None,
        pm_ids=None,
        db=db,
        current_user=None,
    )

    assert r.total_costo == D("50000.00")
    assert r.markup_porcentaje == round(r.total_ganancia / D("50000") * 100, 2)
