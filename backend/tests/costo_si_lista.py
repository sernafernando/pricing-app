"""SQLite stand-in for the costo SI reader (sell-in-costo-si T3): `lote.actuales` and `lote.en_fechas` are Postgres
SQL, so tests that run on the in-memory SQLite `db` (written before costo SI) get a Python version of the reader's
'lista' fallback (Q1, handoffs/sell-in-costo-si-interfaz.md §1):

- current: `productos_erp.costo` in `moneda_costo` (0 or less = no list cost), pesos at the caller's USD rate or the
  latest one dated today or before;
- on a date d: the last list 1 history row created before the end of d (`curr_id` 1/NULL = ARS, else USD; a 0 there
  falls back like the reader does), else `productos_erp`; pesos at the last USD rate dated d or before;
- the USD rate (interfaz §7): `tipo_cambio` venta > 0, else the ERP's USD -> ARS `tb_cur_exch_history`; its date goes
  to `tipo_cambio_fecha` (USD only; a caller's rate is dated by the `tipo_cambio` row that has it, else None);
  without either the pesos are None, never 0.

`columna.costo_ars_sql` (a cost in pesos as SQL, for a sort that matches those numbers) gets the same rule in SQL.
SQLite has no `costo_si_pasos`, so 'lista' is all the real reader could answer there too; combos are not emulated
(none of those tests has one). `lote.sql_en_fecha` is a Postgres SQL fragment and has no SQLite stand-in: a test of a
raw-SQL path that embeds it runs on Postgres. Costo SI itself is tested on Postgres.
Use: `pytestmark = pytest.mark.usefixtures("costo_si_lista")` (import the fixture) or the fixture by name."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.cur_exch_history import CurExchHistory
from app.models.item_cost_list_history import ItemCostListHistory as H
from app.models.producto import ProductoERP
from app.models.tipo_cambio import TipoCambio
from app.services.costo_si import lote
from app.services.pricing_calculator import moneda_de

_UN_DIA = timedelta(days=1)


def _tc(db, hasta: date):
    """The reader's USD rate on `hasta` and that rate's own date, `(tc, fecha)` (interfaz §7): the last `tipo_cambio`
    venta > 0 dated on or before it, else the ERP's last USD -> ARS `tb_cur_exch_history` rate > 0 created before the
    end of that day (its date: the day it was created); `(None, None)` without either."""
    fila = (
        db.query(TipoCambio.venta, TipoCambio.fecha)
        .filter(TipoCambio.moneda == "USD", TipoCambio.venta > 0, TipoCambio.fecha <= hasta)
        .order_by(TipoCambio.fecha.desc())
        .first()
    )
    if fila is not None:
        return Decimal(str(fila[0])), fila[1]
    erp = (
        db.query(CurExchHistory.ceh_exchange, CurExchHistory.ceh_cd)
        .filter(
            CurExchHistory.curr_id_1 == 2,
            CurExchHistory.curr_id_2 == 1,
            CurExchHistory.ceh_exchange > 0,
            CurExchHistory.ceh_cd < datetime.combine(hasta, datetime.min.time()) + _UN_DIA,
        )
        .order_by(CurExchHistory.ceh_cd.desc(), CurExchHistory.ceh_id.desc())
        .first()
    )
    if erp is not None:
        return Decimal(str(erp[0])), erp[1].date() if isinstance(erp[1], datetime) else erp[1]
    return None, None


def _fecha_de(db, tipo_cambio):
    """A caller's rate, dated like the reader does: the latest `tipo_cambio` row (today or before) with that rate."""
    fila = (
        db.query(TipoCambio.fecha)
        .filter(TipoCambio.moneda == "USD", TipoCambio.venta == tipo_cambio, TipoCambio.fecha <= date.today())
        .order_by(TipoCambio.fecha.desc())
        .first()
    )
    return fila[0] if fila else None


def _positivo(valor):
    return Decimal(str(valor)) if valor is not None and valor > 0 else None


def _costo(item_id: int, costo, moneda, tasa) -> lote.Costo:
    """`tasa`: `(tc, fecha)` as `_tc` returns it (a caller's rate: its `tipo_cambio` row's date, or None)."""
    tc, tc_fecha = tasa
    moneda = moneda if costo is not None else None
    return lote.Costo(
        item_id=item_id,
        costo=costo,
        moneda=moneda,
        fuente=lote.FUENTE_LISTA if costo is not None else None,
        costo_si_desde=None,
        tipo_cambio=tc if moneda == "USD" else None,
        costo_ars=lote.en_pesos(costo, moneda, tc),
        tipo_cambio_fecha=tc_fecha if moneda == "USD" else None,
    )


def _productos(db, ids):
    columnas = (ProductoERP.item_id, ProductoERP.costo, ProductoERP.moneda_costo)
    return {p.item_id: p for p in db.query(*columnas).filter(ProductoERP.item_id.in_(ids))}


def actuales_lista(db, item_ids, *, tipo_cambio=None):
    ids = sorted({int(i) for i in item_ids if i is not None})
    if not ids:
        return {}
    tasa = (Decimal(str(tipo_cambio)), _fecha_de(db, tipo_cambio)) if tipo_cambio else _tc(db, date.today())
    productos = _productos(db, ids)
    out = {}
    for i in ids:
        p = productos.get(i)
        costo = _positivo(p.costo) if p is not None else None
        out[i] = _costo(i, costo, moneda_de(p.moneda_costo) if p is not None else None, tasa)
    return out


def en_fechas_lista(db, pares):
    lista = sorted(
        {(int(i), f.date() if isinstance(f, datetime) else f) for i, f in pares if i is not None and f is not None}
    )
    if not lista:
        return {}
    productos = _productos(db, {i for i, _ in lista})
    out = {}
    for i, d in lista:
        historia = (
            db.query(H.iclh_price, H.curr_id)
            .filter(H.item_id == i, H.coslis_id == 1, H.iclh_cd < datetime.combine(d, datetime.min.time()) + _UN_DIA)
            .order_by(H.iclh_cd.desc(), H.iclh_id.desc())
            .first()
        )
        costo = _positivo(historia[0]) if historia else None
        if costo is not None:
            moneda = "ARS" if (historia[1] or 1) == 1 else "USD"
        else:
            p = productos.get(i)
            costo = _positivo(p.costo) if p is not None else None
            moneda = moneda_de(p.moneda_costo) if p is not None else None
        out[(i, d)] = _costo(i, costo, moneda, _tc(db, d))
    return out


def costo_ars_sql_lista(item, tipo_cambio):
    """`columna.costo_ars_sql` as `actuales_lista` answers it, in SQL over `productos_erp` (the listing's main table,
    so `item` is implied): a positive list cost, ARS (or none, `moneda_de`) as is, USD x the caller's rate; NULL
    without a rate. The caller always passes the page's rate here (the listings resolve it first)."""
    from sqlalchemy import and_, case, or_

    from app.models.producto import TipoMoneda

    ars = or_(ProductoERP.moneda_costo.is_(None), ProductoERP.moneda_costo == TipoMoneda.ARS)
    positivo = and_(ProductoERP.costo.isnot(None), ProductoERP.costo > 0)
    ramas = [(and_(positivo, ars), ProductoERP.costo)]
    if tipo_cambio:
        ramas.append((positivo, ProductoERP.costo * float(tipo_cambio)))
    return case(*ramas)


@pytest.fixture
def costo_si_lista(monkeypatch):
    from app.services.costo_si import columna

    monkeypatch.setattr(lote, "actuales", actuales_lista)
    monkeypatch.setattr(lote, "en_fechas", en_fechas_lista)
    monkeypatch.setattr(columna, "costo_ars_sql", costo_ars_sql_lista)
