"""GET /api/precios/variantes-envio: one markup per active publication at a given price.

Today every markup uses MAX(list_cost) across the product's active MLAs. This endpoint keeps that value for
comparison and adds one variant per active MLA, priced with ITS OWN list_cost through the same calculator, plus
a simple and a sales-weighted average.

The mlwebhook table (`ml_seller_shipping_costs`) is not reachable from tests: `_fetch_list_cost_by_mla` is
stubbed, as the existing resolver tests do. The logistic types used here are the values the code already
documents as observed in production (`mode_resolution.py`: self_service, cross_docking, fulfillment).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.models.comision_versionada import ComisionAdicionalCuota, ComisionBase, ComisionVersion
from app.models.ml_orders_ops import MlOrderItemOps
from app.models.ml_publications import MlItem
from app.models.ml_sale_line import MlSaleLine
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.services import envio_real_service
from app.services.pricing_calculator import calcular_comision_ml_total, calcular_limpio, calcular_markup

URL = "/api/precios/variantes-envio"
ITEM = 9101
COSTO = 50000.0
ABOVE = 60000.0  # above the default free-shipping threshold (33000): shipping counts
BELOW = 20000.0  # below it: the buyer pays shipping, it never reaches the markup
COSTS = {"MLA-FLEX": 2000.0, "MLA-COLECTA": 8000.0, "MLA-CUOTAS": 5000.0}


@pytest.fixture()
def asked(monkeypatch) -> list[list[str]]:
    """Stub of the mlwebhook read: records each call and answers from `COSTS`."""
    calls: list[list[str]] = []

    def fetch(mla_ids):
        calls.append(sorted(mla_ids))
        return {mla: COSTS[mla] for mla in mla_ids if mla in COSTS}

    monkeypatch.setattr(envio_real_service, "_fetch_list_cost_by_mla", fetch)
    return calls


@pytest.fixture()
def comisiones(db):
    version = ComisionVersion(nombre="Test", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=12.0))
    db.add(ComisionAdicionalCuota(version_id=version.id, cuotas=3, adicional=5.0))
    db.flush()


@pytest.fixture()
def producto(db, comisiones) -> ProductoERP:
    p = ProductoERP(
        item_id=ITEM,
        codigo="VAR-ENVIO-1",
        descripcion="Producto variantes envio",
        costo=COSTO,
        moneda_costo="ARS",
        iva=21.0,
        activo=True,
        envio=300.0,
    )
    db.add(p)
    db.flush()
    return p


def add_pub(db, mla: str, pricelist_id: int = 4, activo: bool = True, logistic: str | None = None) -> None:
    db.add(PublicacionML(mla=mla, item_id=ITEM, codigo="C", item_title="t", pricelist_id=pricelist_id, activo=activo))
    if logistic is not None:
        db.add(MlItem(item_id=mla, listing_type_id="gold_special", logistic_type=logistic))
    db.flush()


_row = iter(range(500_000, 600_000))


def add_sale(db, mla: str, qty: int, days_ago: int, product: int = ITEM) -> None:
    row = next(_row)
    when = datetime.now(UTC) - timedelta(days=days_ago)
    db.add(MlOrderItemOps(id=row, order_id=row, item_id=mla, quantity=qty))
    db.flush()
    db.add(
        MlSaleLine(
            item_row_id=row,
            order_id=row,
            group_key=f"o:{row}",
            product=product,
            mla=mla,
            group_date=when,
            day=when.date(),
            qty=qty,
            gross=1,
            tg=1,
            mtg=1,
            mcosto=1,
        )
    )
    db.flush()


def expected(precio: float, comision_pct: float, envio: float) -> tuple[float, float]:
    """(markup %, ganancia) from the existing calculator, at the given shipping cost."""
    comisiones = calcular_comision_ml_total(precio, comision_pct, 21.0)
    limpio = calcular_limpio(precio, 21.0, envio, comisiones["comision_total"])
    return calcular_markup(limpio, COSTO) * 100, limpio - COSTO


def get(client, headers, precio: float, **params):
    return client.get(URL, params={"item_id": ITEM, "precio": precio, **params}, headers=headers)


def by_mla(body) -> dict:
    return {v["mla"]: v for v in body["variantes"]}


def seed_three(db) -> None:
    add_pub(db, "MLA-FLEX", logistic="self_service")
    add_pub(db, "MLA-COLECTA", logistic="cross_docking")
    add_pub(db, "MLA-CUOTAS", pricelist_id=17, logistic="fulfillment")
    add_pub(db, "MLA-OFF", activo=False)


class TestVariantes:
    def test_each_publication_is_priced_with_its_own_shipping_cost(self, client, auth_headers, producto, db, asked):
        seed_three(db)
        body = get(client, auth_headers, ABOVE).json()
        rows = by_mla(body)

        assert set(rows) == {"MLA-FLEX", "MLA-COLECTA", "MLA-CUOTAS"}  # the inactive one is not a variant
        for mla, pct in (("MLA-FLEX", 12.0), ("MLA-COLECTA", 12.0), ("MLA-CUOTAS", 17.0)):
            markup, ganancia = expected(ABOVE, pct, COSTS[mla])
            assert rows[mla]["costo_envio"] == COSTS[mla]
            assert rows[mla]["comision_base_pct"] == pct
            assert rows[mla]["markup_pct"] == round(markup, 2)
            assert rows[mla]["ganancia"] == round(ganancia, 2)
        assert rows["MLA-FLEX"]["markup_pct"] > rows["MLA-COLECTA"]["markup_pct"]
        assert asked == [["MLA-COLECTA", "MLA-CUOTAS", "MLA-FLEX"]]  # ONE batched cost read

    def test_logistic_type_and_its_label(self, client, auth_headers, producto, db, asked):
        seed_three(db)
        rows = by_mla(get(client, auth_headers, ABOVE).json())
        assert (rows["MLA-FLEX"]["logistic_type"], rows["MLA-FLEX"]["logistica"]) == ("self_service", "flex")
        assert (rows["MLA-COLECTA"]["logistic_type"], rows["MLA-COLECTA"]["logistica"]) == ("cross_docking", "colecta")
        assert (rows["MLA-CUOTAS"]["logistic_type"], rows["MLA-CUOTAS"]["logistica"]) == ("fulfillment", "full")
        assert rows["MLA-FLEX"]["listing_type"] == "gold_special"
        assert rows["MLA-FLEX"]["pricelist_id"] == 4

    def test_below_the_free_shipping_threshold_shipping_does_not_count(self, client, auth_headers, producto, db, asked):
        seed_three(db)
        body = get(client, auth_headers, BELOW).json()
        rows = by_mla(body)
        markup, _ = expected(BELOW, 12.0, 0.0)
        assert body["envio_aplica"] is False
        assert rows["MLA-FLEX"]["markup_pct"] == rows["MLA-COLECTA"]["markup_pct"] == round(markup, 2)

    def test_a_publication_without_list_cost_is_flagged_not_dropped(self, client, auth_headers, producto, db, asked):
        seed_three(db)
        add_pub(db, "MLA-SIN-COSTO")
        add_sale(db, "MLA-SIN-COSTO", 50, days_ago=1)
        body = get(client, auth_headers, ABOVE).json()
        row = by_mla(body)["MLA-SIN-COSTO"]

        assert row["sin_costo_envio"] is True
        assert row["costo_envio"] is None and row["markup_pct"] is None and row["ganancia"] is None
        assert row["unidades_vendidas"] == 50
        assert body["publicaciones_sin_costo_envio"] == ["MLA-SIN-COSTO"]
        assert body["promedio_simple"]["publicaciones"] == 3  # left out of both averages
        assert body["promedio_ponderado"] is None
        assert all(not v["sin_costo_envio"] for m, v in by_mla(body).items() if m != "MLA-SIN-COSTO")


class TestPromedios:
    def test_weighted_by_units_sold_in_the_window_and_simple(self, client, auth_headers, producto, db, asked):
        seed_three(db)
        add_sale(db, "MLA-FLEX", 2, days_ago=1)
        add_sale(db, "MLA-FLEX", 1, days_ago=29)
        add_sale(db, "MLA-COLECTA", 1, days_ago=3)
        add_sale(db, "MLA-COLECTA", 40, days_ago=31)  # outside the 30-day window
        add_sale(db, "MLA-CUOTAS", 40, days_ago=1, product=ITEM + 1)  # another product's sale of the MLA
        body = get(client, auth_headers, ABOVE).json()

        flex, flex_g = expected(ABOVE, 12.0, COSTS["MLA-FLEX"])
        colecta, colecta_g = expected(ABOVE, 12.0, COSTS["MLA-COLECTA"])
        cuotas, cuotas_g = expected(ABOVE, 17.0, COSTS["MLA-CUOTAS"])
        rows = by_mla(body)
        assert [rows[m]["unidades_vendidas"] for m in ("MLA-FLEX", "MLA-COLECTA", "MLA-CUOTAS")] == [3, 1, 0]
        assert body["ventana_dias"] == 30
        assert body["ponderacion"] == "unidades_vendidas"
        assert body["promedio_ponderado"] == {
            "markup_pct": round((3 * flex + 1 * colecta) / 4, 2),
            "ganancia": round((3 * flex_g + 1 * colecta_g) / 4, 2),
            "unidades": 4,
        }
        assert body["promedio_simple"] == {
            "markup_pct": round((flex + colecta + cuotas) / 3, 2),
            "ganancia": round((flex_g + colecta_g + cuotas_g) / 3, 2),
            "publicaciones": 3,
        }

    def test_without_sales_the_weighted_average_is_null(self, client, auth_headers, producto, db, asked):
        seed_three(db)
        body = get(client, auth_headers, ABOVE).json()
        assert body["promedio_ponderado"] is None
        assert body["promedio_simple"]["publicaciones"] == 3


class TestActual:
    def test_todays_max_based_markup_matches_calcular_markup(self, client, auth_headers, producto, db, asked):
        seed_three(db)
        body = get(client, auth_headers, ABOVE).json()
        hoy = client.get(
            "/api/precios/calcular-markup", params={"item_id": ITEM, "precio": ABOVE}, headers=auth_headers
        ).json()

        markup, ganancia = expected(ABOVE, 12.0, max(COSTS.values()))
        assert body["actual"]["costo_envio"] == max(COSTS.values())
        assert body["actual"]["origen"] == "max_publicaciones"
        assert body["actual"]["markup_pct"] == hoy["markup"] == round(markup, 2)
        assert body["actual"]["ganancia"] == round(ganancia, 2)
        rows = by_mla(body)  # each publication at today's MAX too, with its own commission
        assert rows["MLA-FLEX"]["markup_pct_actual"] == round(markup, 2)
        assert rows["MLA-CUOTAS"]["markup_pct_actual"] == round(expected(ABOVE, 17.0, max(COSTS.values()))[0], 2)

    def test_without_publications_today_falls_back_to_erp_envio(self, client, auth_headers, producto, asked):
        body = get(client, auth_headers, ABOVE).json()
        assert body["variantes"] == []
        assert body["actual"]["costo_envio"] == 300.0
        assert body["actual"]["origen"] == "erp"
        assert body["promedio_simple"] is None and body["promedio_ponderado"] is None
        assert asked == []


class TestEndpoint:
    def test_requires_authentication(self, client, producto):
        assert client.get(URL, params={"item_id": ITEM, "precio": ABOVE}).status_code == 401

    def test_unknown_product_is_404(self, client, auth_headers, asked):
        resp = client.get(URL, params={"item_id": 1, "precio": ABOVE}, headers=auth_headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["message"] == "Producto no encontrado"

    def test_price_must_be_positive(self, client, auth_headers, producto):
        assert get(client, auth_headers, 0).status_code == 422

    def test_query_count_does_not_grow_with_publications(
        self, client, auth_headers, producto, db, asked, query_counter
    ):
        seed_three(db)
        with query_counter() as few:
            get(client, auth_headers, ABOVE)
        for n in range(10):
            add_pub(db, f"MLA-X{n}", logistic="self_service")
            add_sale(db, f"MLA-X{n}", 1, days_ago=1)
        with query_counter() as many:
            get(client, auth_headers, ABOVE)
        assert many.total == few.total
