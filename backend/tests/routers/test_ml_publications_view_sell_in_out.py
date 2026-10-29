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
from app.models.sell_in import SellInCompra, SellInCompraItem
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
            },
            "sell_out": None,
            "markups_sell_in": {"publicacion": round(calcular_markup(limpio_of(70), COST[70] - 100.0) * 100, 2)},
            "markups_sell_in_out": {},
        }
        assert body["markup_breakdown"]["costo_ars"] == COST[70]  # the plain cost stays as it was

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
