"""Auditoría de stock (S3-S8): `GET /ml-publications/view/stock-audit` lists one row per base product with what its
ERP and Full stock is worth at cost, in USD and ARS at the day's BNA rate, its variants under it, and the KPI strip
over every row. Gated by `ml_publicaciones.ver_auditoria_stock`. Invented data only.

The world (rate 1000 ARS per USD):
* notebook 100 (USD 1000, ERP 5): MLA10 and MLA11 share user product UP10 (Full 2, counted once);
* variant 101 = notebook 100 + RAM 102 (USD 1100, ERP 3 derived from the base): MLA12, UP12 Full 1;
* 103 = notebook 100 + its warranty 104 (both filed as notebooks): base is the expensive one, 100; no publication;
* pack 110 = 10 x mouse 111 (mouse USD 2, ERP 100; pack USD 20): MLA20, UP20 Full 3 -> 30 mice;
* kit 120 = keyboard 121 + mouse 111: MLA30, UP30 Full 4 -> not shown, counted nowhere;
* PC 130 (category 47, ARS 300000, ERP 1): MLA40 paused;
* 140 (USD 10, ERP 2) has no publication; 150 has no stock.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.routers import ml_publications_view
from app.services.ml_publications.view.stock_audit import KIT, PACK, PC, VARIANTE, ComboKind, classify_combos
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import seed_rows
from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

URL = "/api/ml-publications/view/stock-audit"
PERMISO = "ml_publicaciones.ver_auditoria_stock"

BOM_DDL = (
    "CREATE TABLE IF NOT EXISTS tb_item (comp_id integer, item_id integer, item_code varchar(100), cat_id integer, "
    "subcat_id integer, PRIMARY KEY (comp_id, item_id))",
    "CREATE TABLE IF NOT EXISTS combo_componentes (combo_item_id integer, componente_item_id integer, "
    "cantidad numeric(18,4), PRIMARY KEY (combo_item_id, componente_item_id))",
)


def product(conn, item_id: int, costo: float, moneda: str, stock: int, cat: int, subcat: int = 1) -> None:
    seed.add_product(conn, item_id, f"C{item_id}", f"Producto {item_id}", marca="Marca", stock=stock)
    seed.add_cost(conn, item_id, costo, moneda_costo=moneda)
    conn.execute(
        text("INSERT INTO tb_item (comp_id, item_id, item_code, cat_id, subcat_id) VALUES (1, :i, :c, :cat, :sub)"),
        {"i": item_id, "c": f"C{item_id}", "cat": cat, "sub": subcat},
    )


def combo(conn, combo_id: int, *parts: tuple[int, int]) -> None:
    for item, qty in parts:
        conn.execute(text("INSERT INTO combo_componentes VALUES (:c, :i, :q)"), {"c": combo_id, "i": item, "q": qty})


def publication(conn, mla: str, product_id: int, up: str, status: str = "active") -> None:
    seed.add_item(conn, mla, status=status, user_product_id=up)
    seed.add_link(conn, mla, product_id)


def fill(conn) -> None:
    seed.create_presence_tables(conn)
    for ddl in BOM_DDL:
        conn.execute(text(ddl))
    seed.add_usd_rate(conn, 1000.0, "2026-11-17")
    product(conn, 100, 1000, "USD", 5, 46, 3819)
    product(conn, 101, 1100, "USD", 3, 46, 3819)
    product(conn, 102, 50, "USD", 0, 50)
    product(conn, 103, 1050, "USD", 0, 46, 3819)
    product(conn, 104, 50, "USD", 0, 46, 3819)
    product(conn, 110, 20, "USD", 0, 57)
    product(conn, 111, 2, "USD", 100, 57)
    product(conn, 120, 30, "USD", 0, 57)
    product(conn, 121, 25, "USD", 0, 57)
    product(conn, 130, 300000, "ARS", 1, 47)
    product(conn, 131, 100000, "ARS", 0, 50)
    product(conn, 140, 10, "USD", 2, 60)
    product(conn, 150, 10, "USD", 0, 60)
    combo(conn, 101, (100, 1), (102, 1))
    combo(conn, 103, (100, 1), (104, 1))
    combo(conn, 110, (111, 10))
    combo(conn, 120, (121, 1), (111, 1))
    combo(conn, 130, (131, 1), (102, 2))
    publication(conn, "MLA10", 100, "UP10")
    publication(conn, "MLA11", 100, "UP10")
    publication(conn, "MLA12", 101, "UP12")
    publication(conn, "MLA20", 110, "UP20")
    publication(conn, "MLA30", 120, "UP30")
    publication(conn, "MLA40", 130, "UP40", status="paused")
    seed.add_stock(conn, "UP10", full=2, own=0)
    seed.add_stock(conn, "UP12", full=1, own=0)
    seed.add_stock(conn, "UP20", full=3, own=0)
    seed.add_stock(conn, "UP30", full=4, own=0)


@pytest.fixture()
def started(monkeypatch) -> list[tuple]:
    seen: list[tuple] = []

    def fetch(*args, **kwargs):
        seen.append((args, kwargs))
        return {"MLA12"}

    monkeypatch.setattr(ml_publications_view, "fetch_mlas_with_started", fetch)
    return seen


@pytest.fixture()
def auditor(client, pg, db, rol_admin, admin_auth_headers, started):
    seed_rows(pg, fill)
    grant(db, rol_admin, PERMISO)
    return admin_auth_headers


def audit(client, headers, **params) -> dict:
    response = client.get(URL, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def money(unidades: int, usd: float, ars: float) -> dict:
    return {"unidades": unidades, "usd": usd, "ars": ars}


class TestClassifyCombos:
    CATS = {1: (46, 3819), 2: (50, 1), 3: (46, 3908), 4: (46, 3819), 5: (47, 1), 6: (57, 1), 7: (57, 1)}

    def test_one_notebook_component_is_a_variant_of_it(self) -> None:
        kinds = classify_combos({10: [(1, Decimal(1)), (2, Decimal(1))]}, self.CATS, {})
        assert kinds == {10: ComboKind(VARIANTE, 1, Decimal(1))}

    def test_an_accessory_notebook_subcategory_is_not_a_notebook(self) -> None:
        kinds = classify_combos({10: [(3, Decimal(1)), (2, Decimal(1))]}, self.CATS, {})
        assert kinds == {10: ComboKind(KIT)}

    def test_two_notebook_components_take_the_most_expensive_as_base(self) -> None:
        kinds = classify_combos({10: [(4, Decimal(1)), (1, Decimal(1))]}, self.CATS, {1: 1000.0, 4: 50.0})
        assert kinds[10] == ComboKind(VARIANTE, 1, Decimal(1))

    def test_a_pc_is_its_own_product_whatever_its_components(self) -> None:
        self.CATS[11] = (47, 1)
        assert classify_combos({11: [(1, Decimal(1)), (2, Decimal(1))]}, self.CATS, {}) == {11: ComboKind(PC)}

    def test_a_single_component_is_a_pack_with_its_quantity(self) -> None:
        assert classify_combos({10: [(6, Decimal(10))]}, self.CATS, {}) == {10: ComboKind(PACK, 6, Decimal(10))}

    def test_several_components_without_a_notebook_is_a_kit(self) -> None:
        assert classify_combos({10: [(6, Decimal(1)), (7, Decimal(1))]}, self.CATS, {}) == {10: ComboKind(KIT)}


@pytest.mark.postgres
class TestStockAudit:
    def test_without_the_permission_it_is_a_403(self, client, pg, db, rol_admin, admin_auth_headers) -> None:
        grant(db, rol_admin, "ml_ops.ver", "productos.ver")  # the screen alone is not enough
        response = client.get(URL, headers=admin_auth_headers)
        assert response.status_code == 403
        assert PERMISO in response.json()["error"]["message"]

    def test_rows_are_base_products_with_stock_ordered_by_total_value(self, client, auditor) -> None:
        body = audit(client, auditor)
        assert [(row["product_item_id"], row["tipo"]) for row in body["rows"]] == [
            (100, "producto"),
            (130, "pc"),
            (111, "producto"),
            (140, "producto"),
        ]
        assert body["total"] == 4
        assert (body["tipo_cambio"], body["tipo_cambio_fecha"]) == (1000.0, "2026-11-17")

    def test_a_notebook_adds_its_variants_full_but_never_their_erp(self, client, auditor) -> None:
        notebook = audit(client, auditor)["rows"][0]
        assert notebook["erp"] == money(5, 5000.0, 5_000_000.0)
        # its own Full 2 (UP10 once, though two listings share it) + variant 101's 1 at the variant's cost
        assert notebook["full"] == money(3, 3100.0, 3_100_000.0)
        assert notebook["total"] == money(8, 8100.0, 8_100_000.0)
        assert notebook["publications_count"] == 2
        assert notebook["params"] == {"producto": "100"}
        [variant] = notebook["variantes"]  # 103 (notebook + warranty) has no publication: nothing to show
        assert variant["product_item_id"] == 101 and variant["tipo"] == "variante"
        assert variant["full"] == money(1, 1100.0, 1_100_000.0)
        assert "erp" not in variant  # derived from the base: shown as "—"
        assert variant["params"] == {"producto": "101"}

    def test_a_pack_adds_its_full_in_base_units_at_the_pack_cost(self, client, auditor) -> None:
        mouse = next(row for row in audit(client, auditor)["rows"] if row["product_item_id"] == 111)
        assert mouse["erp"] == money(100, 200.0, 200_000.0)
        assert mouse["full"] == money(30, 60.0, 60_000.0)  # 3 packs of 10, each USD 20; kit 120 counts nowhere
        [pack] = mouse["variantes"]
        assert (pack["tipo"], pack["cantidad"], pack["full_unidades_base"]) == ("pack", 10.0, 30)
        assert pack["full"] == money(3, 60.0, 60_000.0)

    def test_a_pc_is_one_row_valued_in_pesos_and_dollars(self, client, auditor) -> None:
        pc = next(row for row in audit(client, auditor)["rows"] if row["product_item_id"] == 130)
        assert pc["erp"] == money(1, 300.0, 300_000.0)
        assert pc["variantes"] == []
        assert pc["publicacion_activa"] is False

    def test_the_kpis_sum_every_row(self, client, auditor) -> None:
        kpis = audit(client, auditor, limit=1)["kpis"]  # over every row, not the page
        assert kpis["erp"] == money(108, 5520.0, 5_520_000.0)
        assert kpis["full"] == money(33, 3160.0, 3_160_000.0)
        assert kpis["total"] == money(141, 8680.0, 8_680_000.0)
        assert kpis["productos"] == 4
        assert kpis["productos_sin_publicacion_activa"] == 2  # the paused PC and 140 with none
        assert kpis["productos_con_promo_aplicada"] == 1  # the notebook, through its variant's MLA12
        assert kpis["productos_sin_promo_aplicada"] == 3

    def test_each_row_says_whether_it_has_an_applied_promotion(self, client, auditor) -> None:
        promo = {row["product_item_id"]: row["promo_aplicada"] for row in audit(client, auditor)["rows"]}
        assert promo == {100: True, 130: False, 111: False, 140: False}

    def test_a_publication_filter_leaves_out_the_products_without_publication(self, client, auditor) -> None:
        body = audit(client, auditor, promo_aplicada="con")
        assert [row["product_item_id"] for row in body["rows"]] == [100]
        assert body["rows"][0]["full"] == money(1, 1100.0, 1_100_000.0)  # only MLA12's Full: the filtered ones

    def test_paging_and_ordering(self, client, auditor) -> None:
        body = audit(client, auditor, orden="descripcion", dir="asc", limit=2, offset=1)
        assert [row["product_item_id"] for row in body["rows"]] == [111, 130]
        assert (body["total"], body["orden"], body["dir"]) == (4, "descripcion", "asc")

    def test_an_unknown_order_is_a_422(self, client, auditor) -> None:
        response = client.get(URL, headers=auditor, params={"orden": "precio"})
        assert response.status_code == 422
        assert "orden" in response.text

    def test_without_the_promotions_database_the_promo_figures_are_null(self, client, auditor, monkeypatch) -> None:
        def down(*args, **kwargs):
            raise RuntimeError("ML_WEBHOOK_DB_URL not set")

        monkeypatch.setattr(ml_publications_view, "fetch_mlas_with_started", down)
        body = audit(client, auditor)
        assert body["kpis"]["productos_con_promo_aplicada"] is None
        assert all(row["promo_aplicada"] is None for row in body["rows"])
