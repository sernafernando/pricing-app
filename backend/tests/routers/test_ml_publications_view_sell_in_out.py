"""`sell_in_out` on the Resumen of one publication (`GET /api/ml-publications/view/items/{item_id}`, T10).

Owner rule: "Always show both: cost and cost with sell in; markup and totals without and with sell out." The field
is additive and lives next to `markup_breakdown`: it explains the same unit (the worst one) of the same linked
product, with one markup key, `publicacion`, recorded from the breakdown's own net. D1 (sell-in-costo-si T3 PR 5,
owner L12: "el costo siso no existe, es costo SI y SO va en la venta, como ganancia adicional"): the sell in (FIFO
lot) is still shown, but it never comes off the cost, so there is no markup "with sell in" (`markups_sell_in` is
always empty); the markup with sell out is (net + sell out - costo SI) / costo SI. Here the SQLite pricing db has no
costo SI steps, so costo SI is the list cost (`tests/costo_si_lista.py`). Null when neither sell in nor sell out
applies or nothing can be priced; absent without `ml_metricas.ver_ganancia`. The resolver's money rules are pinned in
`tests/services/test_productos_sell_in_out_postgres.py`; this file pins the wiring and the HTTP contract.
"""

# ruff: noqa: F811 -- the fixtures are imported from the detail's test modules and used by name

from __future__ import annotations

from datetime import date, timedelta

import pytest


from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.producto import ProductoERP
from app.models.sell_out import SellOutCampana, SellOutCampanaGrupo
from sqlalchemy import update

from app.models.sell_in import SellInCompra, SellInCompraItem
from app.services.ml_publications.view import markup as markup_module
from app.services.ml_publications.view import markup_service
from app.services.ml_publications.view.markup import unit_breakdown
from tests.routers.test_ml_publications_view_markup import (  # noqa: F401
    COST,
    analyst,
    pg,
    pricing,
    reader,
    view_pg,
)
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_detail_postgres import body_of, rows  # noqa: F401
from tests.services.ml_publications.view.test_unit_markup import make_ctx, make_inputs
from tests.costo_si_lista import costo_si_lista  # noqa: F401 -- the SQLite pricing db reads lote.actuales

pytestmark = [pytest.mark.postgres, pytest.mark.usefixtures("costo_si_lista")]


def sell_in(db, user, item_id: int, cantidad: int = 2, monto: str = "200.00") -> int:
    """A purchase of `item_id` in the pricing database with `monto` ARS of sell in over `cantidad` units."""
    if db.get(ProductoERP, item_id) is None:  # the pricing database's own catalog row the purchase points to
        db.add(ProductoERP(item_id=item_id, codigo=f"C{item_id}", costo=COST[item_id], moneda_costo="ARS", iva=10.5))
        db.flush()
    compra = SellInCompra(
        fecha_compra=date(2020, 1, 1), moneda="ARS", monto_total=monto, estado="activa", usuario_id=user.id
    )
    db.add(compra)
    db.flush()
    linea = SellInCompraItem(
        compra_id=compra.id, item_id=item_id, cantidad=cantidad, costo_base_unit=1000, monto_asignado=monto
    )
    db.add(linea)
    db.commit()
    return linea.id


def sell_out(db, user, item_id: int, monto: str = "500.00") -> int:
    """A sell out campaign of `monto` ARS per unit for `item_id` in the pricing database, in force today."""
    if db.get(ProductoERP, item_id) is None:
        db.add(ProductoERP(item_id=item_id, codigo=f"C{item_id}", costo=COST[item_id], moneda_costo="ARS", iva=10.5))
        db.flush()
    grupo = OffsetGrupo(nombre=f"G{item_id}")
    db.add(grupo)
    db.flush()
    db.add(OffsetGrupoFiltro(grupo_id=grupo.id, item_id=item_id))
    hoy = date.today()
    campana = SellOutCampana(
        nombre="SO",
        fecha_desde=hoy - timedelta(days=5),
        fecha_hasta=hoy + timedelta(days=30),
        tipo="por_unidad",
        monto_unit=monto,
        moneda="ARS",
        base_porcentaje="costo",
        acumulable=True,
        monto_incluye_iva=False,
        estado="activa",
        usuario_id=user.id,
    )
    db.add(campana)
    db.flush()
    db.add(SellOutCampanaGrupo(campana_id=campana.id, grupo_id=grupo.id))
    db.commit()
    return campana.id


def markup_with_sell_out(product: int, credito: float) -> float:
    """D1 on the Resumen scale: (net + sell out - cost) / cost x 100, the cost being costo SI (here the list cost)."""
    return round((limpio_of(product) + credito - COST[product]) / COST[product] * 100, 2)


def limpio_of(product: int) -> float:
    """The net of the breakdown of `product` as `test_detail_postgres.fill` stores it (VAT 10.5, ERP shipping 120)."""
    found = unit_breakdown(
        make_ctx(), make_inputs(producto_item_id=product, costo=COST[product], iva=10.5, envio=120.0), {}
    )
    assert found is not None
    return found.limpio


class TestPayload:
    def test_the_item_level_product_with_sell_in_shows_its_lot_and_no_markup_with_sell_in(
        self, client, rows, analyst, pricing, db, admin_user
    ) -> None:
        linea = sell_in(db, admin_user, 70)

        body = body_of(client, analyst, "MLA11")

        assert body["sell_in_out"] == {
            "sell_in": {
                "compra_item_id": linea,
                "bono_id": None,  # a FIFO lot (T25: a cost bonus fills it)
                "bono_ids": [],
                "descuento_unit": 100.0,
                "costo": COST[70] - 100.0,
                "unidades_restantes": 2,
                "moneda_costo": "ARS",
                "costo_moneda": COST[70] - 100.0,
                "descuento_unit_moneda": 100.0,
            },
            "sell_out": None,
            "markups_sell_in": {},  # D1: the lot never comes off the cost of a markup
            "markups_sell_in_out": {},  # no sell out: nothing to add to the profit
        }
        assert body["markup_breakdown"]["costo_ars"] == COST[70]  # the plain cost stays as it was

    def test_a_usd_cost_shows_the_cost_and_its_sell_in_in_usd_at_the_breakdowns_rate(
        self, client, rows, pg, analyst, pricing, db, admin_user
    ) -> None:
        # S10 (owner): "si son 17,04 USD, mostrame 17,04 USD". 40 USD at the context's 1000 ARS/USD is the same
        # 40000 ARS the ARS case prices, so every ARS figure and markup is the ARS case's own.
        with pg.begin() as conn:
            seed.add_cost(conn, 70, 40.0, moneda_costo="USD", iva=10.5, envio=120.0)
        linea = sell_in(db, admin_user, 70)

        body = body_of(client, analyst, "MLA11")

        breakdown = body["markup_breakdown"]
        assert (breakdown["costo_ars"], breakdown["costo"], breakdown["moneda_costo"]) == (COST[70], 40.0, "USD")
        sell_in_usd = body["sell_in_out"]["sell_in"]
        assert sell_in_usd["compra_item_id"] == linea
        assert (sell_in_usd["costo"], sell_in_usd["descuento_unit"]) == (COST[70] - 100.0, 100.0)  # ARS, as before
        assert sell_in_usd["moneda_costo"] == "USD"
        assert sell_in_usd["costo_moneda"] == pytest.approx(39.9)  # 39900 ARS at the same 1000 ARS/USD
        assert sell_in_usd["descuento_unit_moneda"] == pytest.approx(0.1)
        assert body["sell_in_out"]["markups_sell_in"] == {}  # D1: no markup "with sell in" in any currency

    def test_a_usd_purchase_at_its_own_rate_still_reads_at_the_costs_one_rate(
        self, client, rows, pg, analyst, pricing, db, admin_user
    ) -> None:
        # Review R3-detail-rate-overwrite: the lot's discount is in ARS at ITS purchase's rate (0.10 USD x 1500 = 150
        # ARS per unit); the cost with sell in in USD is that ARS figure back at the COST's rate (the context's 1000),
        # the one the breakdown's `costo_ars` used: one rate for the cost, never the purchase's.
        with pg.begin() as conn:
            seed.add_cost(conn, 70, 40.0, moneda_costo="USD", iva=10.5, envio=120.0)
        linea = sell_in(db, admin_user, 70)
        compra = db.get(SellInCompraItem, linea).compra_id
        db.execute(
            update(SellInCompra)
            .where(SellInCompra.id == compra)
            .values(moneda="USD", tipo_cambio=1500, monto_total=0.2)
        )
        db.execute(update(SellInCompraItem).where(SellInCompraItem.id == linea).values(monto_asignado=0.2))
        db.commit()

        sell_in_usd = body_of(client, analyst, "MLA11")["sell_in_out"]["sell_in"]

        assert (sell_in_usd["costo"], sell_in_usd["descuento_unit"]) == (COST[70] - 150.0, 150.0)
        assert sell_in_usd["costo_moneda"] == pytest.approx((COST[70] - 150.0) / 1000)  # 39.85, not at 1500
        assert sell_in_usd["descuento_unit_moneda"] == pytest.approx(0.15)

    def test_a_usd_cost_without_any_rate_has_no_markup_and_no_sell_in_out(
        self, client, rows, pg, analyst, pricing, db, admin_user, monkeypatch, caplog
    ) -> None:
        # No USD rate at all (neither today's nor the costo SI reader's): the cost in pesos is unknown (interfaz §7:
        # NULL stays NULL and is logged), so there is no markup, no breakdown and no sell in / sell out companion,
        # never one priced over the USD figure taken as pesos.
        markup_module._log_no_rate.cache_clear()
        monkeypatch.setattr(markup_service, "build_pricing_context", lambda db: make_ctx(tipo_cambio_usd=None))
        with pg.begin() as conn:
            seed.add_cost(conn, 70, 40.0, moneda_costo="USD", iva=10.5, envio=120.0)
        sell_in(db, admin_user, 70)

        body = body_of(client, analyst, "MLA11")

        assert body["markup_breakdown"] is None
        assert body["sell_in_out"] is None
        assert "costo SI: no USD rate for item 70 (publication MLA11)" in caplog.text

    def test_the_markup_with_sell_out_is_on_the_resumen_scale(
        self, client, rows, analyst, pricing, db, admin_user
    ) -> None:
        sell_out(db, admin_user, 70, monto="0.01")

        body = body_of(client, analyst, "MLA11")

        # a one-cent sell out barely moves it: same percent scale as the breakdown's markup
        assert body["sell_in_out"]["markups_sell_in_out"]["publicacion"] == pytest.approx(
            body["markup_breakdown"]["markup"], abs=0.01
        )

    def test_with_sell_out_the_markup_adds_it_to_the_profit_over_the_plain_cost(
        self, client, rows, analyst, pricing, db, admin_user
    ) -> None:
        sell_out(db, admin_user, 70)

        found = body_of(client, analyst, "MLA11")["sell_in_out"]

        assert found["sell_out"]["monto_unit"] == 500.0
        assert found["markups_sell_in_out"] == {"publicacion": markup_with_sell_out(70, 500.0)}
        assert found["markups_sell_in"] == {}

    def test_a_sell_in_next_to_the_sell_out_leaves_the_markup_as_without_it(
        self, client, rows, analyst, pricing, db, admin_user
    ) -> None:
        # D1: "SO va en la venta, como ganancia adicional"; the lot is shown but never lowers the cost
        sell_out(db, admin_user, 70)
        sin_sell_in = body_of(client, analyst, "MLA11")["sell_in_out"]["markups_sell_in_out"]
        sell_in(db, admin_user, 70)

        found = body_of(client, analyst, "MLA11")["sell_in_out"]

        assert found["sell_in"]["descuento_unit"] == 100.0  # the lot is there
        assert found["markups_sell_in_out"] == sin_sell_in == {"publicacion": markup_with_sell_out(70, 500.0)}
        assert found["markups_sell_in"] == {}

    def test_with_variations_it_follows_the_worst_units_product(
        self, client, rows, analyst, pricing, db, admin_user
    ) -> None:
        sell_in(db, admin_user, 70)  # variation 11: not the unit the breakdown explains
        linea = sell_in(db, admin_user, 71)  # variation 12: the worst one

        body = body_of(client, analyst, "MLA10")

        assert body["markup_breakdown"]["variation_id"] == 12
        assert body["sell_in_out"]["sell_in"]["compra_item_id"] == linea
        assert body["sell_in_out"]["sell_in"]["costo"] == COST[71] - 100.0


class TestNull:
    def test_without_sell_in_or_sell_out_it_is_null_and_the_rest_is_unchanged(
        self, client, rows, analyst, pricing
    ) -> None:
        body = body_of(client, analyst, "MLA11")

        assert body["sell_in_out"] is None
        assert body["markup_breakdown"]["costo_ars"] == COST[70]
        assert body["product"]["costo"] == COST[70]

    def test_without_a_linked_product_it_is_null(self, client, rows, analyst, pricing, db, admin_user) -> None:
        sell_in(db, admin_user, 70)

        body = body_of(client, analyst, "MLA12")

        assert body["markup_breakdown"] is None
        assert body["sell_in_out"] is None

    def test_without_ver_ganancia_it_is_absent(self, client, rows, reader, pricing, db, admin_user) -> None:
        sell_in(db, admin_user, 70)

        body = body_of(client, reader, "MLA11")

        assert "sell_in_out" not in body
