"""SQLite stand-in for the costo SI reader (sell-in-costo-si T3): `lote.actuales` and `lote.en_fechas` are Postgres
SQL, so tests that run on the in-memory SQLite `db` (written before costo SI) get a Python version of the reader's
'lista' fallback (Q1, handoffs/sell-in-costo-si-interfaz.md §1):

- current: `productos_erp.costo` in `moneda_costo` (0 or less = no list cost), pesos at the caller's USD rate or the
  latest one dated today or before;
- on a date d: the last list 1 history row created before the end of d (`curr_id` 1/NULL = ARS, else USD; a 0 there
  falls back like the reader does), else `productos_erp`; pesos at the last USD rate dated d or before.

SQLite has no `costo_si_pasos`, so 'lista' is all the real reader could answer there too; combos are not emulated
(none of those tests has one). `lote.sql_en_fecha` is a Postgres SQL fragment and has no SQLite stand-in: a test of a
raw-SQL path that embeds it runs on Postgres. Costo SI itself is tested on Postgres.
Use: `pytestmark = pytest.mark.usefixtures("costo_si_lista")` (import the fixture) or the fixture by name."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.item_cost_list_history import ItemCostListHistory as H
from app.models.producto import ProductoERP
from app.models.tipo_cambio import TipoCambio
from app.services.costo_si import lote
from app.services.pricing_calculator import moneda_de

_UN_DIA = timedelta(days=1)


def _tc(db, hasta: date):
    fila = (
        db.query(TipoCambio.venta)
        .filter(TipoCambio.moneda == "USD", TipoCambio.venta > 0, TipoCambio.fecha <= hasta)
        .order_by(TipoCambio.fecha.desc())
        .first()
    )
    return Decimal(str(fila[0])) if fila else None


def _positivo(valor):
    return Decimal(str(valor)) if valor is not None and valor > 0 else None


def _costo(item_id: int, costo, moneda, tc) -> lote.Costo:
    moneda = moneda if costo is not None else None
    return lote.Costo(
        item_id=item_id,
        costo=costo,
        moneda=moneda,
        fuente=lote.FUENTE_LISTA if costo is not None else None,
        costo_si_desde=None,
        tipo_cambio=tc if moneda == "USD" else None,
        costo_ars=lote.en_pesos(costo, moneda, tc),
    )


def _productos(db, ids):
    columnas = (ProductoERP.item_id, ProductoERP.costo, ProductoERP.moneda_costo)
    return {p.item_id: p for p in db.query(*columnas).filter(ProductoERP.item_id.in_(ids))}


def actuales_lista(db, item_ids, *, tipo_cambio=None):
    ids = sorted({int(i) for i in item_ids if i is not None})
    if not ids:
        return {}
    tc = Decimal(str(tipo_cambio)) if tipo_cambio else _tc(db, date.today())
    productos = _productos(db, ids)
    out = {}
    for i in ids:
        p = productos.get(i)
        costo = _positivo(p.costo) if p is not None else None
        out[i] = _costo(i, costo, moneda_de(p.moneda_costo) if p is not None else None, tc)
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


@pytest.fixture
def costo_si_lista(monkeypatch):
    monkeypatch.setattr(lote, "actuales", actuales_lista)
    monkeypatch.setattr(lote, "en_fechas", en_fechas_lista)
