"""Sell in and sell out of a product TODAY, for the Productos screens (sell-in-sell-out T9).

`resolver_sell_in_out_batch` reads, for a page of products, the purchase line
the next sale would consume (option A, FIFO) and the campaigns that would credit
it, and `markups(...)` turns each product's already-computed `limpio` values into
the markups with sell in and with sell in + sell out. Postgres only, like the
allocators it reads after (`sell_in._world`, `sell_out._world`).
"""

from __future__ import annotations

from datetime import date
from typing import Iterator, Optional

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import sessionmaker

from app.models.producto import ProductoERP
from app.services.productos_sell_in_out import resolver_sell_in_out_batch
from app.services.sell_in.costing import get_costing
from app.services.sell_out import asignacion
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in import _world as si
from tests.services.sell_out import _world as so

pytestmark = pytest.mark.postgres

D = date
HOY = D(2026, 11, 10)
ROUTER = 2964  # TP-LINK Routers, iva 21, cost 50000 ARS
SWITCH = 2270  # TP-LINK Switches, iva 10.5, no sell in nor sell out anywhere

TABLES = list(dict.fromkeys([*si.TABLES, *so.TABLES]))
STUBS = [*si.STUBS, so.STUBS[-1]]  # usuarios / proveedores / pedidos_compra + offsets_ganancia


def _install(engine: Engine) -> None:
    si.install(engine)
    with engine.begin() as conn:
        for item_id, (marca, categoria, sub, iva) in so.PRODUCTOS.items():
            conn.execute(
                text(
                    "UPDATE productos_erp SET marca = :m, categoria = :c, subcategoria_id = :s, iva = :iva, "
                    "costo = 50000, moneda_costo = 'ARS' WHERE item_id = :i"
                ),
                {"i": item_id, "m": marca, "c": categoria, "s": sub, "iva": iva},
            )


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("productos_sio", TABLES, STUBS, after=_install) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    si.clean(engine)
    so.clean(engine)


def _recompute_sell_in(engine: Engine, *item_ids: int) -> None:
    with sessionmaker(bind=engine)() as db:
        get_costing().recompute(db, item_ids, isolate_failures=False)
        db.commit()


def _recompute_sell_out(engine: Engine, *ids: int) -> None:
    with sessionmaker(bind=engine)() as db:
        asignacion.recalcular(db, ids)
        db.commit()


def _payload(engine: Engine, item_id: int = ROUTER, limpio: Optional[float] = 60000.0, **kwargs):
    """The product's `sell_in_out` after recording the clásica (60000 ARS) and the best offer."""
    with sessionmaker(bind=engine)() as db:
        producto = db.get(ProductoERP, item_id)
        batch = resolver_sell_in_out_batch(db, [item_id], HOY)
        acc = batch.markups(producto, precio_lista_ml=kwargs.get("precio_lista_ml"), tipo_cambio=kwargs.get("tc"))
        if limpio is not None:
            acc.record("clasica", limpio)
            acc.record("mejor_oferta", limpio, percent=False)
        return acc.payload()


class TestSellIn:
    def test_next_sale_takes_the_oldest_lot_with_units_left(self, engine):
        # Lot A: 2 units, 100 per unit; lot B: 5 units, 200 per unit. A sale of 3 used A and 1 of B.
        si.compra(engine, [(ROUTER, 2, "200.00")], D(2026, 10, 1))
        (lote_b,) = si.compra(engine, [(ROUTER, 5, "1000.00")], D(2026, 10, 5))
        si.venta(engine, "fuera", ROUTER, 3, D(2026, 10, 20))
        _recompute_sell_in(engine, ROUTER)

        payload = _payload(engine)

        assert payload.sell_in.compra_item_id == lote_b
        assert payload.sell_in.descuento_unit == 200.0
        assert payload.sell_in.costo == 49800.0
        assert payload.sell_in.unidades_restantes == 4
        assert payload.sell_out is None
        assert payload.markups_sell_in == {
            "clasica": round((60000 / 49800 - 1) * 100, 2),
            "mejor_oferta": 60000 / 49800 - 1,
        }
        assert payload.markups_sell_in_out == {}

    def test_a_lot_dated_after_today_is_not_current(self, engine):
        si.compra(engine, [(ROUTER, 5, "1000.00")], D(2026, 11, 20))

        assert _payload(engine) is None

    def test_used_up_lot_leaves_the_plain_cost(self, engine):
        si.compra(engine, [(ROUTER, 2, "200.00")], D(2026, 10, 1))
        si.venta(engine, "fuera", ROUTER, 2, D(2026, 10, 20))
        _recompute_sell_in(engine, ROUTER)

        assert _payload(engine) is None

    def test_usd_purchase_converts_at_its_own_rate(self, engine):
        # 10 USD over 2 units at 1000 ARS/USD: 5000 ARS per unit, whatever today's rate is.
        si.compra(engine, [(ROUTER, 2, "10.00")], D(2026, 10, 1), moneda="USD", tipo_cambio="1000")
        so.tipo_cambio(engine, D(2026, 11, 9), 1500)

        payload = _payload(engine)

        assert payload.sell_in.descuento_unit == 5000.0
        assert payload.sell_in.costo == 45000.0


class TestSellOut:
    def test_percentage_campaign_on_the_product_cost(self, engine):
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        cid = so.campana(engine, [gid], tipo="porcentaje", monto_unit=None, porcentaje="2", base_porcentaje="costo")

        payload = _payload(engine)

        assert payload.sell_in is None
        assert payload.sell_out.monto_unit == 1000.0  # 2% of 50000
        assert payload.sell_out.campana_ids == [cid]
        assert payload.markups_sell_in == {}
        assert payload.markups_sell_in_out["clasica"] == round((61000 / 50000 - 1) * 100, 2)

    def test_sell_out_adds_to_profit_over_the_cost_with_sell_in(self, engine):
        si.compra(engine, [(ROUTER, 2, "2000.00")], D(2026, 10, 1))  # 1000 per unit
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        so.campana(engine, [gid], monto_unit="500.00")

        payload = _payload(engine)

        assert payload.markups_sell_in_out["clasica"] == round((60500 / 49000 - 1) * 100, 2)

    def test_usd_per_unit_campaign_with_vat_converts_at_its_rate(self, engine):
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        so.campana(
            engine, [gid], moneda="USD", monto_unit="1.21", monto_incluye_iva=True, tc_modo="fijo", tipo_cambio="1000"
        )

        assert _payload(engine).sell_out.monto_unit == 1000.0  # 1.21 / 1.21 = 1 USD at 1000

    def test_a_non_stackable_campaign_takes_precedence_by_id(self, engine):
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        primera = so.campana(engine, [gid], monto_unit="10.00", acumulable=False)
        so.campana(engine, [gid], monto_unit="20.00")

        sell_out = _payload(engine).sell_out

        assert sell_out.campana_ids == [primera]
        assert sell_out.monto_unit == 10.0

    def test_stackable_campaigns_add_up(self, engine):
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        ids = [so.campana(engine, [gid], monto_unit="10.00"), so.campana(engine, [gid], monto_unit="20.00")]

        sell_out = _payload(engine).sell_out

        assert sell_out.campana_ids == ids
        assert sell_out.monto_unit == 30.0

    def test_a_campaign_whose_cap_is_used_up_counts_zero(self, engine):
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        topada = so.campana(engine, [gid], monto_unit="10.00", acumulable=False, tope_unidades=1)
        siguiente = so.campana(engine, [gid], monto_unit="20.00")
        si.venta(engine, "fuera", ROUTER, 1, D(2026, 11, 5))
        _recompute_sell_out(engine, topada, siguiente)

        sell_out = _payload(engine).sell_out

        assert sell_out.campana_ids == [siguiente]
        assert sell_out.monto_unit == 20.0

    def test_money_cap_left_limits_the_unit_credit(self, engine):
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        cid = so.campana(engine, [gid], monto_unit="10.00", tope_monto="25.00")
        si.venta(engine, "fuera", ROUTER, 2, D(2026, 11, 5))
        _recompute_sell_out(engine, cid)

        assert _payload(engine).sell_out.monto_unit == 5.0

    def test_campaign_outside_today_or_voided_does_not_apply(self, engine):
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        so.campana(engine, [gid], D(2026, 10, 1), D(2026, 10, 31))
        so.campana(engine, [gid], estado="anulada")

        assert _payload(engine) is None

    def test_missing_rate_leaves_the_credit_unknown_not_guessed(self, engine):
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        cid = so.campana(engine, [gid], moneda="USD", monto_unit="1.00", tc_modo="al_cobro")

        payload = _payload(engine)

        assert payload.sell_out.campana_ids == [cid]
        assert payload.sell_out.monto_unit is None
        assert payload.markups_sell_in_out == {}


class TestNoData:
    def test_no_sell_in_nor_sell_out_is_null(self, engine):
        si.compra(engine, [(ROUTER, 2, "200.00")], D(2026, 10, 1))  # another product's lot
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        so.campana(engine, [gid])

        assert _payload(engine, SWITCH) is None

    def test_batch_reads_a_bounded_number_of_queries(self, engine):
        si.compra(engine, [(ROUTER, 2, "200.00")], D(2026, 10, 1))
        gid = so.grupo(engine, [{"marca": "TP-LINK"}])
        so.campana(engine, [gid], moneda="USD", monto_unit="1.00", tc_modo="dia_venta")
        so.tipo_cambio(engine, D(2026, 11, 9), 1000)
        statements = []
        with sessionmaker(bind=engine)() as db:
            conn = db.connection()
            event.listen(conn, "before_cursor_execute", lambda *a: statements.append(a[2]))
            resolver_sell_in_out_batch(db, [ROUTER, SWITCH, 950], HOY)

        assert len(statements) <= 6
