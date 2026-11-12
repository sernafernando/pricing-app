"""Tienda's sell in / sell out (`app.services.tienda_sell_in_out`) against real tables, with hand-computed figures.

Owner (2026-11-12): "en tienda tienen que aplicar los sell in y sell out igual que en el resto de las cosas, tienen
que figurarle los costos más bajos y el plus de ganancia, acordate que tienda no usa las mismas fórmulas porque no
es sobre ml." Orchestrator decisions: sell out scope per key (gremio / sugerido: off-ML; web_transf: Tienda Nube; a
default-reach campaign applies to every key, an ML-stores-only one to none); a percentage of price campaign takes
each key's OWN price with VAT as its base.

The router (TP-LINK, VAT 21%) costs 50000 ARS. A lot of 2 units for 10000 ARS gives 5000 ARS per unit, so its cost
with sell in is 45000 ARS. Varios 6.5%, Tienda Nube commission 1%.

- gremio: 20% markup, 50000 x 1.065 x 1.2 = 63900 without VAT (77319 with VAT); net 63900 / 1.065 = 60000.
- sugerido: 30% markup, 50000 x 1.065 x 1.3 = 69225 without VAT (83762.25 with VAT); net 65000.
- web_transf: 80000 with VAT; 80000 / 1.21 = 66115.702479..., less 1% of 80000 (800) and 6.5% of the price without
  VAT (4297.520661...): net 61018.181818...

Campaigns: A, default reach, 1000 ARS per unit; B, Tienda Nube only, 10% of the price without VAT; C, one ML
official store only, 7777 ARS per unit; D, off-ML only, 5% of the price without VAT.

- gremio (A + D): 1000 + 5% of 63900 (3195) = 4195.
- sugerido (A + D): 1000 + 5% of 69225 (3461.25) = 4461.25.
- web_transf (A + B): 1000 + 10% of 66115.70 (6611.57) = 7611.57.
"""

from __future__ import annotations

from datetime import date
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.producto import ProductoERP
from app.models.tactical import TacticalTienda
from app.services.pricing_calculator import calcular_precio_web_transferencia, limpio_web_transferencia
from app.services.sell_in.costing import get_costing
from app.services.tienda_sell_in_out import (
    CLAVE_GREMIO,
    CLAVE_SUGERIDO,
    CLAVE_WEB_TRANSF,
    PrecioTienda,
    limpio_lista,
    resolver_tienda_batches,
    sell_in_out_tienda,
)
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in import _world as si
from tests.services.sell_out import _world as so
from tests.services.test_productos_sell_in_out_postgres import STUBS, TABLES
from tests.services.test_productos_sell_in_out_tienda_scope_postgres import _install

pytestmark = pytest.mark.postgres

HOY = date(2026, 11, 10)
ROUTER = 2964  # TP-LINK Routers, VAT 21%, cost 50000 ARS
SWITCH = 2270  # no sell in, no campaign: the no-SISO row
GAUSS = 57997
VARIOS = 6.5
COMISION_TN = 1.0

PRECIOS = {
    CLAVE_GREMIO: PrecioTienda(con_iva=77319.0, limpio=limpio_lista(63900.0, VARIOS)),
    CLAVE_SUGERIDO: PrecioTienda(con_iva=83762.25, limpio=limpio_lista(69225.0, VARIOS)),
    CLAVE_WEB_TRANSF: PrecioTienda(
        con_iva=80000.0, limpio=limpio_web_transferencia(80000.0, 21.0, COMISION_TN, VARIOS)
    ),
}


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema(
        "tienda_sio",
        [*TABLES, MlTiendaOficial.__table__, TacticalTienda.__table__],
        STUBS,
        after=_install,
    ) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    si.clean(engine)
    so.clean(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tacticals"))


def _tactical(engine: Engine, *, canales=(), oficiales=()) -> int:
    with engine.begin() as conn:
        tid = conn.execute(
            text(
                "INSERT INTO tacticals (tipo, nombre, marca, fecha_desde, fecha_hasta, moneda, usuario_id, "
                "todas_tiendas, tope_compartido) VALUES ('sell_out', 'T', 'TP-LINK', '2026-11-01', '2026-11-30', "
                "'ARS', 7, false, true) RETURNING id"
            )
        ).scalar_one()
        for tipo in canales:
            conn.execute(
                text("INSERT INTO tactical_tiendas (tactical_id, tipo, store_id) VALUES (:t, :tipo, NULL)"),
                {"t": tid, "tipo": tipo},
            )
        for store_id in oficiales:
            conn.execute(
                text("INSERT INTO tactical_tiendas (tactical_id, tipo, store_id) VALUES (:t, 'oficial', :s)"),
                {"t": tid, "s": store_id},
            )
    return tid


def _campana(engine: Engine, tactical_id=None, **kw) -> int:
    gid = so.grupo(engine, [{"item_id": ROUTER}])
    if tactical_id is not None:
        kw.update(tactical_id=tactical_id, tactical_linea=1)
    return so.campana(engine, [gid], **kw)


def _porcentaje(pct: str) -> dict:
    return {"tipo": "porcentaje", "monto_unit": None, "porcentaje": pct, "base_porcentaje": "precio_neto"}


def _sell_in_out(engine: Engine, item_id: int = ROUTER, precios=PRECIOS):
    with sessionmaker(bind=engine)() as db:
        producto = db.get(ProductoERP, item_id)
        batches = resolver_tienda_batches(db, [item_id], HOY)
        return sell_in_out_tienda(batches, producto, precios, tipo_cambio=None, iva=producto.iva or 21.0)


@pytest.fixture()
def mundo(engine: Engine) -> dict:
    si.compra(engine, [(ROUTER, 2, "10000.00")], date(2026, 10, 1))
    with sessionmaker(bind=engine)() as db:
        get_costing().recompute(db, [ROUTER], isolate_failures=False)
        db.commit()
    return {
        "A": _campana(engine, monto_unit="1000.00"),
        "B": _campana(engine, _tactical(engine, canales=("tienda_nube",)), **_porcentaje("10.00")),
        "C": _campana(engine, _tactical(engine, oficiales=(GAUSS,)), monto_unit="7777.00"),
        "D": _campana(engine, _tactical(engine, canales=("fuera",)), **_porcentaje("5.00")),
    }


def test_the_cost_with_sell_in_is_one_figure_in_the_cost_currency(engine, mundo):
    sio = _sell_in_out(engine)

    assert (sio.sell_in.descuento_unit, sio.sell_in.costo) == (5000.0, 45000.0)
    assert (sio.sell_in.moneda_costo, sio.sell_in.costo_moneda) == ("ARS", 45000.0)


def test_each_key_reads_the_campaigns_of_its_channel_with_its_own_price_as_base(engine, mundo):
    sio = _sell_in_out(engine)

    a, b, d = mundo["A"], mundo["B"], mundo["D"]
    assert {k: (v.monto_unit, v.campana_ids) for k, v in sio.sell_out.items()} == {
        CLAVE_GREMIO: (4195.0, [a, d]),
        CLAVE_SUGERIDO: (4461.25, [a, d]),
        CLAVE_WEB_TRANSF: (7611.57, [a, b]),
    }


def test_the_extra_profit_uses_the_tienda_net_never_the_ml_one(engine, mundo):
    sio = _sell_in_out(engine)

    # net / 45000 - 1
    assert sio.markups_sell_in == {CLAVE_GREMIO: 33.33, CLAVE_SUGERIDO: 44.44, CLAVE_WEB_TRANSF: 35.6}
    # (net + sell out) / 45000 - 1: 64195, 69461.25, 68629.75...
    assert sio.markups_sell_in_out == {CLAVE_GREMIO: 42.66, CLAVE_SUGERIDO: 54.36, CLAVE_WEB_TRANSF: 52.51}


def test_a_key_without_a_price_has_no_markup_and_no_sell_out(engine, mundo):
    sio = _sell_in_out(engine, precios={**PRECIOS, CLAVE_SUGERIDO: None})

    assert set(sio.sell_out) == {CLAVE_GREMIO, CLAVE_WEB_TRANSF}
    assert CLAVE_SUGERIDO not in sio.markups_sell_in
    assert CLAVE_SUGERIDO not in sio.markups_sell_in_out


def test_a_product_without_a_vat_rate_uses_the_one_its_tienda_prices_were_built_with(engine, mundo):
    # Tienda prices a product without VAT at 21% (`listar_productos_tienda`), so the percentage of price bases
    # read that same 21%: the figures are the ones of the router with its own 21% rate.
    con_iva = _sell_in_out(engine)
    with engine.begin() as conn:
        conn.execute(text("UPDATE productos_erp SET iva = NULL WHERE item_id = :i"), {"i": ROUTER})
    try:
        sin_iva = _sell_in_out(engine)
    finally:
        with engine.begin() as conn:
            conn.execute(text("UPDATE productos_erp SET iva = 21.0 WHERE item_id = :i"), {"i": ROUTER})

    assert sin_iva.sell_out[CLAVE_WEB_TRANSF].monto_unit == 7611.57
    assert sin_iva == con_iva


def test_a_product_without_sell_in_or_sell_out_has_none(engine, mundo):
    assert _sell_in_out(engine, SWITCH) is None


def test_the_web_net_is_the_one_its_price_is_solved_for():
    resultado = calcular_precio_web_transferencia(
        costo_ars=50000.0, iva=21.0, markup_objetivo=0.25, comision_web=COMISION_TN, iibb=VARIOS
    )

    limpio = limpio_web_transferencia(resultado["precio"], 21.0, COMISION_TN, VARIOS)
    assert round((limpio / 50000.0 - 1) * 100, 2) == resultado["markup_real"]
