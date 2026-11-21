"""The SQLite stand-in for the costo SI reader (`tests/costo_si_lista.py`) answers exactly what the real reader
(`lote.actuales`) answers for products without costo SI: the 'lista' fallback of handoffs/sell-in-costo-si-interfaz.md
§1 (Q1). Checked against the real reader on Postgres, so the stand-in cannot drift from it. Invented data."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.models.producto import ProductoERP
from app.models.tipo_cambio import TipoCambio
from app.services.costo_si import lote
from tests.costo_si_lista import actuales_lista, costo_si_lista, en_fechas_lista  # noqa: F401  (fixture)
from tests.services.costo_si import _world as w

USD, ARS, VACIO, CERO, NADA, AUSENTE = 6101, 6102, 6103, 6104, 6105, 6199


@pytest.fixture(scope="module")
def mundo() -> Iterator[Engine]:  # not `engine`: that name is the SQLite `db` fixture's
    with w.world("costo_si_lista") as engine:
        yield engine


@pytest.mark.postgres
@pytest.mark.parametrize("tipo_cambio", [None, 1234.5], ids=["latest_rate", "caller_rate"])
def test_the_stand_in_answers_what_the_reader_answers_without_costo_si(mundo: Engine, tipo_cambio) -> None:
    engine, hoy = mundo, date.today()
    w.producto(engine, USD, moneda="USD", costo="100")
    w.producto(engine, ARS, moneda="ARS", costo="50000")
    w.producto(engine, VACIO, moneda=None, costo="70")  # no currency is ARS
    w.producto(engine, CERO, moneda="USD", costo="0")  # the ERP's 0 = no list cost
    w.producto(engine, NADA, moneda="USD")
    w.tipo_cambio(engine, hoy - timedelta(days=1), 1000)
    w.tipo_cambio(engine, hoy - timedelta(days=3), 900)
    w.tipo_cambio(engine, hoy + timedelta(days=1), 5000)  # a future row is not today's rate
    ids = [USD, ARS, VACIO, CERO, NADA, AUSENTE]
    try:
        with sessionmaker(bind=engine)() as db:
            real = lote.actuales(db, ids, tipo_cambio=tipo_cambio)
            stand_in = actuales_lista(db, ids, tipo_cambio=tipo_cambio)
    finally:
        w.clean(engine)

    assert stand_in == real
    assert real[USD].costo_ars == Decimal("100") * Decimal(str(tipo_cambio or 1000))


@pytest.mark.postgres
def test_the_stand_in_answers_what_the_reader_answers_on_a_date_without_costo_si(mundo: Engine) -> None:
    """List 1 history created before the end of the day (USD and ARS rows; a 0 row falls back to the current list
    cost), else the current list cost; pesos at that date's USD rate."""
    engine = mundo
    w.producto(engine, USD, moneda="USD", costo="40")
    w.producto(engine, ARS, moneda="ARS", costo="50000")
    w.producto(engine, VACIO, moneda=None, costo="70")
    w.producto(engine, NADA, moneda="USD")
    w.costo_lista(engine, USD, datetime(2026, 10, 1, 9), "35")
    w.costo_lista(engine, USD, datetime(2026, 10, 5, 23, 59), "38")
    w.costo_lista(engine, USD, datetime(2026, 10, 7, 10), "0")
    w.costo_lista(engine, ARS, datetime(2026, 10, 2, 12), "45000", curr_id=1)
    w.tipo_cambio(engine, date(2026, 9, 30), 900)
    w.tipo_cambio(engine, date(2026, 10, 4), 950)
    w.tipo_cambio(engine, date(2026, 10, 6), 0)  # no rate that day: the previous one counts
    fechas = [date(2026, 9, 29), date(2026, 10, 1), date(2026, 10, 5), date(2026, 10, 6), datetime(2026, 10, 7, 18)]
    pares = [(i, f) for i in (USD, ARS, VACIO, NADA, AUSENTE) for f in fechas]
    try:
        with sessionmaker(bind=engine)() as db:
            real = lote.en_fechas(db, pares)
            stand_in = en_fechas_lista(db, pares)
    finally:
        w.clean(engine)

    assert stand_in == real
    assert real[(USD, date(2026, 10, 5))].costo_ars == Decimal("38") * 950


@pytest.mark.postgres
def test_the_stand_in_falls_back_to_the_erp_rate_history_like_the_reader(mundo: Engine) -> None:
    """Interfaz §7: no `tipo_cambio` venta > 0 on or before the date -> the ERP's USD -> ARS `tb_cur_exch_history`
    (created before the end of the day; never another currency pair), with that rate's date; without either the pesos
    are None, never 0."""
    engine = mundo
    w.producto(engine, USD, moneda="USD", costo="100")
    w.producto(engine, ARS, moneda="ARS", costo="50000")
    w.tipo_cambio(engine, date(2026, 10, 6), 0)  # a 0 rate is no rate
    w.cambio_erp(engine, datetime(2026, 10, 1, 10), 880)
    w.cambio_erp(engine, datetime(2026, 10, 5, 23, 59), 910)
    w.cambio_erp(engine, datetime(2026, 10, 7, 9), 930)  # created after the end of 10-06: not that day's rate
    w.cambio_erp(engine, datetime(2026, 10, 5, 12), 7777, desde=3)  # another currency pair never counts
    pares = [(i, f) for i in (USD, ARS) for f in (date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 6))]
    try:
        with sessionmaker(bind=engine)() as db:
            real, stand_in = lote.en_fechas(db, pares), en_fechas_lista(db, pares)
            actual_real, actual_stand_in = lote.actuales(db, [USD, ARS]), actuales_lista(db, [USD, ARS])
            propio_real = lote.actuales(db, [USD], tipo_cambio=Decimal("1234.5"))
            propio_stand_in = actuales_lista(db, [USD], tipo_cambio=Decimal("1234.5"))
            w.tipo_cambio(engine, date(2026, 10, 3), 1234.5)
            de_fila_real = lote.actuales(db, [USD], tipo_cambio=Decimal("1234.5"))
            de_fila_stand_in = actuales_lista(db, [USD], tipo_cambio=Decimal("1234.5"))
    finally:
        w.run(engine, "DELETE FROM tb_cur_exch_history")
        w.clean(engine)

    assert stand_in == real
    assert actual_stand_in == actual_real
    assert propio_stand_in == propio_real
    del6 = real[(USD, date(2026, 10, 6))]
    assert (del6.costo_ars, del6.tipo_cambio_fecha) == (Decimal("100") * 910, date(2026, 10, 5))
    assert real[(USD, date(2026, 9, 30))].costo_ars is None  # no rate at all: unknown, never 0
    assert real[(ARS, date(2026, 10, 6))].tipo_cambio_fecha is None  # ARS uses no rate
    assert (actual_real[USD].costo_ars, actual_real[USD].tipo_cambio_fecha) == (Decimal("100") * 930, date(2026, 10, 7))
    assert propio_real[USD].tipo_cambio_fecha is None  # a caller's rate no `tipo_cambio` row has: undated
    assert de_fila_stand_in == de_fila_real  # a caller's rate a `tipo_cambio` row has: that row's date
    assert de_fila_real[USD].tipo_cambio_fecha == date(2026, 10, 3)


@pytest.mark.usefixtures("costo_si_lista")
def test_the_fixture_puts_the_stand_in_on_sqlite(db) -> None:
    db.add(ProductoERP(item_id=USD, codigo="C1", descripcion="P", costo=100, moneda_costo="USD"))
    db.add(TipoCambio(fecha=date.today(), moneda="USD", compra=1000, venta=1000))
    db.flush()

    costo = lote.actuales(db, [USD])[USD]

    assert (costo.fuente, costo.costo, costo.moneda, costo.costo_ars) == (
        lote.FUENTE_LISTA,
        Decimal("100"),
        "USD",
        Decimal("100000"),
    )
    hoy = date.today()
    assert lote.en_fechas(db, [(USD, hoy)])[(USD, hoy)].costo_ars == Decimal("100000")
