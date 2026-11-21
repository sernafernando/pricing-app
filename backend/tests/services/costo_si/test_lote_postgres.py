"""The resolved-cost reader (sell-in-costo-si T3 PR 1, interface handoffs/sell-in-costo-si-interfaz.md): the current
cost and the cost in force on (product, date), costo SI first and list cost otherwise (Q1), in the product's cost
currency (L18), in pesos at the right rate, combos as their components (S11), and the same rule as a joinable subquery
and a SQL fragment. Spec: handoffs/sell-in-costo-si-feature.md S10, S11, S13. Invented data."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import dataclasses
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

    tc, D10_10 = D("1500"), date(2026, 10, 10)
    assert got == {
        A: Costo(A, D("23.08687"), "USD", SI, date(2026, 10, 10), tc, D("23.08687") * tc, D10_10),
        B: Costo(B, D("10.12345"), "USD", SI, date(2026, 10, 5), tc, D("10.12345") * tc, D10_10),
        SIN: Costo(SIN, D("40"), "USD", LISTA, None, tc, D("60000"), D10_10),
        ARSP: Costo(ARSP, D("15000"), "ARS", SI, date(2026, 10, 1), None, D("15000")),
        ARSLISTA: Costo(ARSLISTA, D("20000"), "ARS", LISTA, None, None, D("20000")),
        NADA: _nada(NADA),
        COMBO: Costo(COMBO, D("56.29719"), "USD", SI, None, tc, D("56.29719") * tc, D10_10),
        COMBO_LISTA: Costo(COMBO_LISTA, D("63.08687"), "USD", LISTA, None, tc, D("63.08687") * tc, D10_10),
        COMBO_MIX: Costo(COMBO_MIX, D("49630.30500"), "ARS", SI, None, None, D("49630.30500")),
        COMBO_INCOMPLETO: _nada(COMBO_INCOMPLETO),
        PC: Costo(PC, D("300"), "USD", SI, date(2026, 10, 1), tc, D("450000"), D10_10),
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

    mil, D10_01 = D("1000"), date(2026, 10, 1)
    assert got == {
        (A, date(2026, 9, 30)): Costo(A, D("30"), "USD", LISTA, None, None, None),
        (A, date(2026, 10, 9)): Costo(A, D("25"), "USD", SI, date(2026, 10, 1), mil, D("25000"), D10_01),
        (A, date(2026, 10, 10)): Costo(
            A, D("23.08687"), "USD", SI, date(2026, 10, 10), D("1500"), D("34630.30500"), date(2026, 10, 10)
        ),
        (SIN, date(2026, 9, 30)): Costo(SIN, D("40"), "USD", LISTA, None, None, None),
        (SIN, date(2026, 10, 1)): Costo(SIN, D("35"), "USD", LISTA, None, mil, D("35000"), D10_01),
        (SIN, date(2026, 10, 7)): Costo(SIN, D("38"), "USD", LISTA, None, mil, D("38000"), D10_01),
        (ARSP, date(2026, 10, 2)): Costo(ARSP, D("15000"), "ARS", SI, date(2026, 10, 1), None, D("15000")),
        (ARSLISTA, date(2026, 10, 2)): Costo(ARSLISTA, D("18000"), "ARS", LISTA, None, None, D("18000")),
        (COMBO, date(2026, 10, 4)): Costo(COMBO, D("61"), "USD", LISTA, None, mil, D("61000"), D10_01),
        (COMBO, date(2026, 10, 7)): Costo(COMBO, D("60.12345"), "USD", SI, None, mil, D("60123.45"), D10_01),
        (COMBO_MIX, date(2026, 9, 30)): _nada(COMBO_MIX),
        (COMBO_MIX, date(2026, 10, 7)): Costo(COMBO_MIX, D("40000"), "ARS", SI, None, None, D("40000")),
        (COMBO_INCOMPLETO, date(2026, 10, 20)): _nada(COMBO_INCOMPLETO),
        (PC, date(2026, 10, 2)): Costo(PC, D("300"), "USD", SI, date(2026, 10, 1), mil, D("300000"), D10_01),
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
            for c in ("costo", "moneda", "fuente", "costo_si_desde", "tipo_cambio", "costo_ars", "tipo_cambio_fecha")
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
        "costo_si_tipo_cambio_fecha",
    ]


@pytest.mark.parametrize("tc", [None, 2000.0])
def test_the_current_row_fragment_is_what_actuales_runs(engine: Engine, tc) -> None:
    """T3 PR 10: raw SQL that needs the CURRENT cost per row (consultas ranking) joins `sql_actual_fila` and gets
    exactly `actuales`, never the list history `sql_en_fecha(..., CURRENT_DATE)` falls back to first (SIN: list 40
    today, history 38)."""
    _mundo(engine)
    ids = [A, SIN, ARSP, ARSLISTA, NADA, COMBO, COMBO_MIX, COMBO_INCOMPLETO, PC]
    tasa = "NULL::numeric" if tc is None else "CAST(:tc AS numeric)"
    sql = text(
        "SELECT v.item_id, cs.* FROM unnest(CAST(:ids AS integer[])) v(item_id)"
        f" LEFT JOIN LATERAL ({lote.sql_actual_fila('v.item_id', tasa)}) cs ON true ORDER BY 1"
    )

    with _db(engine) as db:
        filas = {r[0]: tuple(r[1:]) for r in db.execute(sql, {"ids": ids, "tc": tc})}
        esperado = lote.actuales(db, ids, tipo_cambio=tc)

    campos = [f.name for f in dataclasses.fields(Costo)][1:]  # every field but item_id, in `COLUMNAS` order
    assert filas == {i: tuple(getattr(esperado[i], c) for c in campos) for i in ids}
    assert filas[SIN][:3] == (D("40"), "USD", LISTA)


@pytest.mark.parametrize("tc", [None, 2000.0])
def test_the_set_fragment_is_what_actuales_runs_for_every_product(engine: Engine, tc) -> None:
    """T3 PR 10 perf: raw SQL over a whole catalogue (consultas ranking / kpis) joins `sql_actual_conjunto` ONCE (no
    per-row lateral) and gets exactly `actuales` for every product: costo SI, list fallback, a list cost of 0, combos
    of one and of mixed currency, an incomplete combo, a PC and a product with no cost at all."""
    _mundo(engine)
    w.producto(engine, 5299, costo="0")  # a list cost of 0 is no cost
    w.producto(engine, 5298, costo="10")
    _paso(engine, 5298, 0, date(2026, 10, 1), "0.00000")  # an average of 0 is a costo SI
    w.producto(engine, 5297, costo="12")
    _paso(engine, 5297, 0, date(2026, 10, 1), None)  # a step without an average falls back to the list cost
    ids = [A, B, SIN, ARSP, ARSLISTA, NADA, COMBO, COMBO_LISTA, COMBO_MIX, COMBO_INCOMPLETO, PC, 5299, 5298, 5297, 999]
    tasa = "NULL::numeric" if tc is None else "CAST(:tc AS numeric)"
    conjunto = lote.sql_actual_conjunto("SELECT unnest(CAST(:ids AS integer[])) AS item_id", tasa)
    sql = text(f"SELECT cs.* FROM ({conjunto}) cs ORDER BY cs.item_id")

    with _db(engine) as db:
        filas = {r[0]: tuple(r[1:]) for r in db.execute(sql, {"ids": ids, "tc": tc})}
        esperado = lote.actuales(db, ids, tipo_cambio=tc)

    campos = [f.name for f in dataclasses.fields(Costo)][1:]
    assert filas == {i: tuple(getattr(esperado[i], c) for c in campos) for i in ids}


G72, G72_ARS, G72_CERO, G72_NADA, ERP_CERO = 5221, 5222, 5223, 5224, 5225
COMBO_GBP, COMBO_GBP_ARS, COMBO_GBP_CERO, COMBO_GBP_NADA, COMBO_ERP_CERO = 5231, 5232, 5233, 5234, 5235


def _componentes_fuera_de_productos_erp(engine: Engine) -> None:
    """Combo components GBP has but `productos_erp` does not (category 72 PRODUCCIÓN, skipped by the ERP sync; prod:
    items 15, 166, 360, 567): G72 USD 1.51 (a second company row says 99: the first company wins), G72_ARS ARS 500,
    G72_CERO cost 0 (item 4772, a discount line), G72_NADA no GBP cost. ERP_CERO has a `productos_erp` row with cost
    0 (item 4448). Each is in one combo with A (costo SI USD 23.08687 today)."""
    _mundo(engine)
    for item in (G72, G72_ARS, G72_CERO, G72_NADA):
        w.run(
            engine,
            "INSERT INTO tb_item (comp_id, item_id, item_code, cat_id) VALUES (1, :i, :c, 72)",
            i=item,
            c=f"C{item}",
        )
    for comp, item, precio, curr in (
        (1, G72, "1.51", 2),
        (2, G72, "99", 2),
        (1, G72_ARS, "500", 1),
        (1, G72_CERO, "0", 2),
    ):
        w.run(
            engine,
            "INSERT INTO tb_item_cost_list (comp_id, coslis_id, item_id, coslis_price, curr_id) VALUES (:c, 1, :i, :p, :m)",
            c=comp,
            i=item,
            p=D(precio),
            m=curr,
        )
    w.producto(engine, ERP_CERO, costo="0")
    w.run(
        engine,
        "INSERT INTO tb_item_cost_list (comp_id, coslis_id, item_id, coslis_price, curr_id) VALUES (1, 1, :i, 3, 2)",
        i=ERP_CERO,
    )
    for combo, componente, cantidad in (
        (COMBO_GBP, G72, 25),
        (COMBO_GBP_ARS, G72_ARS, 2),
        (COMBO_GBP_CERO, G72_CERO, 1),
        (COMBO_GBP_NADA, G72_NADA, 1),
        (COMBO_ERP_CERO, ERP_CERO, 5),
    ):
        w.producto(engine, combo)
        for parte, q in ((A, 1), (componente, cantidad)):
            w.run(
                engine,
                "INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES (:c, :p, :q)",
                c=combo,
                p=parte,
                q=q,
            )


def test_a_combo_component_missing_from_productos_erp_takes_its_gbp_list_cost(engine: Engine) -> None:
    """Orchestrator (#2373): a combo component with no `productos_erp` row takes its list cost from GBP's
    `tb_item_cost_list` (list 1, 'lista', its currency, the same rate rules). A GBP cost of 0 or none, and a
    `productos_erp` cost of 0, stay unknown (§7) until the owner answers. Only as a component: the item read on its
    own is still unknown."""
    _componentes_fuera_de_productos_erp(engine)
    combos = [COMBO_GBP, COMBO_GBP_ARS, COMBO_GBP_CERO, COMBO_GBP_NADA, COMBO_ERP_CERO]

    with _db(engine) as db:
        got = lote.actuales(db, [*combos, G72])
        dia = lote.en_fechas(db, [(COMBO_GBP, date(2026, 10, 20)), (COMBO_GBP_ARS, date(2026, 10, 20))])

    tc, D10_10 = D("1500"), date(2026, 10, 10)
    assert got[COMBO_GBP] == Costo(COMBO_GBP, D("60.83687"), "USD", LISTA, None, tc, D("60.83687") * tc, D10_10)
    # mixed currency: summed in pesos at the rate, 23.08687 x 1500 + 2 x 500
    assert got[COMBO_GBP_ARS] == Costo(COMBO_GBP_ARS, D("35630.30500"), "ARS", LISTA, None, None, D("35630.30500"))
    assert got[COMBO_GBP_CERO] == _nada(COMBO_GBP_CERO)
    assert got[COMBO_GBP_NADA] == _nada(COMBO_GBP_NADA)
    assert got[COMBO_ERP_CERO] == _nada(COMBO_ERP_CERO)
    assert got[G72] == _nada(G72)
    # on a date with no GBP list history the current GBP list cost stands in, as `productos_erp`'s would
    assert dia[(COMBO_GBP, date(2026, 10, 20))] == got[COMBO_GBP]
    assert dia[(COMBO_GBP_ARS, date(2026, 10, 20))] == got[COMBO_GBP_ARS]


def test_on_a_date_a_gbp_only_component_reads_its_list_history_first(engine: Engine) -> None:
    """Dated priority: costo SI step > list history > `productos_erp` > GBP's current list cost. A component missing
    from `productos_erp` with a history row before the date reads that row (USD 2), not GBP's current 1.51."""
    _componentes_fuera_de_productos_erp(engine)
    w.costo_lista(engine, G72, datetime(2026, 10, 5, 12), "2")
    dia = date(2026, 10, 20)

    with _db(engine) as db:
        got = lote.en_fechas(db, [(COMBO_GBP, dia)])[(COMBO_GBP, dia)]

    assert (got.costo, got.moneda, got.fuente) == (D("73.08687"), "USD", LISTA)  # 23.08687 + 25 x 2


@pytest.mark.parametrize("tc", [None, 2000.0])
def test_the_row_and_set_fragments_take_the_gbp_list_cost_of_a_component_too(engine: Engine, tc) -> None:
    _componentes_fuera_de_productos_erp(engine)
    ids = [COMBO_GBP, COMBO_GBP_ARS, COMBO_GBP_CERO, COMBO_GBP_NADA, COMBO_ERP_CERO, G72, A]
    tasa = "NULL::numeric" if tc is None else "CAST(:tc AS numeric)"
    fila = text(
        "SELECT v.item_id, cs.* FROM unnest(CAST(:ids AS integer[])) v(item_id)"
        f" LEFT JOIN LATERAL ({lote.sql_actual_fila('v.item_id', tasa)}) cs ON true"
    )
    conjunto = text(
        f"SELECT cs.* FROM ({lote.sql_actual_conjunto('SELECT unnest(CAST(:ids AS integer[])) AS item_id', tasa)}) cs"
    )

    with _db(engine) as db:
        por_fila = {r[0]: tuple(r[1:]) for r in db.execute(fila, {"ids": ids, "tc": tc})}
        por_conjunto = {r[0]: tuple(r[1:]) for r in db.execute(conjunto, {"ids": ids, "tc": tc})}
        esperado = lote.actuales(db, ids, tipo_cambio=tc)

    campos = [f.name for f in dataclasses.fields(Costo)][1:]
    assert por_fila == por_conjunto == {i: tuple(getattr(esperado[i], c) for c in campos) for i in ids}
    assert por_conjunto[COMBO_GBP][:3] == (D("60.83687"), "USD", LISTA)


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


@pytest.mark.parametrize(
    "alias", ["p", "pe", "h", "o", "r", "d", "b", "cc", "fx", "cs", "x", "t", "pt", "q", "ids", "v"]
)
def test_the_fragments_never_capture_the_callers_alias(engine: Engine, alias: str) -> None:
    """A caller whose own alias is one the fragment uses inside (e.g. a product table `p`) still reads ITS item: the
    fragment's inner names never shadow the caller's."""
    _mundo(engine)
    ids = [A, B, SIN, ARSP, ARSLISTA, NADA, COMBO, COMBO_LISTA, COMBO_MIX, PC]
    fecha = date(2026, 10, 7)
    dia = f"DATE '{fecha}'"
    actual = (
        f"SELECT {alias}.item_id, ({lote.sql_actual(f'{alias}.item_id')}) "
        f"FROM unnest(CAST(:ids AS int[])) AS {alias}(item_id)"
    )
    en_fecha = (
        f"SELECT {alias}.item_id, cs_.costo_si_costo, cs_.costo_si_ars "
        f"FROM unnest(CAST(:ids AS int[])) AS {alias}(item_id) "
        f"LEFT JOIN LATERAL ({lote.sql_en_fecha(f'{alias}.item_id', dia)}) cs_ ON true"
    )

    with _db(engine) as db:
        assert dict(db.execute(text(actual), {"ids": ids}).all()) == {
            i: c.costo_ars for i, c in lote.actuales(db, ids).items()
        }
        assert {r[0]: (r[1], r[2]) for r in db.execute(text(en_fecha), {"ids": ids})} == {
            i: (c.costo, c.costo_ars) for (i, _), c in lote.en_fechas(db, [(i, fecha) for i in ids]).items()
        }


def _sin_tipo_cambio(engine: Engine) -> None:
    w.run(engine, "DELETE FROM tipo_cambio")


def test_without_any_usd_rate_the_pesos_are_unknown_never_zero(engine: Engine, caplog) -> None:
    """No `tipo_cambio` and no ERP rate on or before the date: a USD cost has NO peso value (never 0: sales costed
    at 0 were a past incident), and the readers log the item and the date."""
    _mundo(engine)
    _sin_tipo_cambio(engine)
    dia = date(2026, 10, 7)
    sql = (
        "SELECT v.item_id, cs.costo_si_costo, cs.costo_si_tipo_cambio, cs.costo_si_ars FROM (VALUES (:a, :d), (:c, :d))"
        f" v(item_id, fecha) LEFT JOIN LATERAL ({lote.sql_en_fecha('v.item_id', 'v.fecha')}) cs ON true ORDER BY 1"
    )

    with _db(engine) as db, caplog.at_level("WARNING", logger=lote.__name__):
        actual = lote.actuales(db, [A, ARSP])
        en_fecha = lote.en_fechas(db, [(A, dia)])[(A, dia)]
        crudo = db.execute(text(sql), {"a": A, "c": COMBO_MIX, "d": dia}).all()

    assert (actual[A].costo, actual[A].tipo_cambio, actual[A].costo_ars) == (D("23.08687"), None, None)
    assert actual[ARSP].costo_ars == D("15000.00000")  # pesos need no rate
    assert (en_fecha.costo, en_fecha.tipo_cambio, en_fecha.costo_ars) == (D("25.00000"), None, None)
    assert crudo == [(A, D("25.00000"), None, None), (COMBO_MIX, None, None, None)]
    avisos = [r.getMessage() for r in caplog.records]
    assert any(str(A) in m and "2026-10-07" in m for m in avisos), avisos
    assert any(str(A) in m and str(date.today()) in m for m in avisos), avisos


def test_a_read_without_a_usd_rate_logs_one_warning_per_date_with_every_item(engine: Engine, caplog) -> None:
    """Warning volume: a listing page reads dozens of USD products at once; a day without a USD rate logs ONE
    warning per date naming the count and the items, never one per item."""
    _mundo(engine)
    _sin_tipo_cambio(engine)

    with _db(engine) as db, caplog.at_level("WARNING", logger=lote.__name__):
        lote.actuales(db, [A, B, SIN, ARSP])

    avisos = [r.getMessage() for r in caplog.records if r.name == lote.__name__]
    assert len(avisos) == 1, avisos
    assert "3 items" in avisos[0] and all(str(i) in avisos[0] for i in (A, B, SIN)), avisos
    assert str(ARSP) not in avisos[0] and str(date.today()) in avisos[0], avisos


def test_without_tipo_cambio_the_erp_rate_history_gives_the_rate(engine: Engine) -> None:
    """Like the metrics crons: `tipo_cambio` first, else the ERP's `tb_cur_exch_history` (USD -> ARS, > 0, the last
    one on or before the end of the day); never another currency pair."""
    _mundo(engine)
    _sin_tipo_cambio(engine)
    w.cambio_erp(engine, datetime(2026, 10, 1, 9), 1200)
    w.cambio_erp(engine, datetime(2026, 10, 7, 18), 0)  # a 0 rate is no rate
    w.cambio_erp(engine, datetime(2026, 10, 7, 10), 900, desde=3)  # another currency
    w.cambio_erp(engine, datetime(2026, 10, 8, 9), 1300)  # after the date
    dia = date(2026, 10, 7)
    sql = (
        "SELECT cs.costo_si_tipo_cambio, cs.costo_si_ars FROM (VALUES (:a, :d)) v(item_id, fecha)"
        f" LEFT JOIN LATERAL ({lote.sql_en_fecha('v.item_id', 'v.fecha')}) cs ON true"
    )

    with _db(engine) as db:
        en_fecha = lote.en_fechas(db, [(A, dia)])[(A, dia)]
        crudo = db.execute(text(sql), {"a": A, "d": dia}).one()
        actual = lote.actuales(db, [A])[A]

    assert (en_fecha.tipo_cambio, en_fecha.tipo_cambio_fecha, en_fecha.costo_ars) == (
        D("1200"),
        date(2026, 10, 1),
        D("25.00000") * 1200,
    )
    assert tuple(crudo) == (D("1200"), D("25.00000") * 1200)
    assert (actual.tipo_cambio, actual.tipo_cambio_fecha) == (D("1300"), date(2026, 10, 8))  # the latest ERP rate

    w.tipo_cambio(engine, date(2026, 10, 5), 1000)
    with _db(engine) as db:
        primero = lote.en_fechas(db, [(A, dia)])[(A, dia)]
    assert (primero.tipo_cambio, primero.tipo_cambio_fecha) == (D("1000"), date(2026, 10, 5))  # tipo_cambio first


def test_the_public_rate_lookup_is_the_readers_rate_with_its_date(engine: Engine) -> None:
    """`sql_tipo_cambio(fecha)`: the reader's USD rate on a SQL date and that rate's date, for raw SQL that stores the
    rate next to the cost (PR 7's `cotizacion_dolar`, `ml_order_item_costos.tipo_cambio_fecha`): `tipo_cambio`
    first, else the ERP history; NULLs without either."""
    _mundo(engine)

    def tasa(dia: date) -> tuple:
        sql = f"SELECT csi_t.* FROM ({lote.sql_tipo_cambio(':d')}) csi_t"
        with _db(engine) as db:
            return tuple(db.execute(text(sql), {"d": dia}).one())

    assert tasa(date(2026, 9, 30)) == (None, None)  # before any rate: unknown, never 0
    assert tasa(date(2026, 10, 7)) == (D("1000"), date(2026, 10, 1))
    with _db(engine) as db:
        mismo = lote.en_fechas(db, [(A, date(2026, 10, 12))])[(A, date(2026, 10, 12))]
    assert tasa(date(2026, 10, 12)) == (mismo.tipo_cambio, mismo.tipo_cambio_fecha) == (D("1500"), date(2026, 10, 10))

    _sin_tipo_cambio(engine)
    w.cambio_erp(engine, datetime(2026, 10, 1, 9), 1200)
    assert tasa(date(2026, 10, 7)) == (D("1200"), date(2026, 10, 1))
    with _db(engine) as db:
        escalar = db.execute(
            text(f"SELECT (SELECT csi_t.costo_si_tipo_cambio FROM ({lote.sql_tipo_cambio(':d')}) csi_t)"),
            {"d": date(2026, 10, 7)},
        ).scalar_one()
    assert escalar == D("1200")  # usable as a scalar rate too


def _escaneos(plan: dict, tabla: str) -> list[int]:
    """The `actual loops` of every scan of `tabla` in an EXPLAIN (ANALYZE, FORMAT JSON) plan (0 = never executed)."""
    nodos, vistos = [plan], []
    while nodos:
        nodo = nodos.pop()
        if nodo.get("Relation Name") == tabla:
            vistos.append(nodo.get("Actual Loops", 0))
        nodos.extend(nodo.get("Plans", []))
    return vistos


def test_a_sort_over_many_products_looks_the_rate_up_once(engine: Engine) -> None:
    """Measured on prod (#2366): a rate looked up per product, ERP history included, made the full-catalogue costo SI
    sort take seconds. The rate does not depend on the product: one `tipo_cambio` lookup per query, and the ERP
    history is never read while `tipo_cambio` has a rate."""
    _mundo(engine)
    sql = (
        "EXPLAIN (ANALYZE, FORMAT JSON) SELECT v.item_id FROM (VALUES (:a), (:b), (:c), (:d)) v(item_id)"
        f" ORDER BY ({lote.sql_actual('v.item_id')}) NULLS LAST"
    )

    with _db(engine) as db:
        plan = db.execute(text(sql), {"a": A, "b": B, "c": SIN, "d": ARSP}).scalar_one()[0]["Plan"]

    assert _escaneos(plan, "tipo_cambio") and max(_escaneos(plan, "tipo_cambio")) == 1
    assert max(_escaneos(plan, "tb_cur_exch_history"), default=0) == 0


def test_the_set_fragment_checks_the_pc_category_only_for_ids_with_parts(engine: Engine) -> None:
    """Timed on prod (#2373): the "not a PC" check read `tb_item` once per id of the whole catalogue (~15 of the ~50
    ms of a Tienda sort). Only an id with parts in `combo_componentes` can be a combo, so only those are checked."""
    _mundo(engine)
    ids = [A, B, SIN, ARSP, ARSLISTA, NADA, COMBO, COMBO_LISTA, PC]  # 3 with parts: COMBO, COMBO_LISTA, PC
    conjunto = lote.sql_actual_conjunto("SELECT unnest(CAST(:ids AS integer[])) AS item_id")

    with _db(engine) as db:
        plan = db.execute(
            text(f"EXPLAIN (ANALYZE, FORMAT JSON) SELECT cs.item_id FROM ({conjunto}) cs"), {"ids": ids}
        ).scalar_one()[0]["Plan"]

    assert sum(_escaneos(plan, "tb_item")) == 3


def _por_fila(plan: dict, tabla: str) -> bool:
    """Whether `tabla` is scanned inside a correlated SubPlan (re-run per outer row) of an EXPLAIN JSON plan."""
    pendientes = [(plan, False)]
    while pendientes:
        nodo, correlado = pendientes.pop()
        correlado = correlado or nodo.get("Parent Relationship") == "SubPlan"
        if correlado and nodo.get("Relation Name") == tabla:
            return True
        pendientes.extend((hijo, correlado) for hijo in nodo.get("Plans", []))
    return False


def test_the_catalogue_sort_key_is_the_current_cost_computed_once_per_product(engine: Engine) -> None:
    """Measured on prod (#2366): Publicaciones ML has ~6 rows per product, so a per-row costo SI made its sort take
    ~0.8 s. `sql_actual_catalogo(item)` is `sql_actual(item)` (pesos, NULL when unknown) computed once per product for
    the whole query, then looked up per row."""
    _mundo(engine)
    ids = [A, B, SIN, ARSP, ARSLISTA, NADA, COMBO, COMBO_MIX, COMBO_INCOMPLETO, PC, 999]
    valores = ", ".join(f"({i})" for i in ids + [A, A, B])
    comparar = (
        f"SELECT v.item_id, ({lote.sql_actual('v.item_id')}), {lote.sql_actual_catalogo('v.item_id')}"
        f" FROM (VALUES {valores}) v(item_id)"
    )
    plan_sql = (
        f"EXPLAIN (ANALYZE, FORMAT JSON) SELECT v.item_id FROM (VALUES {valores}) v(item_id)"
        f" ORDER BY {lote.sql_actual_catalogo('v.item_id')} NULLS LAST"
    )

    with _db(engine) as db:
        filas = db.execute(text(comparar)).all()
        plan = db.execute(text(plan_sql)).scalar_one()[0]["Plan"]

    assert [(i, por_fila) for i, por_fila, _ in filas] == [(i, catalogo) for i, _, catalogo in filas]
    assert {i for i, por_fila, _ in filas if por_fila is not None} >= {A, B, SIN, ARSP, COMBO}
    assert not _por_fila(plan, "productos_erp") and not _por_fila(plan, "combo_componentes")


def test_the_rate_comes_with_its_own_date(engine: Engine) -> None:
    """The rate's date travels with the rate (a frozen sale cost records it, `ml_order_item_costos.tipo_cambio_fecha`):
    the `tipo_cambio` row's date in force, the latest one for the current cost; none for pesos, nor for a rate the
    caller supplied that no `tipo_cambio` row has (the reader cannot date it)."""
    _mundo(engine)
    sql = (
        "SELECT v.item_id, cs.costo_si_tipo_cambio, cs.costo_si_tipo_cambio_fecha FROM (VALUES (:a, DATE '2026-10-07'),"
        f" (:c, DATE '2026-10-12')) v(item_id, fecha) LEFT JOIN LATERAL ({lote.sql_en_fecha('v.item_id', 'v.fecha')}) cs"
        " ON true ORDER BY 1"
    )

    with _db(engine) as db:
        en = lote.en_fechas(db, [(A, date(2026, 10, 7)), (A, date(2026, 10, 12)), (ARSP, date(2026, 10, 7))])
        actual = lote.actuales(db, [A, ARSP])
        propio = lote.actuales(db, [A], tipo_cambio=2000.0)[A]
        de_una_fila = lote.actuales(db, [A], tipo_cambio=1000.0)[A]
        crudo = db.execute(text(sql), {"a": A, "c": COMBO}).all()

    assert en[(A, date(2026, 10, 7))].tipo_cambio_fecha == date(2026, 10, 1)
    assert en[(A, date(2026, 10, 12))].tipo_cambio_fecha == date(2026, 10, 10)
    assert en[(ARSP, date(2026, 10, 7))].tipo_cambio_fecha is None
    assert (actual[A].tipo_cambio, actual[A].tipo_cambio_fecha) == (D("1500"), date(2026, 10, 10))
    assert actual[ARSP].tipo_cambio_fecha is None
    assert (propio.tipo_cambio, propio.tipo_cambio_fecha) == (D("2000.0"), None)  # no `tipo_cambio` row has it
    # the screens pass `obtener_tipo_cambio_actual`: a `tipo_cambio` row's rate gets that row's date
    assert (de_una_fila.tipo_cambio, de_una_fila.tipo_cambio_fecha) == (D("1000.0"), date(2026, 10, 1))
    assert crudo == [(A, D("1000"), date(2026, 10, 1)), (COMBO, D("1500"), date(2026, 10, 10))]


@pytest.mark.parametrize(
    "alias", ["p", "pe", "h", "o", "r", "d", "b", "cc", "fx", "cs", "x", "t", "pt", "tc", "q", "v"]
)
def test_the_fragment_never_captures_the_callers_alias(engine: Engine, alias: str) -> None:
    """A caller whose own alias is one the fragment uses inside (e.g. a product table `p`, a rate table `tc`) still
    reads ITS item on ITS date: the fragment's inner names never shadow the caller's, for either input."""
    _mundo(engine)
    ids = [A, B, SIN, ARSP, ARSLISTA, NADA, COMBO, COMBO_LISTA, COMBO_MIX, PC]
    fechas = [date(2026, 10, 7)] * 5 + [date(2026, 10, 12)] * 5
    sql = (
        f"SELECT {alias}.item_id, {alias}.fecha, cs_.costo_si_costo, cs_.costo_si_tipo_cambio, cs_.costo_si_ars "
        f"FROM unnest(CAST(:ids AS int[]), CAST(:fechas AS date[])) AS {alias}(item_id, fecha) "
        f"LEFT JOIN LATERAL ({lote.sql_en_fecha(f'{alias}.item_id', f'{alias}.fecha')}) cs_ ON true"
    )

    with _db(engine) as db:
        got = {(r[0], r[1]): tuple(r[2:]) for r in db.execute(text(sql), {"ids": ids, "fechas": fechas})}
        esperado = {
            k: (c.costo, c.tipo_cambio, c.costo_ars) for k, c in lote.en_fechas(db, list(zip(ids, fechas))).items()
        }

    assert got == esperado


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
