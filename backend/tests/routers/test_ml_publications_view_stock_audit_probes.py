"""Independent probes of the Auditoría de stock view (S3-S8, S10 and the L2 / L5 rules), written from the feature
document, not from the implementation. Invented data only.

The world (rate 1000 ARS per USD):
* notebook 200 (USD 1000, ERP 4): MLA200A and MLA200B share UP200 (Full 2, counted once);
* 201 a warranty filed as a notebook (USD 100); variant 202 = 200 + 201 (USD 1200, ERP 9): base is 200 (L2 a),
  MLA202 / UP202 Full 1, its ERP never added nor shown;
* 281 = 200 + mouse 205 (a variant with ERP 6 and no publication);
* bag 203 (cat 46, accessory subcat 3908, USD 20, ERP 10) and kit 204 = 203 + mouse 205 (ERP 3): MLA204 / UP204
  Full 5 -> hidden, counts nowhere; kit 282 = 203 + 2 mice (ERP 7, no publication) hidden too;
* sleeve 207 (cat 46, accessory subcat 3964, USD 8) and 208 = 3 x 207 (USD 24): a pack, never a variant;
  MLA208 / UP208 Full 2 -> 6 sleeves worth USD 48;
* PC 210 (cat 47, ARS 500000, ERP 2) = notebook 200 + mouse: its own row, never exploded; MLA210 paused, Full 1;
* MLA300 has two variations linked to 220 (USD 50) and 221 (USD 70): UPV1 Full 3 and UPV2 Full 7, the item-level
  UPITEM Full 100 must not count; MLA301 (variation 1 also -> 220, UPV1) shares UPV1: counted once;
* 230 (ARS 5000, ERP 0) and pack 231 = 2 x 230 (ARS 9000): MLA231 / UP231 Full 4 -> 8 units, ARS 36000;
* 240 has no cost (ERP 5); 250 ERP -3 with MLA250 and no Full; 251 ERP -2; 260 (USD 10, ERP 1) has no publication;
  270 (ERP 0, MLA270 without Full) has no stock.
Started promotions: MLA202 and MLA300.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.routers import ml_publications_view
from app.services.ml_publications.view import stock_audit
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import seed_rows
from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401
from tests.routers.test_ml_publications_view_stock_audit import (
    BOM_DDL,
    PERMISO,
    URL,
    board_row,
    combo,
    money,
    product,
    publication,
)
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

STARTED = {"MLA202", "MLA300"}


def fill(conn) -> None:
    seed.create_presence_tables(conn)
    for ddl in BOM_DDL:
        conn.execute(text(ddl))
    seed.add_usd_rate(conn, 1000.0, "2026-11-17")
    product(conn, 200, 1000, "USD", 4, 46, 3819)
    product(conn, 201, 100, "USD", 0, 46, 3819)
    product(conn, 202, 1200, "USD", 9, 46, 3819)
    product(conn, 281, 1005, "USD", 6, 46, 3819)
    product(conn, 203, 20, "USD", 10, 46, 3908)
    product(conn, 204, 25, "USD", 3, 57)
    product(conn, 282, 30, "USD", 7, 57)
    product(conn, 205, 5, "USD", 0, 57)
    product(conn, 207, 8, "USD", 0, 46, 3964)
    product(conn, 208, 24, "USD", 0, 57)
    product(conn, 210, 500000, "ARS", 2, 47)
    product(conn, 220, 50, "USD", 0, 60)
    product(conn, 221, 70, "USD", 0, 60)
    product(conn, 230, 5000, "ARS", 0, 60)
    product(conn, 231, 9000, "ARS", 0, 60)
    product(conn, 240, 1, "USD", 5, 60)
    seed.add_cost(conn, 240, None, moneda_costo="USD")
    product(conn, 250, 10, "USD", -3, 60)
    product(conn, 251, 10, "USD", -2, 60)
    product(conn, 260, 10, "USD", 1, 60)
    product(conn, 270, 10, "USD", 0, 60)
    combo(conn, 202, (200, 1), (201, 1))
    combo(conn, 281, (200, 1), (205, 1))
    combo(conn, 204, (203, 1), (205, 1))
    combo(conn, 282, (203, 1), (205, 2))
    combo(conn, 208, (207, 3))
    combo(conn, 210, (200, 1), (205, 1))
    combo(conn, 231, (230, 2))
    publication(conn, "MLA200A", 200, "UP200")
    publication(conn, "MLA200B", 200, "UP200", kind="gold_pro")
    publication(conn, "MLA202", 202, "UP202")
    publication(conn, "MLA204", 204, "UP204")
    publication(conn, "MLA208", 208, "UP208")
    publication(conn, "MLA210", 210, "UP210", status="paused")
    publication(conn, "MLA231", 231, "UP231")
    publication(conn, "MLA250", 250, "UP250")
    publication(conn, "MLA270", 270, "UP270")
    # one listing, two variations linked to two products (each with its own user product)
    seed.add_item(conn, "MLA300", status="active", user_product_id="UPITEM", listing_type_id="gold_special")
    seed.add_variation(conn, "MLA300", 1, user_product_id="UPV1")
    seed.add_variation(conn, "MLA300", 2, user_product_id="UPV2")
    seed.add_link(conn, "MLA300", 220, variation_id=1)
    seed.add_link(conn, "MLA300", 221, variation_id=2)
    # a second listing of variation 1's user product
    seed.add_item(conn, "MLA301", status="active", user_product_id="UPITEM2", listing_type_id="gold_pro")
    seed.add_variation(conn, "MLA301", 1, user_product_id="UPV1")
    seed.add_link(conn, "MLA301", 220, variation_id=1)
    for up, full in (
        ("UP200", 2),
        ("UP202", 1),
        ("UP204", 5),
        ("UP208", 2),
        ("UP210", 1),
        ("UP231", 4),
        ("UP250", 0),
        ("UP270", 0),
        ("UPV1", 3),
        ("UPV2", 7),
        ("UPITEM", 100),
        ("UPITEM2", 50),
    ):
        seed.add_stock(conn, up, full=full, own=0)


@pytest.fixture()
def started(monkeypatch) -> None:
    monkeypatch.setattr(ml_publications_view, "fetch_mlas_with_started", lambda *a, **k: set(STARTED))


@pytest.fixture()
def auditor(client, pg, db, rol_admin, admin_auth_headers, started):
    seed_rows(pg, fill)
    grant(db, rol_admin, PERMISO)
    return admin_auth_headers


def audit(client, headers, **params) -> dict:
    response = client.get(URL, headers=headers, params={"limit": 100, **params})
    assert response.status_code == 200, response.text
    return response.json()


def by_id(body: dict) -> dict[int, dict]:
    return {row["product_item_id"]: row for row in body["rows"]}


@pytest.mark.postgres
class TestProbeRows:
    def test_only_base_rows_with_stock_are_listed(self, client, auditor) -> None:
        rows = by_id(audit(client, auditor))
        # 202/281 variants, 204/282 kits, 208/231 packs are no rows; 201, 205, 270 no stock; 250/251 negative ERP
        assert sorted(rows) == [200, 203, 207, 210, 220, 221, 230, 240, 260]

    def test_a_variant_with_two_notebooks_goes_under_the_most_expensive_and_adds_only_its_full(
        self, client, auditor
    ) -> None:
        notebook = by_id(audit(client, auditor))[200]
        assert notebook["tipo"] == "producto"
        assert notebook["erp"] == money(4, 4000.0, 4_000_000.0)  # never 202's 9 nor 281's 6 ERP units
        assert notebook["full"] == money(3, 3200.0, 3_200_000.0)  # UP200 once (2) + 202's 1 at USD 1200
        assert notebook["total"] == money(7, 7200.0, 7_200_000.0)
        variant = next(v for v in notebook["variantes"] if v["product_item_id"] == 202)
        assert variant["tipo"] == "variante"
        assert variant["full"] == money(1, 1200.0, 1_200_000.0)
        assert "erp" not in variant
        # the PC holding notebook 200 is never one of its variants
        assert 210 not in [v["product_item_id"] for v in notebook["variantes"]]

    def test_a_variant_without_publication_is_not_listed_under_its_base(self, client, auditor) -> None:
        notebook = by_id(audit(client, auditor))[200]
        assert [v["product_item_id"] for v in notebook["variantes"]] == [202]

    def test_kits_are_hidden_and_never_add_to_their_components(self, client, auditor) -> None:
        bag = by_id(audit(client, auditor))[203]
        assert bag["erp"] == money(10, 200.0, 200_000.0)
        assert bag["full"] == money(0, None, None)  # kit 204's Full 5 counts nowhere
        assert bag["variantes"] == []

    def test_an_accessory_subcategory_combo_is_a_pack_not_a_variant(self, client, auditor) -> None:
        sleeve = by_id(audit(client, auditor))[207]
        assert sleeve["full"] == money(6, 48.0, 48_000.0)  # 2 packs x 3 at the pack's USD 24
        [pack] = sleeve["variantes"]
        assert (pack["tipo"], pack["cantidad"], pack["full_unidades_base"]) == ("pack", 3.0, 6)

    def test_a_pc_is_one_row_with_its_own_stock(self, client, auditor) -> None:
        pc = by_id(audit(client, auditor))[210]
        assert pc["tipo"] == "pc"
        assert pc["erp"] == money(2, 1000.0, 1_000_000.0)
        assert pc["full"] == money(1, 500.0, 500_000.0)
        assert pc["variantes"] == []

    def test_full_is_read_per_variation_and_each_user_product_once(self, client, auditor) -> None:
        rows = by_id(audit(client, auditor))
        assert rows[220]["full"] == money(3, 150.0, 150_000.0)  # UPV1 once, though MLA300 and MLA301 share it
        assert rows[221]["full"] == money(7, 490.0, 490_000.0)  # never the item-level UPITEM's 100

    def test_an_ars_pack_counts_base_units_at_the_pack_cost_with_the_bna_rate(self, client, auditor) -> None:
        base = by_id(audit(client, auditor))[230]
        assert base["erp"] == money(0, None, None)
        assert base["full"] == money(8, 36.0, 36_000.0)

    def test_a_product_without_cost_has_an_unknown_value_never_zero(self, client, auditor) -> None:
        assert by_id(audit(client, auditor))[240]["erp"] == money(5, None, None)


@pytest.mark.postgres
class TestProbeKpis:
    def test_the_kpis_cover_every_row_whatever_the_page(self, client, auditor) -> None:
        kpis = audit(client, auditor, limit=1)["kpis"]
        assert kpis["erp"] == money(22, 5210.0, 5_210_000.0)
        assert kpis["full"] == money(28, 4424.0, 4_424_000.0)
        assert kpis["total"] == money(50, 9634.0, 9_634_000.0)
        assert kpis["productos"] == 9
        # 203 and 240 / 260 without publication, the paused PC
        assert kpis["productos_sin_publicacion_activa"] == 4
        assert kpis["productos_con_promo_aplicada"] == 3  # 200 (MLA202), 220 and 221 (MLA300)
        assert kpis["productos_sin_promo_aplicada"] == 6


@pytest.mark.postgres
class TestProbeFilters:
    def test_sin_promo_aplicada_drops_the_started_ones_and_the_products_without_publication(
        self, client, auditor
    ) -> None:
        body = audit(client, auditor, promo_aplicada="sin")
        rows = by_id(body)
        # 220 stays through MLA301 (variation 1, not started); 221 had only the started MLA300
        assert sorted(rows) == [200, 207, 210, 220, 230]
        assert rows[220]["full"] == money(3, 150.0, 150_000.0)
        assert rows[200]["full"] == money(2, 2000.0, 2_000_000.0)  # variant 202's MLA is filtered out
        assert rows[200]["variantes"] == []
        assert body["kpis"]["productos"] == 5

    def test_con_promo_aplicada_keeps_only_the_started_publications(self, client, auditor) -> None:
        rows = by_id(audit(client, auditor, promo_aplicada="con"))
        assert sorted(rows) == [200, 220, 221]
        assert rows[200]["full"] == money(1, 1200.0, 1_200_000.0)

    def test_an_unknown_promo_aplicada_value_is_a_422(self, client, auditor) -> None:
        assert client.get(URL, headers=auditor, params={"promo_aplicada": "maybe"}).status_code == 422


@pytest.mark.postgres
class TestProbePermission:
    def test_every_other_permission_without_the_audit_one_is_a_403(
        self, client, pg, db, rol_admin, admin_auth_headers, started
    ) -> None:
        seed_rows(pg, fill)
        grant(db, rol_admin, "ml_ops.ver", "productos.ver", "ml_metricas.ver", "ml_metricas.ver_ganancia")
        response = client.get(URL, headers=admin_auth_headers)
        assert response.status_code == 403
        assert PERMISO in response.json()["error"]["message"]

    def test_a_plain_user_gets_a_403(self, client, pg, auth_headers, started) -> None:
        assert client.get(URL, headers=auth_headers).status_code == 403


def no_rate_fill(conn) -> None:
    seed.create_presence_tables(conn)
    for ddl in BOM_DDL:
        conn.execute(text(ddl))
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS tipo_cambio (id serial PRIMARY KEY, fecha date, moneda varchar(10), "
            "compra double precision, venta double precision, timestamp_actualizacion timestamptz DEFAULT now())"
        )
    )
    product(conn, 300, 10, "USD", 2, 60)
    product(conn, 301, 5000, "ARS", 3, 60)


@pytest.mark.postgres
class TestProbeNoRate:
    def test_without_a_rate_the_other_currency_is_unknown(
        self, client, pg, db, rol_admin, admin_auth_headers, started
    ) -> None:
        seed_rows(pg, no_rate_fill)
        grant(db, rol_admin, PERMISO)
        body = audit(client, admin_auth_headers)
        rows = by_id(body)
        assert body["tipo_cambio"] is None
        assert rows[300]["erp"] == money(2, 20.0, None)
        assert rows[301]["erp"] == money(3, None, 15000.0)


@pytest.fixture()
def board_mlas(monkeypatch) -> list[list[str]]:
    seen: list[list[str]] = []
    figures = {
        "MLA208": board_row("MLA208", d7=1, d30=2, gross=60.0, tg=6.0, costo=40.0),
        "MLA210": board_row("MLA210", d7=1, d30=1, gross=900000.0, tg=90000.0, costo=500000.0),
        "MLA200A": board_row("MLA200A", d7=0, d30=1, gross=1500.0, tg=150.0, costo=1000.0),
    }

    def fake(db, mlas, sell_in_out=False):
        seen.append(sorted(mlas))
        return {m: figures[m] for m in mlas if m in figures}

    monkeypatch.setattr(stock_audit, "metrics_by_mla", fake)
    return seen


@pytest.mark.postgres
class TestProbeSales:
    def test_hidden_kits_never_reach_the_board_and_a_pc_keeps_its_own_sales(
        self, client, auditor, db, rol_admin, board_mlas
    ) -> None:
        grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
        rows = by_id(audit(client, auditor))
        assert board_mlas == [["MLA200A", "MLA200B", "MLA202", "MLA208", "MLA210", "MLA231", "MLA300", "MLA301"]]
        assert rows[200]["ventas"]["unidades_30d"] == 1  # never the PC's sale
        assert rows[210]["ventas"]["unidades_30d"] == 1
        assert rows[207]["ventas"]["unidades_30d"] == 6  # 2 packs of 3, in base units
        assert rows[207]["ventas"]["facturado_30d"] == 60.0
        assert rows[207]["ventas"]["markup_30d"] == 15.0

    def test_without_metricas_there_are_no_sales_and_sales_sorts_are_forbidden(
        self, client, auditor, board_mlas
    ) -> None:
        body = audit(client, auditor)
        assert all(row["ventas"] is None for row in body["rows"])
        assert board_mlas == []
        assert client.get(URL, headers=auditor, params={"orden": "facturado_30d"}).status_code == 403

    def test_the_sorts_by_value_order_by_usd(self, client, auditor) -> None:
        ids = [row["product_item_id"] for row in audit(client, auditor, orden="valor_total")["rows"]]
        assert ids[:3] == [200, 210, 221]


def test_a_variant_full_value_uses_decimal_quantities() -> None:
    # a quantity read as Decimal never breaks the base-units product (pack x 2.0000)
    kinds = stock_audit.classify_combos({1: [(2, Decimal("2.0000"))]}, {2: (60, 1)}, {})
    assert kinds[1].cantidad == Decimal(2)
