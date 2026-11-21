"""The resolved-cost reader (sell-in-costo-si T3 PR 1, interface handoffs/sell-in-costo-si-interfaz.md): the current
cost and the cost in force on (product, date), costo SI first and list cost otherwise (Q1), in the product's cost
currency (L18), in pesos at the right rate, combos as their components (S11), and the same rule as a joinable subquery
and a SQL fragment. Spec: handoffs/sell-in-costo-si-feature.md S10, S11, S13. Invented data."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import sessionmaker

from app.mcp import tools as mcp_tools
from app.models.producto import ProductoERP
from app.services.costo_si import lectura, lote
from app.services.costo_si.lote import Costo
from tests.services.costo_si import _world as w

pytestmark = pytest.mark.postgres

D = Decimal
SI, LISTA = lote.FUENTE_COSTO_SI, lote.FUENTE_LISTA
A, B, SIN, ARSP, ARSLISTA, NADA = 5201, 5202, 5203, 5204, 5205, 5206
COMBO, COMBO_LISTA, COMBO_MIX, COMBO_INCOMPLETO, PC = 5211, 5212, 5213, 5214, 5215


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("costo_si_lote") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _paso(engine: Engine, item_id: int, orden: int, fecha: date, promedio: str, moneda: str = "USD") -> None:
    w.run(
        engine,
        "INSERT INTO costo_si_pasos (item_id, orden, tipo, fecha, cantidad, stock_antes, stock_base, stock_despues,"
        " promedio_usd, moneda) VALUES (:i, :o, :t, :f, 0, 0, 0, 0, :p, :m)",
        i=item_id,
        o=orden,
        t="inicio" if orden == 0 else "compra",
        f=fecha,
        p=promedio,
        m=moneda,
    )


def _mundo(engine: Engine) -> None:
    """A (USD): three steps, two on 10-10 (the later `orden` wins), list cost 30. B (USD): one step from 10-05, list
    cost 11. SIN (USD): no costo SI, list 40 today, history 35 (10-01 09:00) and 38 (10-05). ARSP (ARS): costo SI
    15000 from 10-01, list 14000. ARSLISTA (ARS): list 20000. NADA: no cost at all. Combos: COMBO = 2 A + B,
    COMBO_LISTA = A + SIN, COMBO_MIX = A + ARSP, COMBO_INCOMPLETO = A + NADA. PC (cat 47, contains A): its own 300.
    USD rate 1000 from 10-01, 1500 from 10-10."""
    w.producto(engine, A, costo="30")
    w.producto(engine, B, costo="11")
    w.producto(engine, SIN, costo="40")
    w.producto(engine, ARSP, moneda="ARS", costo="14000")
    w.producto(engine, ARSLISTA, moneda="ARS", costo="20000")
    w.producto(engine, NADA)
    for combo in (COMBO, COMBO_LISTA, COMBO_MIX, COMBO_INCOMPLETO):
        w.producto(engine, combo)
    w.producto(engine, PC, cat_id=47)
    _paso(engine, A, 0, date(2026, 10, 1), "25.00000")
    _paso(engine, A, 1, date(2026, 10, 10), "23.81667")
    _paso(engine, A, 2, date(2026, 10, 10), "23.08687")
    _paso(engine, B, 0, date(2026, 10, 5), "10.12345")
    _paso(engine, ARSP, 0, date(2026, 10, 1), "15000.00000", moneda="ARS")
    _paso(engine, PC, 0, date(2026, 10, 1), "300.00000")
    w.costo_lista(engine, SIN, datetime(2026, 10, 1, 9), "35")
    w.costo_lista(engine, SIN, datetime(2026, 10, 5, 12), "38")
    w.costo_lista(engine, ARSLISTA, datetime(2026, 10, 1, 9), "18000", curr_id=1)
    w.tipo_cambio(engine, date(2026, 10, 1), 1000)
    w.tipo_cambio(engine, date(2026, 10, 10), 1500)
    partes = [
        (COMBO, A, 2),
        (COMBO, B, 1),
        (COMBO_LISTA, A, 1),
        (COMBO_LISTA, SIN, 1),
        (COMBO_MIX, A, 1),
        (COMBO_MIX, ARSP, 1),
        (COMBO_INCOMPLETO, A, 1),
        (COMBO_INCOMPLETO, NADA, 1),
        (PC, A, 1),
    ]
    for combo, componente, cantidad in partes:
        w.run(
            engine,
            "INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES (:c, :p, :q)",
            c=combo,
            p=componente,
            q=cantidad,
        )


def _db(engine: Engine):
    return sessionmaker(bind=engine, autoflush=False)()


def _nada(item_id: int) -> Costo:
    return Costo(item_id, None, None, None, None, None, None)


def test_actuales_resolves_costo_si_then_list_cost_in_each_products_currency(engine: Engine) -> None:
    """S10 + Q1 + L18 + S11, at the latest rate (1500)."""
    _mundo(engine)
    ids = [A, B, SIN, ARSP, ARSLISTA, NADA, COMBO, COMBO_LISTA, COMBO_MIX, COMBO_INCOMPLETO, PC, 999]

    with _db(engine) as db:
        got = lote.actuales(db, ids)

    tc = D("1500")
    assert got == {
        A: Costo(A, D("23.08687"), "USD", SI, date(2026, 10, 10), tc, D("23.08687") * tc),
        B: Costo(B, D("10.12345"), "USD", SI, date(2026, 10, 5), tc, D("10.12345") * tc),
        SIN: Costo(SIN, D("40"), "USD", LISTA, None, tc, D("60000")),
        ARSP: Costo(ARSP, D("15000"), "ARS", SI, date(2026, 10, 1), None, D("15000")),
        ARSLISTA: Costo(ARSLISTA, D("20000"), "ARS", LISTA, None, None, D("20000")),
        NADA: _nada(NADA),
        COMBO: Costo(COMBO, D("56.29719"), "USD", SI, None, tc, D("56.29719") * tc),
        COMBO_LISTA: Costo(COMBO_LISTA, D("63.08687"), "USD", LISTA, None, tc, D("63.08687") * tc),
        COMBO_MIX: Costo(COMBO_MIX, D("49630.30500"), "ARS", SI, None, None, D("49630.30500")),
        COMBO_INCOMPLETO: _nada(COMBO_INCOMPLETO),
        PC: Costo(PC, D("300"), "USD", SI, date(2026, 10, 1), tc, D("450000")),
        999: _nada(999),
    }


def test_actuales_takes_the_callers_rate_and_no_ids_runs_no_query(engine: Engine) -> None:
    _mundo(engine)
    with _db(engine) as db:
        got = lote.actuales(db, [A], tipo_cambio=2000.0)
        assert lote.actuales(db, []) == {}

    assert (got[A].tipo_cambio, got[A].costo_ars) == (D("2000"), D("46173.74000"))


def test_en_fechas_is_the_cost_in_force_that_day_at_that_days_rate(engine: Engine) -> None:
    """S10: the last step dated on or before the date. Q1: else the day's list history (its last row of that day),
    else today's list cost. Pesos at that day's rate; none before the first rate."""
    _mundo(engine)
    pares = [
        (A, date(2026, 9, 30)),
        (A, date(2026, 10, 9)),
        (A, date(2026, 10, 10)),
        (SIN, date(2026, 9, 30)),
        (SIN, date(2026, 10, 1)),
        (SIN, date(2026, 10, 7)),
        (ARSP, date(2026, 10, 2)),
        (ARSLISTA, date(2026, 10, 2)),
        (COMBO, date(2026, 10, 4)),
        (COMBO, date(2026, 10, 7)),
        (COMBO_MIX, date(2026, 9, 30)),
        (COMBO_MIX, date(2026, 10, 7)),
        (COMBO_INCOMPLETO, date(2026, 10, 20)),
        (PC, date(2026, 10, 2)),
    ]

    with _db(engine) as db:
        got = lote.en_fechas(db, pares)

    mil = D("1000")
    assert got == {
        (A, date(2026, 9, 30)): Costo(A, D("30"), "USD", LISTA, None, None, None),
        (A, date(2026, 10, 9)): Costo(A, D("25"), "USD", SI, date(2026, 10, 1), mil, D("25000")),
        (A, date(2026, 10, 10)): Costo(A, D("23.08687"), "USD", SI, date(2026, 10, 10), D("1500"), D("34630.30500")),
        (SIN, date(2026, 9, 30)): Costo(SIN, D("40"), "USD", LISTA, None, None, None),
        (SIN, date(2026, 10, 1)): Costo(SIN, D("35"), "USD", LISTA, None, mil, D("35000")),
        (SIN, date(2026, 10, 7)): Costo(SIN, D("38"), "USD", LISTA, None, mil, D("38000")),
        (ARSP, date(2026, 10, 2)): Costo(ARSP, D("15000"), "ARS", SI, date(2026, 10, 1), None, D("15000")),
        (ARSLISTA, date(2026, 10, 2)): Costo(ARSLISTA, D("18000"), "ARS", LISTA, None, None, D("18000")),
        (COMBO, date(2026, 10, 4)): Costo(COMBO, D("61"), "USD", LISTA, None, mil, D("61000")),
        (COMBO, date(2026, 10, 7)): Costo(COMBO, D("60.12345"), "USD", SI, None, mil, D("60123.45")),
        (COMBO_MIX, date(2026, 9, 30)): _nada(COMBO_MIX),
        (COMBO_MIX, date(2026, 10, 7)): Costo(COMBO_MIX, D("40000"), "ARS", SI, None, None, D("40000")),
        (COMBO_INCOMPLETO, date(2026, 10, 20)): _nada(COMBO_INCOMPLETO),
        (PC, date(2026, 10, 2)): Costo(PC, D("300"), "USD", SI, date(2026, 10, 1), mil, D("300000")),
    }


def test_the_reader_agrees_with_the_one_product_reader_on_every_costo_si(engine: Engine) -> None:
    """Same rule as `lectura.leer` for many at once (a mixed-currency combo only has a value here, in pesos)."""
    _mundo(engine)
    items = [A, B, SIN, ARSP, COMBO, COMBO_LISTA, COMBO_INCOMPLETO, PC]
    fechas = [date(2026, 9, 30), date(2026, 10, 5), date(2026, 10, 10), date(2026, 12, 31)]

    with _db(engine) as db:
        lote_ = lote.en_fechas(db, [(i, f) for i in items for f in fechas])
        uno = {(i, f): lectura.leer(db, i, f) for i in items for f in fechas}

    def _si(c: Costo):
        return (c.costo, c.moneda) if c.fuente == SI else (None, None)

    assert {k: _si(c) for k, c in lote_.items()} == {k: (c.costo_si_usd, c.moneda) for k, c in uno.items()}


def test_the_one_product_reader_has_no_value_for_a_mixed_currency_combo(engine: Engine) -> None:
    """L18: USD and ARS components cannot be summed without a rate; `lote` sums them in pesos instead."""
    _mundo(engine)
    with _db(engine) as db:
        mix = lectura.leer(db, COMBO_MIX, date(2026, 10, 7))

    assert (mix.costo_si_usd, mix.moneda) == (None, None)
    assert [(c.item_id, c.moneda) for c in mix.componentes] == [(A, "USD"), (ARSP, "ARS")]


def test_the_sql_fragment_is_what_en_fechas_runs(engine: Engine) -> None:
    """PR 7/8/9 join `sql_en_fecha` in their own SQL and get exactly `en_fechas`."""
    _mundo(engine)
    sql = text(
        "SELECT v.item_id, v.fecha, cs.* FROM (VALUES (:a, DATE '2026-10-07'), (:c, DATE '2026-10-07')) v(item_id, fecha)"
        f" LEFT JOIN LATERAL ({lote.sql_en_fecha('v.item_id', 'v.fecha')}) cs ON true ORDER BY 1"
    )

    with _db(engine) as db:
        filas = [tuple(r) for r in db.execute(sql, {"a": A, "c": COMBO_MIX})]
        esperado = lote.en_fechas(db, [(A, date(2026, 10, 7)), (COMBO_MIX, date(2026, 10, 7))])

    assert [f[2:] for f in filas] == [
        tuple(
            getattr(esperado[(f[0], f[1])], c)
            for c in ("costo", "moneda", "fuente", "costo_si_desde", "tipo_cambio", "costo_ars")
        )
        for f in filas
    ]
    assert list(lote.COLUMNAS) == [
        "costo_si_costo",
        "costo_si_moneda",
        "costo_si_fuente",
        "costo_si_desde",
        "costo_si_tipo_cambio",
        "costo_si_ars",
    ]


def test_actual_subquery_sorts_a_listing_by_the_peso_cost_in_sql(engine: Engine) -> None:
    """S13: a listing LEFT JOINs the current cost and sorts USD and ARS products together by `costo_si_ars`."""
    _mundo(engine)
    actual = lote.actual()

    with _db(engine) as db:
        rows = db.execute(
            select(ProductoERP.item_id, actual.c.costo_si_fuente, actual.c.costo_si_ars)
            .outerjoin(actual, actual.c.item_id == ProductoERP.item_id)
            .order_by(actual.c.costo_si_ars.desc().nulls_last(), ProductoERP.item_id)
        ).all()

    assert [tuple(r) for r in rows] == [
        (PC, SI, D("450000")),
        (COMBO_LISTA, LISTA, D("94630.30500")),
        (COMBO, SI, D("84445.78500")),
        (SIN, LISTA, D("60000")),
        (COMBO_MIX, SI, D("49630.30500")),
        (A, SI, D("34630.30500")),
        (ARSLISTA, LISTA, D("20000")),
        (B, SI, D("15185.17500")),
        (ARSP, SI, D("15000")),
        (NADA, None, None),
        (COMBO_INCOMPLETO, None, None),
    ]


def test_list_history_edge_cases(engine: Engine) -> None:
    """Q1: a NULL `curr_id` is pesos; two corrections the same day, the later one wins (then the higher id); a list
    cost of 0 is no cost (the ERP writes 0 for a missing one), so a combo with such a component is unknown; a
    datetime asks for its date."""
    w.producto(engine, ARSLISTA, moneda="ARS", costo="20000")
    w.producto(engine, SIN, costo="0")
    w.producto(engine, COMBO_LISTA)
    w.run(
        engine,
        "INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES (:c, :p, 1)",
        c=COMBO_LISTA,
        p=SIN,
    )
    w.run(
        engine,
        "INSERT INTO tb_item_cost_list_history (iclh_id, coslis_id, item_id, iclh_price, curr_id, iclh_cd) VALUES "
        "(900001, 1, :i, 17000, NULL, '2026-10-01 09:00'), (900002, 1, :i, 17100, NULL, '2026-10-02 09:00'), "
        "(900003, 1, :i, 17200, NULL, '2026-10-02 15:00')",
        i=ARSLISTA,
    )

    with _db(engine) as db:
        got = lote.en_fechas(
            db,
            [
                (ARSLISTA, date(2026, 10, 1)),
                (ARSLISTA, datetime(2026, 10, 2, 8)),
                (SIN, date(2026, 10, 2)),
                (COMBO_LISTA, date(2026, 10, 2)),
            ],
        )

    assert got == {
        (ARSLISTA, date(2026, 10, 1)): Costo(ARSLISTA, D("17000"), "ARS", LISTA, None, None, D("17000")),
        (ARSLISTA, date(2026, 10, 2)): Costo(ARSLISTA, D("17200"), "ARS", LISTA, None, None, D("17200")),
        (SIN, date(2026, 10, 2)): _nada(SIN),
        (COMBO_LISTA, date(2026, 10, 2)): _nada(COMBO_LISTA),
    }


def test_sql_actual_is_the_current_cost_of_actuales_for_a_sort(engine: Engine) -> None:
    """PR 2 sort key `costo_si`: the correlated SQL a listing orders by is `actuales`' `costo_si_ars`, every case."""
    _mundo(engine)
    ids = [A, B, SIN, ARSP, ARSLISTA, NADA, COMBO, COMBO_LISTA, COMBO_MIX, COMBO_INCOMPLETO, PC]
    sql = f"SELECT v.item_id, ({lote.sql_actual('v.item_id')}) FROM unnest(CAST(:ids AS int[])) AS v(item_id)"

    with _db(engine) as db:
        got = dict(db.execute(text(sql), {"ids": ids}).all())
        esperado = {i: c.costo_ars for i, c in lote.actuales(db, ids).items()}

    assert got == esperado
    assert got[A] is not None and got[NADA] is None


def test_combos_con_lists_the_combos_a_component_moves_but_not_pcs(engine: Engine) -> None:
    _mundo(engine)
    with _db(engine) as db:
        assert lote.combos_con(db, [A, SIN, ARSLISTA]) == {
            A: [COMBO, COMBO_LISTA, COMBO_MIX, COMBO_INCOMPLETO],
            SIN: [COMBO_LISTA],
        }
        assert lote.combos_con(db, []) == {}


def test_en_pesos_converts_usd_at_the_rate_and_never_passes_usd_as_pesos() -> None:
    assert lote.en_pesos(D("23.08687"), "USD", 1450.5) == D("23.08687") * D("1450.5")
    assert lote.en_pesos(D("15000"), "ARS", None) == D("15000")
    assert lote.en_pesos(D("23.08687"), "USD", None) is None
    assert lote.en_pesos(D("23.08687"), "USD", 0) is None
    assert lote.en_pesos(None, "USD", 1450.5) is None
    assert lote.en_pesos(D("1"), None, 1450.5) is None


def test_every_column_stays_behind_the_cost_permission() -> None:
    """C12: the MCP tools strip every `costo*` key without `productos.ver_costos`."""
    for key in (*lote.COLUMNAS, "costo_si", "costo_si_moneda", "costo_si_fuente"):
        assert mcp_tools._COST_KEY.search(key), key
