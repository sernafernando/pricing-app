"""`sell_in_out` on the Resumen of one publication (`GET /api/ml-publications/view/items/{item_id}`, T10).

Owner rule: "Always show both: cost and cost with sell in; markup and totals without and with sell out." The field
is additive and lives next to `markup_breakdown`: it explains the same unit (the worst one) of the same linked
product, with one markup key, `publicacion`, recorded from the breakdown's own net and cost, so the markup with sell
in corresponds to the Resumen markup. Null when neither sell in nor sell out applies or nothing can be priced;
absent without `ml_metricas.ver_ganancia`. The resolver's money rules are pinned in
`tests/services/test_productos_sell_in_out_postgres.py`; this file pins the wiring and the HTTP contract.
"""

# ruff: noqa: F811 -- the fixtures are imported from the detail's test modules and used by name

from __future__ import annotations

from datetime import date

import pytest

from app.models.producto import ProductoERP
from sqlalchemy import update

from app.models.sell_in import SellInCompra, SellInCompraItem
from app.services.ml_publications.view import markup_service
from app.services.ml_publications.view.markup import unit_breakdown
from app.services.pricing_calculator import calcular_markup
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

pytestmark = pytest.mark.postgres


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


def limpio_of(product: int) -> float:
    """The net of the breakdown of `product` as `test_detail_postgres.fill` stores it (VAT 10.5, ERP shipping 120)."""
    found = unit_breakdown(
        make_ctx(), make_inputs(producto_item_id=product, costo=COST[product], iva=10.5, envio=120.0), {}
    )
    assert found is not None
    return found.limpio


class TestPayload:
    def test_the_item_level_product_with_sell_in_shows_its_cost_and_markup(
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
            "markups_sell_in": {"publicacion": round(calcular_markup(limpio_of(70), COST[70] - 100.0) * 100, 2)},
            "markups_sell_in_out": {},
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
        assert body["sell_in_out"]["markups_sell_in"] == {
            "publicacion": round(calcular_markup(limpio_of(70), COST[70] - 100.0) * 100, 2)
        }

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

    def test_a_usd_cost_without_a_rate_says_so_and_has_no_cost_with_sell_in_in_usd(
        self, client, rows, pg, analyst, pricing, db, admin_user, monkeypatch
    ) -> None:
        # No USD rate today: the breakdown says it (`tipo_cambio` null), so the panel never calls its cost "pesos";
        # the cost with sell in has no USD figure (never a guess).
        monkeypatch.setattr(markup_service, "build_pricing_context", lambda db: make_ctx(tipo_cambio_usd=None))
        with pg.begin() as conn:
            seed.add_cost(conn, 70, 40.0, moneda_costo="USD", iva=10.5, envio=120.0)
        sell_in(db, admin_user, 70)

        body = body_of(client, analyst, "MLA11")

        assert (body["markup_breakdown"]["moneda_costo"], body["markup_breakdown"]["tipo_cambio"]) == ("USD", None)
        sell_in_usd = body["sell_in_out"]["sell_in"]
        assert (sell_in_usd["moneda_costo"], sell_in_usd["costo_moneda"]) == ("USD", None)
        assert sell_in_usd["descuento_unit_moneda"] is None

    def test_the_markup_with_sell_in_is_on_the_resumen_scale(
        self, client, rows, analyst, pricing, db, admin_user
    ) -> None:
        sell_in(db, admin_user, 70, cantidad=1, monto="0.01")

        body = body_of(client, analyst, "MLA11")

        # a one-cent discount barely moves it: same percent scale as the breakdown's markup
        assert body["sell_in_out"]["markups_sell_in"]["publicacion"] == pytest.approx(
            body["markup_breakdown"]["markup"], abs=0.01
        )

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
