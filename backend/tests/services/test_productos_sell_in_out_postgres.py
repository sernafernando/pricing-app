"""Sell out of a product TODAY, for the Productos screens (sell-in-sell-out T9; costo SI T5 PR B).

`resolver_sell_in_out_batch` reads, for a page of products, the campaigns that would credit the next sale, and
`markups(...)` turns each product's already-computed `limpio` values into the markups with sell out over costo SI
(D1). No sell in any more: costo SI replaced the FIFO lots and the per-sale cost bonuses, which these tests still
load to prove they give nothing. Postgres only, like the allocators it reads after (`sell_in._world`,
`sell_out._world`).
"""

from __future__ import annotations

from datetime import date
from typing import Iterator, Optional

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import sessionmaker

from app.models.producto import ProductoERP
from app.models.sell_in import SellInBonoItem
from app.models.tactical import TacticalCobranza
from app.services.productos_sell_in_out import resolver_sell_in_out_batch
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

TABLES = list(dict.fromkeys([*si.TABLES, SellInBonoItem.__table__, TacticalCobranza.__table__, *so.TABLES]))
STUBS = [*si.STUBS, so.STUBS[-1]]  # usuarios / proveedores / pedidos_compra + offsets_ganancia
BUDGET = 5  # statements of a page's batch with a USD campaign (TestNoData)


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
        conn.execute(text("DELETE FROM tactical_cobranzas"))
        conn.execute(text("DELETE FROM tacticals"))


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


def _bono_usd(engine) -> int:
    """A tactical's USD 10 per unit cost bonus over TP-LINK at a fixed rate, current on `HOY`."""
    with engine.begin() as conn:
        tactical = conn.execute(
            text(
                "INSERT INTO tacticals (tipo, nombre, marca, fecha_desde, fecha_hasta, moneda, tc_modo, tipo_cambio, "
                "usuario_id) VALUES ('sell_in', 'Synthetic', 'TP-LINK', :d, :h, 'USD', 'fijo', 1000, 7) RETURNING id"
            ),
            {"d": D(2026, 11, 1), "h": D(2026, 11, 30)},
        ).scalar()
        return conn.execute(
            text(
                "INSERT INTO sell_in_bonos_marca (base, alcance, marca, tipo, monto_unit, moneda, fecha_desde, "
                "fecha_hasta, usuario_id, tactical_id, tactical_linea) VALUES ('costo_venta', 'marca', 'TP-LINK', "
                "'por_unidad', 10, 'USD', :d, :h, 7, :t, 1) RETURNING id"
            ),
            {"d": D(2026, 11, 1), "h": D(2026, 11, 30), "t": tactical},
        ).scalar()


_FUENTES_SELL_IN = {
    "fifo_lot": lambda engine: si.compra(engine, [(ROUTER, 2, "200.00")], D(2026, 10, 1)),
    "usd_fifo_lot": lambda engine: si.compra(
        engine, [(ROUTER, 2, "10.00")], D(2026, 10, 1), moneda="USD", tipo_cambio="1000"
    ),
    "percentage_cost_bonus": lambda engine: _bono_costo(engine),
    "per_unit_cost_bonus": lambda engine: _bono_costo(engine, monto_unit="2000.00"),
    "usd_tactical_cost_bonus": _bono_usd,
}


class TestNoSellIn:
    """costo SI replaced the FIFO lots and the per-sale cost bonuses (owner L24: no per-sale loyalty ever): the
    payload has no sell in part any more, only the sell out ("c/ SO") and its markups over costo SI (D1)."""

    @pytest.mark.parametrize("fuente", sorted(_FUENTES_SELL_IN))
    def test_a_lot_or_a_cost_bonus_alone_gives_no_payload(self, engine, fuente):
        _FUENTES_SELL_IN[fuente](engine)

        assert _payload(engine) is None

    @pytest.mark.parametrize("fuente", sorted(_FUENTES_SELL_IN))
    def test_with_sell_out_the_payload_has_no_sell_in_part_and_the_markup_is_unchanged(self, engine, fuente):
        _FUENTES_SELL_IN[fuente](engine)
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        cid = so.campana(engine, [gid], monto_unit="500.00")

        payload = _payload(engine)

        assert payload.model_dump() == {
            "sell_out": {"monto_unit": 500.0, "campana_ids": [cid]},
            "markups_sell_in": {},  # D1: never filled
            "markups_sell_in_out": {
                "clasica": round((60000 + 500 - 50000) / 50000 * 100, 2),
                "mejor_oferta": (60000 + 500 - 50000) / 50000,
            },
        }

    def test_the_batch_holds_no_lot_nor_cost_bonus(self, engine):
        si.compra(engine, [(ROUTER, 2, "200.00")], D(2026, 10, 1))
        _bono_costo(engine)
        with sessionmaker(bind=engine)() as db:
            batch = resolver_sell_in_out_batch(db, [ROUTER, SWITCH], HOY)

        assert not hasattr(batch, "sell_in")
        assert not hasattr(batch, "bonos_costo")

    def test_campaigns_are_read_the_same_with_lots_and_cost_bonuses_on_the_page(self, engine):
        si.compra(engine, [(ROUTER, 2, "200.00")], D(2026, 10, 1))
        gid = so.grupo(engine, [{"marca": "TP-LINK"}])
        campanas = [so.campana(engine, [gid], monto_unit="10.00"), so.campana(engine, [gid], monto_unit="20.00")]
        _bono_costo(engine)
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
        assert (switch.sell_out.campana_ids, switch.sell_out.monto_unit) == (campanas, 30.0)
        assert (router.sell_out.campana_ids, router.sell_out.monto_unit) == (campanas, 30.0)

    def _statements(self, engine) -> int:
        statements = []
        with sessionmaker(bind=engine)() as db:
            conn = db.connection()
            event.listen(conn, "before_cursor_execute", lambda *a: statements.append(a[2]))
            resolver_sell_in_out_batch(db, [ROUTER, SWITCH, 950], HOY)
        return len(statements)

    def test_lots_and_cost_bonuses_cost_no_query(self, engine):
        nada = self._statements(engine)
        si.compra(engine, [(ROUTER, 2, "200.00")], D(2026, 10, 1))
        _bono_costo(engine)
        _bono_costo(engine, alcance="modelos", modelos=(SWITCH,))

        assert self._statements(engine) == nada


class TestSellOut:
    def test_percentage_campaign_on_the_product_cost(self, engine):
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        cid = so.campana(engine, [gid], tipo="porcentaje", monto_unit=None, porcentaje="2", base_porcentaje="costo")

        payload = _payload(engine)

        assert "sell_in" not in payload.model_dump()
        assert payload.sell_out.monto_unit == 1000.0  # 2% of 50000
        assert payload.sell_out.campana_ids == [cid]
        assert payload.markups_sell_in == {}
        assert payload.markups_sell_in_out["clasica"] == round((61000 / 50000 - 1) * 100, 2)

    def test_sell_out_adds_to_profit_and_a_fifo_lot_never_comes_off_the_cost(self, engine):
        # D1 (owner L12): "el costo siso no existe, es costo SI y SO va en la venta, como ganancia adicional".
        si.compra(engine, [(ROUTER, 2, "2000.00")], D(2026, 10, 1))  # a FIFO lot of 1000 per unit
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        so.campana(engine, [gid], monto_unit="500.00")

        payload = _payload(engine)

        assert payload.markups_sell_in == {}  # no "c/ sell in" figure on top of costo SI
        assert payload.markups_sell_in_out["clasica"] == round((60000 + 500 - 50000) / 50000 * 100, 2)
        assert payload.markups_sell_in_out["mejor_oferta"] == (60000 + 500 - 50000) / 50000


class TestCostoSi:
    """sell-in-costo-si S13 / D1: the cost of every sell in / sell out markup is costo SI (`lote.actuales`), whatever
    cost the caller's product carries: Productos, Tienda, the Publicaciones panel and the promos price on the same."""

    @staticmethod
    def _costo_si(engine, item_id: int, promedio: str, moneda: str = "ARS") -> None:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO costo_si_pasos (item_id, orden, tipo, fecha, cantidad, stock_antes, stock_base, "
                    "stock_despues, promedio_usd, moneda) VALUES (:i, 0, 'inicio', '2026-01-01', 0, 0, 0, 0, :p, :m)"
                ),
                {"i": item_id, "p": promedio, "m": moneda},
            )

    @pytest.fixture(autouse=True)
    def _clean_costo_si(self, engine):
        yield
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM costo_si_pasos"))

    def test_the_sell_out_markup_is_over_costo_si_not_the_list_cost(self, engine):
        self._costo_si(engine, ROUTER, "40000")
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        so.campana(engine, [gid], monto_unit="500.00")

        payload = _payload(engine)  # the product still carries its list cost 50000

        assert payload.markups_sell_in_out["clasica"] == round((60000 + 500 - 40000) / 40000 * 100, 2)

    def test_a_cost_based_sell_out_is_a_percentage_of_costo_si(self, engine):
        # Q7 (orchestrator): base='costo' = % of costo SI (L4.7, one cost everywhere).
        self._costo_si(engine, ROUTER, "40000")
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        so.campana(engine, [gid], tipo="porcentaje", monto_unit=None, porcentaje="2", base_porcentaje="costo")

        payload = _payload(engine)

        assert payload.sell_out.monto_unit == 800.0  # 2% of 40000, not of the list 50000
        assert payload.markups_sell_in_out["clasica"] == round((60000 + 800 - 40000) / 40000 * 100, 2)

    def test_a_usd_costo_si_is_priced_at_the_latest_usd_rate(self, engine):
        self._costo_si(engine, ROUTER, "40", moneda="USD")
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO tipo_cambio (fecha, moneda, compra, venta) VALUES ('2026-01-02', 'USD', 1, 1000)")
            )
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        so.campana(engine, [gid], monto_unit="500.00")
        try:
            payload = _payload(engine)
        finally:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM tipo_cambio"))

        assert payload.markups_sell_in_out["clasica"] == round((60000 + 500 - 40000) / 40000 * 100, 2)

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

        # Sell out (campaigns, their consumptions, their rows, today's BNA for the USD one) and the products' costo
        # SI (`lote.actuales`): no FIFO, cost-mode or cost-bonus read any more (costo SI T5 PR B).
        assert len(statements) <= BUDGET


class TestPendienteDeAprobacion:
    """Tacticals approval S2/S6: a load waiting for approval (`estado = 'pendiente'`) applies to no markup. A cost
    bonus never reaches the payload any more (its sell in is inside costo SI), so only the campaign is checked."""

    def test_a_pending_campaign_is_no_sell_out(self, engine):
        gid = so.grupo(engine, [{"item_id": ROUTER}])
        so.campana(engine, [gid], monto_unit="500.00", estado="pendiente")

        assert _payload(engine) is None  # active, it is its sell out (`TestSellOut`)
