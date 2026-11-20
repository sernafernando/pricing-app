"""auditoria-stock-niveles S1-S5: the Marca and Categoría levels of the Auditoría de stock, and the ERP / Full split
of its sales, coverage and rotation. Invented data only.

The world is `test_ml_publications_view_stock_audit.fill` (rate 1000 ARS per USD) with brands and categories:
* Lenovo / Notebooks: notebook 100 (ERP 5 x USD 1000, Full 2) and its variant 101 (Full 1 x USD 1100);
* Lenovo / PC: PC 130 (ERP 1 x ARS 300000);
* Logi / Perif: mouse 111 (ERP 100 x USD 2) and its pack 110 (3 packs of 10 at Full x USD 20);
* no brand / Cables: 140 (ERP 2 x USD 10).
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from app.services.ml_daily_metrics import board
from app.services.ml_publications.view import stock_audit
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import seed_rows
from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401
from tests.routers.test_ml_publications_view_stock_audit import (  # noqa: F401
    FIGURES,
    PERMISO,
    URL,
    audit,
    board_calls,
    fill,
    no_split,
    money,
    photo,
    sheet,
    started,
)
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401

LENOVO, LOGI, NONE = "LENOVO", "LOGI", "__none__"

GROUPS = {
    100: ("Lenovo", "Notebooks"),
    101: ("Lenovo", "Notebooks"),
    130: ("Lenovo", "PC"),
    110: ("Logi", "Perif"),
    111: ("Logi", "Perif"),
    140: (None, "Cables"),
}


def fill_groups(conn) -> None:
    fill(conn)
    for item, (marca, categoria) in GROUPS.items():
        conn.execute(
            text("UPDATE productos_erp SET marca = :m, categoria = :c WHERE item_id = :i"),
            {"m": marca, "c": categoria, "i": item},
        )


def fill_groups_with_photos(conn) -> None:
    fill_groups(conn)
    today = board.today_business()
    photo(conn, today, p100=(4, 1), p101=(0, 1), p111=(100, 0), p110=(0, 3), p140=(2, 0))
    photo(conn, today - timedelta(days=29), p100=(4, 2), p140=(2, 0))


@pytest.fixture()
def grouped(client, pg, db, rol_admin, admin_auth_headers, started, splits):
    seed_rows(pg, fill_groups)
    grant(db, rol_admin, PERMISO, "ml_metricas.ver")
    return admin_auth_headers


@pytest.fixture()
def grouped_photos(client, pg, db, rol_admin, admin_auth_headers, started, splits):
    seed_rows(pg, fill_groups_with_photos)
    grant(db, rol_admin, PERMISO, "ml_metricas.ver")
    return admin_auth_headers


# MLA10 (notebook): 1 of its 7d unit and 1 of its 30d units by Full; MLA12 (variant): its 30d unit by Full; MLA20
# (pack): 1 of its 2 30d packs by Full, and its 7d pack has no shipping data (ERP).
SPLITS = {
    "MLA10": board.ShippingSplit(full_7d=1, full_30d=1, erp_7d=0, erp_30d=1),
    "MLA12": board.ShippingSplit(full_7d=0, full_30d=1, erp_7d=0, erp_30d=0),
    "MLA20": board.ShippingSplit(full_7d=0, full_30d=1, erp_7d=1, erp_30d=1, unknown_7d=1, unknown_30d=1),
}


@pytest.fixture()
def splits(monkeypatch, board_calls) -> list[list[str]]:
    seen: list[list[str]] = []

    def fake(db, mlas):
        seen.append(sorted(mlas))
        return {mla: SPLITS[mla] for mla in mlas if mla in SPLITS}

    monkeypatch.setattr(stock_audit, "fulfillment_by_mla", fake)
    monkeypatch.setattr(
        stock_audit, "summed_sales", stock_audit.summed_from_rows
    )  # these Board rows, summed one by one
    return seen


def by_key(body: dict) -> dict[str, dict]:
    return {row["key"]: row for row in body["rows"]}


def summed(rows: list[dict], part: str) -> dict:
    """The parts' units and values added, the way a group adds its products (costed values only)."""
    usd = [r[part]["usd"] for r in rows if r[part]["usd"] is not None]
    ars = [r[part]["ars"] for r in rows if r[part]["ars"] is not None]
    return money(
        sum(r[part]["unidades"] for r in rows), round(sum(usd), 2) if usd else None, round(sum(ars), 2) if ars else None
    )


@pytest.mark.postgres
class TestLevels:
    def test_the_marca_level_lists_one_row_per_brand_of_the_base_products(self, client, grouped) -> None:
        body = audit(client, grouped, nivel="marca", orden="valor_total", dir="desc")

        assert [(r["key"], r["tipo"], r["descripcion"], r["productos"]) for r in body["rows"]] == [
            ("marca:LENOVO", "marca", "Lenovo", 2),
            ("marca:LOGI", "marca", "Logi", 1),
            ("marca:__none__", "marca", "Sin marca", 1),
        ]
        assert body["total"] == 3
        assert by_key(body)["marca:LENOVO"]["grupo"] == {"marca": LENOVO, "categoria": None}

    def test_a_brand_is_the_sum_of_its_products_without_counting_a_variant_twice(self, client, grouped) -> None:
        lenovo = by_key(audit(client, grouped, nivel="marca"))["marca:LENOVO"]
        products = audit(client, grouped, nivel="producto", grupo_marca=LENOVO)["rows"]

        assert sorted(r["product_item_id"] for r in products) == [100, 130]
        for part in ("erp", "full", "total"):
            assert lenovo[part] == summed(products, part)
        # notebook ERP 5 + PC 1; Full: the notebook's 2 + its variant's 1 (in base units), never the variant again
        assert lenovo["erp"] == money(6, 5300.0, 5_300_000.0)
        assert lenovo["full"] == money(3, 3100.0, 3_100_000.0)

    @pytest.mark.parametrize("nivel", ["marca", "categoria"])
    def test_every_group_is_the_exact_sum_of_its_visible_product_rows(self, client, grouped, nivel) -> None:
        # Owner 2026-11-18 (screenshot): a group's Full must never count a pack's or a variant's units twice.
        # Logi holds the pack 110 (Full only), Lenovo / Notebooks the variant 101 (Full only).
        groups = audit(client, grouped, nivel=nivel)["rows"]
        assert len(groups) >= 3
        for g in groups:
            drill = {
                k: v
                for k, v in (("grupo_marca", g["grupo"]["marca"]), ("grupo_categoria", g["grupo"]["categoria"]))
                if v
            }
            products = audit(client, grouped, nivel="producto", **drill)["rows"]
            assert g["productos"] == len(products), g["key"]
            for part in ("erp", "full", "total"):
                assert g[part] == summed(products, part), (g["key"], part)
        logi = by_key(audit(client, grouped, nivel="marca"))["marca:LOGI"]
        # mouse ERP 100; Full: 3 packs of 10 = 30 base units, once
        assert logi["full"]["unidades"] == 30 and logi["erp"]["unidades"] == 100

    @pytest.mark.parametrize("nivel", ["marca", "categoria", "producto"])
    def test_the_kpis_are_the_sum_of_the_top_level_rows(self, client, grouped, nivel) -> None:
        body = audit(client, grouped, nivel=nivel)
        assert body["total"] == len(body["rows"])
        for part in ("erp", "full", "total"):
            assert body["kpis"][part] == summed(body["rows"], part), part

    def test_a_brand_row_carries_its_categories_and_they_add_up_to_it(self, client, grouped) -> None:
        lenovo = by_key(audit(client, grouped, nivel="marca"))["marca:LENOVO"]

        categorias = {c["key"]: c for c in lenovo["categorias"]}
        assert set(categorias) == {"marca:LENOVO|categoria:NOTEBOOKS", "marca:LENOVO|categoria:PC"}
        assert categorias["marca:LENOVO|categoria:PC"]["grupo"] == {"marca": LENOVO, "categoria": "PC"}
        assert categorias["marca:LENOVO|categoria:PC"]["tipo"] == "categoria"
        for part in ("erp", "full", "total"):
            assert lenovo[part] == summed(list(categorias.values()), part)

    def test_the_categoria_level_groups_across_brands_and_drills_into_one(self, client, grouped) -> None:
        body = audit(client, grouped, nivel="categoria", orden="descripcion", dir="asc")
        assert [r["key"] for r in body["rows"]] == [
            "categoria:CABLES",
            "categoria:NOTEBOOKS",
            "categoria:PC",
            "categoria:PERIF",
        ]
        assert "categorias" not in body["rows"][0]

        drilled = audit(client, grouped, nivel="producto", grupo_categoria="NOTEBOOKS")
        assert [r["product_item_id"] for r in drilled["rows"]] == [100]
        assert drilled["kpis"]["productos"] == 1

    def test_a_drill_into_a_brand_narrows_the_categoria_level_and_the_kpis(self, client, grouped) -> None:
        body = audit(client, grouped, nivel="categoria", grupo_marca=LENOVO)
        assert sorted(r["key"] for r in body["rows"]) == [
            "marca:LENOVO|categoria:NOTEBOOKS",
            "marca:LENOVO|categoria:PC",
        ]
        assert body["kpis"]["productos"] == 2

    def test_a_category_inside_a_drilled_brand_keeps_the_brand_to_drill_further(self, client, grouped) -> None:
        # Opening a category of the drilled brand must stay inside that brand (GGA finding on the first push).
        body = audit(client, grouped, nivel="categoria", grupo_marca=LENOVO)
        assert {r["grupo"]["marca"] for r in body["rows"]} == {LENOVO}

    def test_a_drill_names_its_groups_as_the_rows_show_them(self, client, grouped) -> None:
        body = audit(client, grouped, nivel="producto", grupo_marca=LENOVO, grupo_categoria="NOTEBOOKS")
        assert body["grupo_nombres"] == {"marca": "Lenovo", "categoria": "Notebooks"}
        assert "grupo_nombres" not in audit(client, grouped, nivel="marca")

    def test_the_none_brand_is_its_own_group(self, client, grouped) -> None:
        drilled = audit(client, grouped, nivel="producto", grupo_marca=NONE)
        assert [r["product_item_id"] for r in drilled["rows"]] == [140]

    def test_without_nivel_the_rows_are_the_products_as_before(self, client, grouped) -> None:
        body = audit(client, grouped)
        assert {r["tipo"] for r in body["rows"]} == {"producto", "pc"}

    @pytest.mark.parametrize(
        "orden, direction, expected",
        [
            ("valor_total", "desc", ["marca:LENOVO", "marca:LOGI", "marca:__none__"]),
            ("valor_total", "asc", ["marca:__none__", "marca:LOGI", "marca:LENOVO"]),
            ("descripcion", "asc", ["marca:LENOVO", "marca:LOGI", "marca:__none__"]),
            ("unidades_erp", "desc", ["marca:LOGI", "marca:LENOVO", "marca:__none__"]),
        ],
    )
    def test_the_brands_sort_like_the_products(self, client, grouped, orden, direction, expected) -> None:
        body = audit(client, grouped, nivel="marca", orden=orden, dir=direction)
        assert [r["key"] for r in body["rows"]] == expected

    def test_the_brands_page(self, client, grouped) -> None:
        body = audit(client, grouped, nivel="marca", orden="valor_total", dir="desc", limit=1, offset=1)
        assert ([r["key"] for r in body["rows"]], body["total"]) == (["marca:LOGI"], 3)

    def test_a_filter_applies_to_every_level(self, client, grouped) -> None:
        body = audit(client, grouped, nivel="marca", marcas="Logi")
        assert [r["key"] for r in body["rows"]] == ["marca:LOGI"]

    def test_an_unknown_level_is_a_422(self, client, grouped) -> None:
        assert client.get(URL, headers=grouped, params={"nivel": "tienda"}).status_code == 422


@pytest.mark.postgres
class TestGroupWithoutCost:
    def test_a_brand_adds_its_costed_stock_and_counts_the_products_without_cost(
        self, client, pg, db, rol_admin, admin_auth_headers, started
    ) -> None:
        def world(conn) -> None:
            fill_groups(conn)
            conn.execute(text("UPDATE productos_erp SET costo = NULL WHERE item_id = 130"))

        seed_rows(pg, world)
        grant(db, rol_admin, PERMISO)
        lenovo = by_key(audit(client, admin_auth_headers, nivel="marca"))["marca:LENOVO"]

        assert lenovo["erp"] == money(6, 5000.0, 5_000_000.0)  # the PC's unit is in, its value is not
        assert (lenovo["productos_sin_costo"], lenovo["sin_costo"]) == (1, True)


def envio(ventas: dict) -> dict:
    return ventas["envio"]


def split(erp7: int, full7: int, sin7: int, erp30: int, full30: int, sin30: int) -> dict:
    return {
        "7d": {"erp": erp7, "full": full7, "sin_envio": sin7},
        "30d": {"erp": erp30, "full": full30, "sin_envio": sin30},
    }


@pytest.mark.postgres
class TestSalesSplit:
    def test_every_row_splits_its_sales_into_erp_and_full(self, client, grouped, splits) -> None:
        rows = {r["product_item_id"]: r for r in audit(client, grouped)["rows"]}

        # notebook: its own MLA10 (7d 1 by Full; 30d 2, 1 by Full) and its variant's MLA12 (30d 1 by Full)
        assert envio(rows[100]["ventas"]) == split(0, 1, 0, 1, 2, 0)
        assert envio(rows[100]["variantes"][0]["ventas"]) == split(0, 0, 0, 0, 1, 0)
        # mice, in base units: the pack's 7d pack (10 mice) has no shipping data, so it is ERP and said so
        assert envio(rows[111]["ventas"]) == split(10, 0, 10, 10, 10, 10)
        # 140 never sold
        assert envio(rows[140]["ventas"]) == split(0, 0, 0, 0, 0, 0)

    def test_erp_plus_full_is_the_total_on_every_row_and_level(self, client, grouped, splits) -> None:
        rows = []
        for nivel in ("producto", "categoria", "marca"):
            for row in audit(client, grouped, nivel=nivel)["rows"]:
                rows += [row, *row.get("variantes", []), *row.get("categorias", [])]
        for row in rows:
            ventas = row["ventas"]
            for window in ("7d", "30d"):
                part = ventas["envio"][window]
                assert part["erp"] + part["full"] == ventas[f"unidades_{window}"], (row["key"], window)
                assert part["sin_envio"] <= part["erp"]

    def test_a_brand_adds_its_products_splits(self, client, grouped, splits) -> None:
        lenovo = by_key(audit(client, grouped, nivel="marca"))["marca:LENOVO"]
        logi = by_key(audit(client, grouped, nivel="marca"))["marca:LOGI"]

        assert (lenovo["ventas"]["unidades_7d"], lenovo["ventas"]["unidades_30d"]) == (1, 3)
        assert envio(lenovo["ventas"]) == split(0, 1, 0, 1, 2, 0)
        assert envio(logi["ventas"]) == split(10, 0, 10, 10, 10, 10)

    def test_a_publication_without_a_split_is_all_erp(self, client, grouped, monkeypatch, board_calls) -> None:
        monkeypatch.setattr(stock_audit, "fulfillment_by_mla", lambda db, mlas: {})
        monkeypatch.setattr(
            stock_audit, "summed_sales", stock_audit.summed_from_rows
        )  # these Board rows, summed one by one
        rows = {r["product_item_id"]: r for r in audit(client, grouped)["rows"]}
        assert envio(rows[100]["ventas"]) == split(1, 0, 0, 3, 0, 0)

    def test_the_split_is_read_once_for_all_the_rows(self, client, grouped, splits) -> None:
        audit(client, grouped, nivel="marca")
        assert splits == [["MLA10", "MLA11", "MLA12", "MLA20", "MLA40"]]

    def test_without_metricas_there_are_no_sales_at_any_level(
        self, client, pg, db, rol_admin, admin_auth_headers, started
    ) -> None:
        seed_rows(pg, fill_groups)
        grant(db, rol_admin, PERMISO)
        body = audit(client, admin_auth_headers, nivel="marca")
        assert {r["ventas"] is None for r in body["rows"]} == {True}


def origen(ventas: dict) -> tuple:
    out = ventas["por_origen"]
    return tuple((out[s]["dias_cobertura"], out[s]["cobertura_infinita"], out[s]["rotacion"]) for s in ("erp", "full"))


@pytest.mark.postgres
class TestCoverageAndRotationBySource:
    def test_each_source_is_its_stock_over_its_own_sales(self, client, grouped_photos, splits) -> None:
        rows = {r["product_item_id"]: r for r in audit(client, grouped_photos)["rows"]}
        # notebook: ERP 5 over 1 ERP unit in 30d -> 150 days; average ERP (4 + 4) / 2 = 4 -> 0.25 times.
        # Full 3 (its 2 + the variant's 1) over 2 Full units -> 45 days; average Full (1 + 2) / 2 + the
        # variant's (1 + 0) / 2 = 2 -> 1.0 times.
        assert origen(rows[100]["ventas"]) == ((150.0, False, 0.25), (45.0, False, 1.0))
        # the variant's ERP stock is its base's: nothing of its own; its Full 1 over 1 unit, average 0.5
        assert origen(rows[100]["variantes"][0]["ventas"]) == ((None, False, None), (30.0, False, 2.0))

    def test_stock_without_sales_lasts_forever_per_source(self, client, grouped_photos, splits) -> None:
        rows = {r["product_item_id"]: r for r in audit(client, grouped_photos)["rows"]}
        # 140: ERP 2, never sold -> infinite, rotation 0; no Full at all -> no figure
        assert origen(rows[140]["ventas"]) == ((None, True, 0.0), (None, False, None))

    def test_erp_sales_without_erp_stock_are_out_of_stock_not_unknown(
        self, client, grouped_photos, splits, monkeypatch
    ) -> None:
        # PR #2345 review: the variant sold by ERP and holds no ERP stock of its own -> ERP coverage 0 days (out of
        # stock, the signal that matters), and its rotation sold / 0 has no number: infinite, never "—"
        monkeypatch.setitem(SPLITS, "MLA12", board.ShippingSplit(full_7d=0, full_30d=0, erp_7d=0, erp_30d=1))
        variant = {r["product_item_id"]: r for r in audit(client, grouped_photos)["rows"]}[100]["variantes"][0]
        erp = variant["ventas"]["por_origen"]["erp"]
        assert (erp["dias_cobertura"], erp["cobertura_infinita"]) == (0.0, False)
        assert (erp["rotacion"], erp["rotacion_infinita"]) == (None, True)

    def test_no_erp_sales_and_no_erp_stock_is_the_only_unknown(self, client, grouped_photos, splits) -> None:
        # the variant sold only by Full: nothing to say about ERP
        variant = {r["product_item_id"]: r for r in audit(client, grouped_photos)["rows"]}[100]["variantes"][0]
        erp = variant["ventas"]["por_origen"]["erp"]
        assert (erp["dias_cobertura"], erp["cobertura_infinita"], erp["rotacion"], erp["rotacion_infinita"]) == (
            None,
            False,
            None,
            False,
        )

    def test_two_products_with_different_stock_and_sales_get_different_splits(
        self, client, grouped_photos, splits
    ) -> None:
        # PR #2345 review: the screenshot showed the same ERP / Full figures on every row. The backend computes them
        # per row: the notebook (ERP 5, Full 3, sold 1 ERP + 2 Full) and the mice (ERP stock, sold only by ERP)
        rows = {r["product_item_id"]: r for r in audit(client, grouped_photos)["rows"]}
        assert origen(rows[100]["ventas"]) != origen(rows[111]["ventas"])
        assert origen(rows[100]["ventas"]) != origen(rows[140]["ventas"])

    def test_the_total_coverage_is_the_sales_weighted_mix_of_erp_and_full(self, client, grouped_photos, splits) -> None:
        # total days = 30 x (ERP stock + Full stock) / (ERP sold + Full sold), and each source's stock is
        # its days x its sold / 30: so the total is the sources' days weighted by their sales (rounding aside)
        checked = 0
        for nivel in ("producto", "marca"):
            for row in audit(client, grouped_photos, nivel=nivel)["rows"]:
                ventas = row["ventas"]
                erp, full = ventas["por_origen"]["erp"], ventas["por_origen"]["full"]
                sold = ventas["envio"]["30d"]
                if ventas["dias_cobertura"] is None or None in (erp["dias_cobertura"], full["dias_cobertura"]):
                    continue
                mixed = (erp["dias_cobertura"] * sold["erp"] + full["dias_cobertura"] * sold["full"]) / (
                    sold["erp"] + sold["full"]
                )
                assert abs(mixed - ventas["dias_cobertura"]) <= 0.1, row["key"]
                checked += 1
        assert checked >= 2  # the notebook and its brand

    def test_a_brand_computes_them_on_its_totals_never_an_average(self, client, grouped_photos, splits) -> None:
        lenovo = by_key(audit(client, grouped_photos, nivel="marca"))["marca:LENOVO"]
        # ERP 6 (5 + the PC's 1) over 1 ERP unit -> 180 days; average ERP 4 + 0 -> 0.25. Full as the notebook's.
        assert origen(lenovo["ventas"]) == ((180.0, False, 0.25), (45.0, False, 1.0))
        # the totals too: stock 9 over 3 units -> 90 days; 3 over the average 6 -> 0.5
        assert (lenovo["ventas"]["dias_cobertura"], lenovo["ventas"]["rotacion"]) == (90.0, 0.5)


@pytest.mark.postgres
class TestExportLevels:
    def test_the_export_has_the_erp_and_full_columns(self, client, grouped, splits) -> None:
        rows = {r["Código"]: r for r in sheet(client, grouped)}
        row = rows["C100"]
        assert (row["Ventas 7D ERP"], row["Ventas 7D Full"], row["Ventas 30D ERP"], row["Ventas 30D Full"]) == (
            0,
            1,
            1,
            2,
        )
        # the pack's line in base units, as the view shows it
        assert (rows["C110"]["Ventas 30D ERP"], rows["C110"]["Ventas 30D Full"]) == (10, 10)

    def test_the_marca_export_lists_each_brand_then_its_categories_then_their_products(
        self, client, grouped, splits
    ) -> None:
        lines = sheet(client, grouped, nivel="marca", orden="valor_total", dir="desc")
        shown = [(line["Tipo"], line["Producto"]) for line in lines]
        assert shown[:6] == [
            ("Marca", "Lenovo"),
            ("Categoría", "Notebooks"),
            ("Producto", "Producto 100"),
            ("Variante", "Producto 101"),
            ("Categoría", "PC"),
            ("PC", "Producto 130"),
        ]
        lenovo = lines[0]
        assert (lenovo["Stock ERP"], lenovo["Valor ERP USD"], lenovo["Ventas 30D Full"]) == (6, 5300.0, 2)
