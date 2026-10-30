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
from app.models.sell_in import SellInBonoItem, SellInBonoMarca
from app.services.productos_sell_in_out import resolver_sell_in_out_batch
from app.services.sell_in.bonos_alcance import del_alcance
from app.services.sell_in import visor_lotes
from app.services.sell_in.costing import get_costing
from app.services.sell_out import alcance, asignacion
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in import _bono_world as bw
from tests.services.sell_in import _world as si
from tests.services.sell_out import _world as so

pytestmark = pytest.mark.postgres

D = date
HOY = D(2026, 11, 10)
ROUTER = 2964  # TP-LINK Routers, iva 21, cost 50000 ARS
SWITCH = 2270  # TP-LINK Switches, iva 10.5, no sell in nor sell out anywhere

TABLES = list(dict.fromkeys([*si.TABLES, SellInBonoItem.__table__, *so.TABLES]))
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
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM sell_in_bonos_marca"))  # items and consumptions cascade


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


def _bono_costo(engine, porcentaje: str = "3.00", **kw) -> int:
    """A % of cost bonus (T25) over TP-LINK, current on `HOY`."""
    kw.setdefault("desde", D(2026, 11, 1))
    kw.setdefault("hasta", D(2026, 11, 30))
    return bw.bono_costo(engine, porcentaje, **kw)


def _consumido(engine, bono_id: int, unidades: int, descuento: str) -> None:
    """What the allocator already gave a sale from the bonus (`sell_in_bono_consumos`)."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sell_in_bono_consumos (bono_id, canal, venta_ref, item_id, fecha_venta, unidades, "
                "descuento_ars) VALUES (:b, 'fuera', :r, :i, :f, :u, :d)"
            ),
            {"b": bono_id, "r": 900_000 + bono_id, "i": ROUTER, "f": D(2026, 11, 5), "u": unidades, "d": descuento},
        )


class TestCostBonus:
    """T25 (S31, rule 5 exclusive per unit): the next sale takes a FIFO lot's units first; with none left, an active
    % of cost bonus is the product's sell in: its % of the product's current cost without VAT (50000 ARS)."""

    def test_a_current_fifo_lot_stays_the_sell_in_whatever_cost_bonus_reaches_it(self, engine):
        (lote,) = si.compra(engine, [(ROUTER, 2, "200.00")], D(2026, 10, 1))
        _bono_costo(engine)

        payload = _payload(engine)

        assert payload.sell_in.model_dump() == {
            "compra_item_id": lote,
            "bono_id": None,
            "bono_ids": [],
            "descuento_unit": 100.0,
            "costo": 49900.0,
            "unidades_restantes": 2,
        }

    def test_with_no_lot_left_an_active_cost_bonus_is_the_sell_in(self, engine):
        bono = _bono_costo(engine)

        payload = _payload(engine)

        assert payload.sell_in.model_dump() == {
            "compra_item_id": None,
            "bono_id": bono,
            "bono_ids": [bono],
            "descuento_unit": 1500.0,  # 3 % of 50000
            "costo": 48500.0,
            "unidades_restantes": None,
        }
        assert payload.markups_sell_in["clasica"] == round((60000 / 48500 - 1) * 100, 2)

    def test_a_used_up_lot_gives_way_to_the_cost_bonus(self, engine):
        si.compra(engine, [(ROUTER, 2, "200.00")], D(2026, 10, 1))
        si.venta(engine, "fuera", ROUTER, 2, D(2026, 10, 20))
        _recompute_sell_in(engine, ROUTER)
        bono = _bono_costo(engine)

        assert (_payload(engine).sell_in.bono_id, _payload(engine).sell_in.descuento_unit) == (bono, 1500.0)

    def test_the_lot_viewer_names_the_cost_bonus_the_screens_show_when_no_lot_is_left(self, engine):
        # The lot viewer (visor_lotes) says what applies instead of the used-up lots: the same decision as above.
        si.compra(engine, [(ROUTER, 2, "200.00")], D(2026, 10, 1))
        si.venta(engine, "fuera", ROUTER, 2, D(2026, 10, 20))
        _recompute_sell_in(engine, ROUTER)
        bono = _bono_costo(engine)

        with sessionmaker(bind=engine)() as db:
            sell_in = visor_lotes.bono_costo(db, ROUTER, HOY)
            sin_bono = visor_lotes.bono_costo(db, 950, HOY)  # MERCUSYS: the TP-LINK bonus does not reach it

        assert (sell_in.bono_ids, sell_in.descuento_unit) == ([bono], 1500.0)
        assert sin_bono is None

    def test_the_lot_viewer_names_the_cost_bonus_that_follows_the_last_lot(self, engine):
        # With a current lot, the screens show the lot (rule 5); the viewer still says what applies once it runs out.
        si.compra(engine, [(ROUTER, 2, "200.00")], D(2026, 10, 1))
        bono = _bono_costo(engine)

        with sessionmaker(bind=engine)() as db:
            sell_in = visor_lotes.bono_costo(db, ROUTER, HOY)

        assert (sell_in.bono_ids, sell_in.descuento_unit) == ([bono], 1500.0)
        assert _payload(engine).sell_in.compra_item_id is not None  # the screens are unchanged

    def test_the_lot_viewer_converts_a_usd_cost_at_the_rate_and_shows_nothing_without_one(self, engine):
        # A USD-cost product: the bonus's % applies to its cost in ARS at the current rate, as the screens do; with no
        # rate there is no ARS cost, so no bonus amount (never a guess, never an error).
        bono = _bono_costo(engine)
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE productos_erp SET costo = 40, moneda_costo = 'USD' WHERE item_id = :i"), {"i": ROUTER}
            )
        try:
            with sessionmaker(bind=engine)() as db:
                sin_tasa = visor_lotes.bono_costo(db, ROUTER, HOY)
            so.tipo_cambio(engine, D(2026, 11, 9), 1250)
            with sessionmaker(bind=engine)() as db:
                con_tasa = visor_lotes.bono_costo(db, ROUTER, HOY)
        finally:
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE productos_erp SET costo = 50000, moneda_costo = 'ARS' WHERE item_id = :i"),
                    {"i": ROUTER},
                )

        assert sin_tasa is None
        assert (con_tasa.bono_ids, con_tasa.descuento_unit) == ([bono], 1500.0)  # 3 % of 40 USD x 1250

    def test_a_percentage_with_vat_is_divided_by_the_product_rate(self, engine):
        # S33: "el tilde tendría que restar el iva"; the router's VAT is 21 %: 3 / 1.21 % of 50000.
        _bono_costo(engine, incluye_iva=True)

        assert _payload(engine).sell_in.descuento_unit == 1239.67

    def test_a_model_takes_its_own_percentage(self, engine):
        bono = _bono_costo(engine, alcance="modelos", modelos=(ROUTER, SWITCH))
        bw.valor_de_modelo(engine, bono, ROUTER, porcentaje="5.00")

        assert _payload(engine).sell_in.descuento_unit == 2500.0
        assert _payload(engine, SWITCH).sell_in.descuento_unit == 1500.0

    def test_a_category_bonus_reaches_only_that_category(self, engine):
        # The scope is the panel's (`bonos_alcance.del_alcance`): the router is a Routers product, the switch is not.
        bono = _bono_costo(engine, alcance="categoria", categoria="Routers")

        assert _payload(engine).sell_in.bono_ids == [bono]
        assert _payload(engine, SWITCH) is None

    def test_the_scope_matches_the_panel_rule_for_every_scope_and_edge(self, engine):
        # Parity with `bonos_alcance.del_alcance`: the resolver matches the scope in one set-based query, and every
        # (bonus, product) pair it reaches must be the panel's. 951 has neither brand nor category; the router is
        # listed in no model bonus; the switch and 950 are listed each in another one.
        sin_nada = 951
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO productos_erp (item_id, codigo, descripcion, costo, moneda_costo, iva) "
                    "VALUES (:i, 'C951', 'Sin marca', 50000, 'ARS', 21)"
                ),
                {"i": sin_nada},
            )
        try:
            ids = [ROUTER, SWITCH, 950, sin_nada]
            for kw in (
                {"alcance": "marca", "marca": "TP-LINK"},
                {"alcance": "marca", "marca": "OTRA"},
                {"alcance": "categoria", "categoria": "Routers"},
                {"alcance": "categoria", "categoria": "Sin productos"},
                {"alcance": "modelos", "modelos": (SWITCH,)},
                {"alcance": "modelos", "modelos": (950,)},
            ):
                _bono_costo(engine, "1.00", **kw)
            with sessionmaker(bind=engine)() as db:
                panel = {
                    (bono.id, item)
                    for bono in db.query(SellInBonoMarca)
                    for (item,) in db.query(ProductoERP.item_id).filter(
                        ProductoERP.item_id.in_(ids), del_alcance(db, bono, ProductoERP.item_id, None)
                    )
                }
                batch = resolver_sell_in_out_batch(db, ids, HOY)
                resolver = {(x.bono.id, item) for item, xs in batch.bonos_costo.items() for x in xs}
                payloads = {item: batch.markups(db.get(ProductoERP, item)).payload() for item in ids}

            assert resolver == panel
            assert len(panel) == 6  # router: brand + category; switch: brand + model; 950: category + model
            for item in ids:
                esperados = sorted(bid for bid, i in panel if i == item)
                assert (payloads[item].sell_in.bono_ids if payloads[item] else []) == esperados
        finally:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM productos_erp WHERE item_id = :i"), {"i": sin_nada})

    def test_a_page_with_campaigns_and_cost_bonuses_reads_the_campaigns_as_alone(self, engine):
        # The cost bonuses ride on the campaigns' query (UNION ALL): the campaigns per product must not change.
        si.compra(engine, [(ROUTER, 2, "200.00")], D(2026, 10, 1))  # the router has a lot, the switch has none
        gid = so.grupo(engine, [{"marca": "TP-LINK"}])
        campanas = [so.campana(engine, [gid], monto_unit="10.00"), so.campana(engine, [gid], monto_unit="20.00")]
        bono = _bono_costo(engine)
        ids = [ROUTER, SWITCH, 950]
        with sessionmaker(bind=engine)() as db:
            solo = alcance.campanas_por_item(db, {(i, HOY) for i in ids})
            batch = resolver_sell_in_out_batch(db, ids, HOY)
            switch = batch.markups(db.get(ProductoERP, SWITCH)).payload()
            router = batch.markups(db.get(ProductoERP, ROUTER)).payload()

        assert solo == {ROUTER: set(campanas), SWITCH: set(campanas)}
        assert {i: [x.campana.id for x in xs] for i, xs in batch.campanas.items()} == {
            i: sorted(cs) for i, cs in solo.items()
        }
        assert (switch.sell_in.bono_ids, switch.sell_out.campana_ids, switch.sell_out.monto_unit) == (
            [bono],
            campanas,
            30.0,
        )
        assert (router.sell_in.compra_item_id is not None, router.sell_in.bono_ids) == (True, [])
        assert router.sell_out.campana_ids == campanas

    def test_several_cost_bonuses_stack_up_to_the_cost(self, engine):
        primero = _bono_costo(engine, "60.00")
        segundo = _bono_costo(engine, "60.00")
        _bono_costo(engine, "1.00")  # nothing left of the cost: it gives nothing

        sell_in = _payload(engine).sell_in

        assert (sell_in.bono_id, sell_in.descuento_unit, sell_in.costo) == (primero, 50000.0, 0.0)
        assert sell_in.bono_ids == [primero, segundo]  # every bonus that gives something, in id order

    @pytest.mark.parametrize("cual", ["el_primero", "el_segundo"])
    def test_a_not_acumulable_bonus_does_not_stack_with_an_earlier_one(self, engine, cual):
        # T27b (S36), the allocator's precedence: the lower id takes the unit, the other gives nothing.
        primero = _bono_costo(engine, "3.00")
        segundo = _bono_costo(engine, "2.00")
        bw.update_bono(engine, primero if cual == "el_primero" else segundo, acumulable=False)

        sell_in = _payload(engine).sell_in

        assert (sell_in.bono_ids, sell_in.descuento_unit, sell_in.costo) == ([primero], 1500.0, 48500.0)

    def test_an_acumulable_bonus_after_an_exclusive_one_stacks_with_the_first_only(self, engine):
        # The exclusive second takes no unit the first holds; the third stacks with the first (both acumulable) and
        # takes what the exclusive one left: the whole next unit.
        primero = _bono_costo(engine, "3.00")
        segundo = _bono_costo(engine, "2.00")
        bw.update_bono(engine, segundo, acumulable=False)
        tercero = _bono_costo(engine, "1.00")

        sell_in = _payload(engine).sell_in

        assert (sell_in.bono_ids, sell_in.descuento_unit, sell_in.costo) == ([primero, tercero], 2000.0, 48000.0)

    def test_a_vat_loaded_bonus_on_a_product_without_vat_leaves_no_cost_bonus_sell_in(self, engine):
        # Like the allocator (`bonos_costo.recalcular`): the product's whole component fails, every bonus of it.
        _bono_costo(engine, "3.00")
        _bono_costo(engine, "2.00", incluye_iva=True)
        bw.set_iva(engine, ROUTER, None)
        try:
            assert _payload(engine) is None
        finally:
            bw.set_iva(engine, ROUTER, so.PRODUCTOS[ROUTER][3])

    def test_a_bonus_whose_cap_is_used_up_does_not_apply(self, engine):
        topado = _bono_costo(engine, tope_unidades=2)
        _consumido(engine, topado, 2, "3000.00")
        siguiente = _bono_costo(engine, "1.00", tope_monto="5000.00")
        _consumido(engine, siguiente, 1, "4900.00")

        sell_in = _payload(engine).sell_in

        # The first gives nothing; the second only the money its cap has left.
        assert (sell_in.bono_id, sell_in.descuento_unit) == (siguiente, 100.0)

    def test_a_bonus_outside_today_voided_or_on_invoices_does_not_apply(self, engine):
        _bono_costo(engine, desde=D(2026, 10, 1), hasta=D(2026, 10, 31))
        _bono_costo(engine, estado="anulada")
        bw.bono(engine, desde=D(2026, 11, 1), hasta=D(2026, 11, 30))  # an invoice bonus: it lives in the FIFO lots

        assert _payload(engine) is None

    def _statements(self, engine) -> int:
        statements = []
        with sessionmaker(bind=engine)() as db:
            conn = db.connection()
            event.listen(conn, "before_cursor_execute", lambda *a: statements.append(a[2]))
            resolver_sell_in_out_batch(db, [ROUTER, SWITCH, 950], HOY)
        return len(statements)

    def test_cost_bonuses_of_any_scope_cost_one_query_more_than_none_active(self, engine):
        sin_bonos = self._statements(engine)  # FIFO and sell out; the bonuses' scope rides on the campaigns' query
        _bono_costo(engine)
        _bono_costo(engine, alcance="modelos", modelos=(SWITCH,))

        assert self._statements(engine) == sin_bonos + 1  # the reached bonuses' rows and caps, every bonus in one query


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

    def test_a_product_with_its_own_amount_shows_it_and_the_others_the_campaign_one(self, engine):
        # T22b S25: a grouped campaign, the router with its own amount, the switch with the campaign's.
        gid = so.grupo(engine, [{"marca": "TP-LINK"}])
        cid = so.campana(engine, [gid], monto_unit="10.00")
        so.monto_item(engine, cid, ROUTER, "35.00")

        assert _payload(engine).sell_out.monto_unit == 35.0
        assert _payload(engine, SWITCH).sell_out.monto_unit == 10.0

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
        cid = so.campana(engine, [gid], moneda="USD", monto_unit="1.00", tc_modo="dia_venta")
        so.monto_item(engine, cid, ROUTER, "2.00")
        so.tipo_cambio(engine, D(2026, 11, 9), 1000)
        statements = []
        with sessionmaker(bind=engine)() as db:
            conn = db.connection()
            event.listen(conn, "before_cursor_execute", lambda *a: statements.append(a[2]))
            resolver_sell_in_out_batch(db, [ROUTER, SWITCH, 950], HOY)

        assert len(statements) <= 6  # no cost bonus active: the T25 lookup costs no statement
