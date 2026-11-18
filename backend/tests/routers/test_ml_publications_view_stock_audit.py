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

import importlib.util
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from app.routers import ml_publications_view
from app.services.ml_daily_metrics import board
from app.services.ml_publications.view import stock_audit
from app.services.ml_publications.view.markup import PublicationMarkup
from app.services.ml_publications.view.markup_service import ItemMarkup
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


def publication(conn, mla: str, product_id: int, up: str, status: str = "active", kind: str = "gold_special") -> None:
    seed.add_item(conn, mla, status=status, user_product_id=up, listing_type_id=kind)
    seed.add_link(conn, mla, product_id)


SNAPSHOT_MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20261122_producto_stock_diario.py"


def create_snapshot_table(conn) -> None:
    """The daily stock photo's table, from its real migration."""
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    spec = importlib.util.spec_from_file_location(SNAPSHOT_MIGRATION.stem, SNAPSHOT_MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(conn)):
        module.upgrade()


def fill(conn) -> None:
    seed.create_presence_tables(conn)
    create_snapshot_table(conn)
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
    publication(conn, "MLA11", 100, "UP10", kind="gold_pro")
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

    # --- promos-fila S2: how many of a node's publications have an applied promotion and how many do not --------

    def test_each_row_and_variant_counts_its_publications_with_and_without_promo(self, client, auditor) -> None:
        rows = {row["product_item_id"]: row for row in audit(client, auditor)["rows"]}
        # the notebook adds its own MLA10, MLA11 and its variant's MLA12 (the only started one)
        assert rows[100]["promo_counts"] == {"con": 1, "sin": 2}
        assert rows[100]["variantes"][0]["promo_counts"] == {"con": 1, "sin": 0}
        assert rows[130]["promo_counts"] == {"con": 0, "sin": 1}  # a PC, its paused MLA40
        assert rows[111]["promo_counts"] == {"con": 0, "sin": 1}  # through its pack's MLA20
        assert rows[111]["variantes"][0]["promo_counts"] == {"con": 0, "sin": 1}
        assert rows[140]["promo_counts"] == {"con": 0, "sin": 0}  # no publication

    def test_without_the_promotions_database_the_promo_counts_are_null(self, client, auditor, monkeypatch) -> None:
        def down(*args, **kwargs):
            raise RuntimeError("ML_WEBHOOK_DB_URL not set")

        monkeypatch.setattr(ml_publications_view, "fetch_mlas_with_started", down)
        rows = audit(client, auditor)["rows"]
        assert all(row["promo_counts"] is None for row in rows)
        assert all(v["promo_counts"] is None for row in rows for v in row["variantes"])

    @pytest.mark.parametrize("dir, expected", [("desc", [100, 111, 130, 140]), ("asc", [111, 130, 140, 100])])
    def test_it_sorts_by_the_publications_with_an_applied_promotion(self, client, auditor, dir, expected) -> None:
        body = audit(client, auditor, orden="promos_aplicadas", dir=dir)
        assert [row["product_item_id"] for row in body["rows"]] == expected

    def test_the_promo_sort_without_the_promotions_database_keeps_the_product_order(
        self, client, auditor, monkeypatch
    ) -> None:
        def down(*args, **kwargs):
            raise RuntimeError("ML_WEBHOOK_DB_URL not set")

        monkeypatch.setattr(ml_publications_view, "fetch_mlas_with_started", down)
        body = audit(client, auditor, orden="promos_aplicadas", dir="desc")
        assert [row["product_item_id"] for row in body["rows"]] == [100, 111, 130, 140]


# --- S10 (L3): sales by period, Total Gauss and markup with sell in / sell out, summed on the base rows -------------


def board_row(mla: str, *, d7: int, d30: int, gross: float, tg: float, costo: float, **sell) -> board.Row:
    """A Board publication row (30 business days) with its figures; `sell` = the sell in / out fields."""
    return board.Row(
        key=mla,
        product_item_id=0,
        mla=mla,
        units=d30,
        windows={"3d": 0, "7d": d7, "15d": 0, "30d": d30},
        gross=Decimal(str(gross)),
        tg=Decimal(str(tg)),
        mtg=Decimal(str(tg)),
        costo=Decimal(str(costo)),
        **{name: (Decimal(str(v)) if isinstance(v, float) else v) for name, v in sell.items()},
    )


FIGURES = {
    # the notebook's own sales: a sell in of 50 on the cost
    "MLA10": board_row(
        "MLA10",
        d7=1,
        d30=2,
        gross=2000.0,
        tg=200.0,
        costo=1000.0,
        sell_in=50.0,
        sell_out=0.0,
        m_sell_in=50.0,
        m_sell_out=0.0,
        sell_in_lineas=1,
        sell_out_lineas=0,
    ),
    # variant 101: a sell out of 30
    "MLA12": board_row(
        "MLA12",
        d7=0,
        d30=1,
        gross=1500.0,
        tg=100.0,
        costo=1000.0,
        sell_in=0.0,
        sell_out=30.0,
        m_sell_in=0.0,
        m_sell_out=30.0,
        sell_in_lineas=0,
        sell_out_lineas=1,
    ),
    # pack 110: 2 packs of 10 mice, no sell in / out
    "MLA20": board_row(
        "MLA20",
        d7=1,
        d30=2,
        gross=100.0,
        tg=10.0,
        costo=40.0,
        sell_in=0.0,
        sell_out=0.0,
        m_sell_in=0.0,
        m_sell_out=0.0,
        sell_in_lineas=0,
        sell_out_lineas=0,
    ),
}


@pytest.fixture()
def board_calls(monkeypatch) -> list[tuple]:
    seen: list[tuple] = []

    def fake(db, mlas, sell_in_out=False):
        seen.append((sorted(mlas), sell_in_out))
        return {mla: FIGURES[mla] for mla in mlas if mla in FIGURES}

    monkeypatch.setattr(stock_audit, "metrics_by_mla", fake)
    return seen


def sales(unidades_7d: int, unidades_30d: int, facturado: float, **margin) -> dict:
    # these Board rows carry no daily series: the trends are empty (the Rotación columns are compared apart)
    trends = {"series_units_90d": [], **({"series_markup_90d": []} if margin else {})}
    return {"unidades_7d": unidades_7d, "unidades_30d": unidades_30d, "facturado_30d": facturado, **trends, **margin}


ROTATION_KEYS = (
    "ultima_venta",
    "ultima_venta_dias",
    "ageing_dias",
    "dias_cobertura",
    "cobertura_infinita",
    "rotacion",
    "stock_promedio",
    "stock_promedio_dias",
)


def plain(ventas: dict) -> dict:
    """A row's sales without the Rotación columns (`sales` builds the rest)."""
    return {key: value for key, value in ventas.items() if key not in ROTATION_KEYS}


@pytest.mark.postgres
class TestStockAuditSales:
    def test_with_ganancia_the_board_reads_sell_in_out_once_for_every_row(
        self, client, auditor, db, rol_admin, board_calls
    ) -> None:
        grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
        body = audit(client, auditor)
        assert (body["can_see_sales"], body["can_see_margin"]) == (True, True)
        assert board_calls == [(["MLA10", "MLA11", "MLA12", "MLA20", "MLA40"], True)]

    def test_a_base_row_sums_its_variants_in_base_units_and_weights_the_markup(
        self, client, auditor, db, rol_admin, board_calls
    ) -> None:
        grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
        rows = {row["product_item_id"]: row for row in audit(client, auditor)["rows"]}
        notebook = rows[100]
        # own 2 + variant 1; Total Gauss 300 over cost 2000 = 15 %; with sell in / out: (300 + 50 + 30) / (2000 - 50)
        assert plain(notebook["ventas"]) == sales(
            1, 3, 3500.0, total_gauss_30d=300.0, markup_30d=15.0, total_gauss_sell_30d=380.0, markup_sell_30d=19.5
        )
        assert plain(notebook["variantes"][0]["ventas"]) == sales(
            0, 1, 1500.0, total_gauss_30d=100.0, markup_30d=10.0, total_gauss_sell_30d=130.0, markup_sell_30d=13.0
        )
        mouse = rows[111]
        # 2 packs of 10 = 20 mice; no sell in / out: those figures do not apply (empty, never a copy)
        assert plain(mouse["ventas"]) == sales(
            10, 20, 100.0, total_gauss_30d=10.0, markup_30d=25.0, total_gauss_sell_30d=None, markup_sell_30d=None
        )
        assert mouse["variantes"][0]["ventas"]["unidades_30d"] == 2  # the pack's own units
        # no sale at all: zero units, no profit figure
        assert plain(rows[140]["ventas"]) == sales(
            0, 0, 0.0, total_gauss_30d=None, markup_30d=None, total_gauss_sell_30d=None, markup_sell_30d=None
        )

    def test_without_ganancia_there_is_no_profit_nor_markup_and_no_sell_in_out(
        self, client, auditor, db, rol_admin, board_calls
    ) -> None:
        grant(db, rol_admin, "ml_metricas.ver")
        body = audit(client, auditor)
        assert (body["can_see_sales"], body["can_see_margin"]) == (True, False)
        assert board_calls[0][1] is False
        assert plain(body["rows"][0]["ventas"]) == sales(1, 3, 3500.0)

    def test_without_metricas_there_are_no_sales_and_no_board(self, client, auditor, board_calls) -> None:
        body = audit(client, auditor)
        assert (body["can_see_sales"], body["can_see_margin"]) == (False, False)
        assert board_calls == []
        assert all(row["ventas"] is None for row in body["rows"])


# --- The approved mock (L6): trends, current markup, Tipo / Estado, the no-active-publication value, sorting -------


SERIES = {
    # three days are enough: the series are summed day by day, whatever their length
    "MLA10": ([1, 0, 1], [10.0, None, 20.0]),
    "MLA11": ([3, 0, 0], [30.0, None, None]),
    "MLA12": ([0, 1, 0], [None, 30.0, None]),
    "MLA20": ([2, 0, 0], [25.0, None, None]),
}


@pytest.fixture()
def series_board(monkeypatch) -> None:
    figures = {
        mla: replace(
            FIGURES.get(mla) or board_row(mla, d7=0, d30=0, gross=0.0, tg=0.0, costo=0.0),
            series_units=u,
            series_markup=m,
        )
        for mla, (u, m) in SERIES.items()
    }
    monkeypatch.setattr(
        stock_audit, "metrics_by_mla", lambda db, mlas, sell_in_out=False: {m: figures[m] for m in mlas if m in figures}
    )


def unit_markup(low: float, high: float) -> ItemMarkup:
    return ItemMarkup(PublicationMarkup((), low, high, low, low < 0, 0, ""))


@pytest.fixture()
def list_markups(monkeypatch) -> list[list[str]]:
    seen: list[list[str]] = []
    found = {"MLA10": unit_markup(18.0, 18.0), "MLA11": unit_markup(16.0, 19.0), "MLA12": unit_markup(22.0, 22.0)}
    found["MLA20"] = unit_markup(30.0, 30.0)

    def fake(db, pricing_db, mlas):
        seen.append(sorted(mlas))
        return {mla: found[mla] for mla in mlas if mla in found}

    monkeypatch.setattr(stock_audit, "publication_markups", fake)
    return seen


@pytest.mark.postgres
class TestStockAuditMock:
    def test_the_trends_sum_units_in_base_units_and_weigh_each_days_markup_by_its_units(
        self, client, auditor, db, rol_admin, series_board, list_markups
    ) -> None:
        grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
        rows = {row["product_item_id"]: row for row in audit(client, auditor)["rows"]}
        notebook = rows[100]["ventas"]
        assert notebook["series_units_90d"] == [4, 1, 1]
        # day 1: (10 x 1 + 30 x 3) / 4 units; a day with no figure stays empty
        assert notebook["series_markup_90d"] == [25.0, 30.0, 20.0]
        assert rows[100]["variantes"][0]["ventas"]["series_units_90d"] == [0, 1, 0]
        assert rows[111]["ventas"]["series_units_90d"] == [20, 0, 0]  # 2 packs of 10
        assert rows[111]["variantes"][0]["ventas"]["series_units_90d"] == [2, 0, 0]
        assert rows[140]["ventas"]["series_units_90d"] == []  # no Board row: no series

    def test_without_ganancia_the_trend_has_units_only(self, client, auditor, db, rol_admin, series_board) -> None:
        grant(db, rol_admin, "ml_metricas.ver")
        notebook = audit(client, auditor)["rows"][0]["ventas"]
        assert notebook["series_units_90d"] == [4, 1, 1]
        assert "series_markup_90d" not in notebook

    def test_the_current_markup_is_the_range_of_the_rows_publications(
        self, client, auditor, db, rol_admin, board_calls, list_markups
    ) -> None:
        grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
        rows = {row["product_item_id"]: row for row in audit(client, auditor)["rows"]}
        assert list_markups == [["MLA10", "MLA11", "MLA12", "MLA20", "MLA40"]]
        assert rows[100]["markup_actual"] == {"min": 16.0, "max": 22.0}  # its own and its variant's, no average
        assert rows[100]["variantes"][0]["markup_actual"] == {"min": 22.0, "max": 22.0}
        assert rows[111]["markup_actual"] == {"min": 30.0, "max": 30.0}
        assert rows[130]["markup_actual"] is None and rows[140]["markup_actual"] is None

    def test_without_ganancia_there_is_no_current_markup(self, client, auditor, db, rol_admin, list_markups) -> None:
        grant(db, rol_admin, "ml_metricas.ver")
        body = audit(client, auditor)
        assert list_markups == []
        assert all("markup_actual" not in row for row in body["rows"])

    def test_tipo_and_estado_count_every_publication_of_the_row(self, client, auditor) -> None:
        rows = {row["product_item_id"]: row for row in audit(client, auditor)["rows"]}
        notebook = rows[100]
        assert (notebook["kind_counts"], notebook["status_counts"]) == ({"clasica": 2, "cuotas_6": 1}, {"active": 3})
        variant = notebook["variantes"][0]
        assert (variant["kind_counts"], variant["status_counts"]) == ({"clasica": 1}, {"active": 1})
        assert rows[130]["status_counts"] == {"paused": 1}
        assert (rows[140]["kind_counts"], rows[140]["status_counts"]) == ({}, {})

    def test_the_kpi_of_products_without_an_active_publication_carries_their_value(self, client, auditor) -> None:
        kpis = audit(client, auditor)["kpis"]
        # the paused PC (1 x ARS 300000) and 140 (2 x USD 10)
        assert kpis["valor_sin_publicacion_activa"] == money(3, 320.0, 320_000.0)

    @pytest.mark.parametrize(
        "orden, expected",
        [
            ("unidades_30d", [111, 100, 130, 140]),
            ("facturado_30d", [100, 111, 130, 140]),
            ("unidades_full", [111, 100, 130, 140]),
        ],
    )
    def test_it_sorts_by_the_sales_and_stock_columns(
        self, client, auditor, db, rol_admin, board_calls, orden, expected
    ) -> None:
        grant(db, rol_admin, "ml_metricas.ver")
        body = audit(client, auditor, orden=orden, dir="desc")
        assert [row["product_item_id"] for row in body["rows"]] == expected

    def test_a_margin_sort_reads_the_shown_figure_and_leaves_the_empty_ones_last(
        self, client, auditor, db, rol_admin, board_calls, list_markups
    ) -> None:
        grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
        # the notebook's markup with sell in / out 19.5; the mouse has none, so its plain 25.0 is the one shown
        asc = audit(client, auditor, orden="markup_30d", dir="asc")
        assert [row["product_item_id"] for row in asc["rows"]] == [100, 111, 130, 140]
        current = audit(client, auditor, orden="markup", dir="desc")
        assert [row["product_item_id"] for row in current["rows"]] == [111, 100, 130, 140]

    @pytest.mark.parametrize(
        "permisos, orden",
        [((), "unidades_7d"), (("ml_metricas.ver",), "total_gauss_30d"), (("ml_metricas.ver",), "markup")],
    )
    def test_a_sort_by_figures_the_caller_cannot_see_is_a_403(
        self, client, auditor, db, rol_admin, permisos, orden
    ) -> None:
        if permisos:
            grant(db, rol_admin, *permisos)
        response = client.get(URL, headers=auditor, params={"orden": orden})
        assert response.status_code == 403


def fill_without_cost(conn, *, rate: bool = True) -> None:
    """The world above, plus 160 (no cost, ERP 4) and notebook 170 (USD 100, ERP 2) whose variant 171 = 170 + RAM 102
    has no cost and Full 1 through MLA70; `rate=False` drops the BNA rate."""
    fill(conn)
    if not rate:
        conn.execute(text("DELETE FROM tipo_cambio"))
    product(conn, 160, 1, "USD", 4, 60)
    seed.add_cost(conn, 160, None, moneda_costo="USD")
    product(conn, 170, 100, "USD", 2, 46, 3819)
    product(conn, 171, 1, "USD", 0, 46, 3819)
    seed.add_cost(conn, 171, None, moneda_costo="USD")
    combo(conn, 171, (170, 1), (102, 1))
    publication(conn, "MLA70", 171, "UP70")
    seed.add_stock(conn, "UP70", full=1, own=0)


@pytest.fixture()
def auditor_without_cost(client, pg, db, rol_admin, admin_auth_headers, started):
    seed_rows(pg, fill_without_cost)
    grant(db, rol_admin, PERMISO)
    return admin_auth_headers


@pytest.fixture()
def auditor_without_rate(client, pg, db, rol_admin, admin_auth_headers, started):
    seed_rows(pg, lambda conn: fill_without_cost(conn, rate=False))
    grant(db, rol_admin, PERMISO)
    return admin_auth_headers


@pytest.mark.postgres
class TestStockWithoutCost:
    """L9: a stocked part without cost is never valued as 0 nor hidden in a partial sum: its value is unknown, its row
    says `sin_costo`, the KPI totals add only the parts with a cost and count the products left out."""

    def rows(self, client, headers) -> dict[int, dict]:
        return {row["product_item_id"]: row for row in audit(client, headers)["rows"]}

    def test_a_product_without_cost_has_unknown_values_and_is_flagged(self, client, auditor_without_cost) -> None:
        row = self.rows(client, auditor_without_cost)[160]
        assert (row["erp"], row["total"]) == (money(4, None, None), money(4, None, None))
        assert row["sin_costo"] is True

    def test_a_variant_without_cost_leaves_its_base_full_unknown_not_partial(
        self, client, auditor_without_cost
    ) -> None:
        row = self.rows(client, auditor_without_cost)[170]
        assert row["erp"] == money(2, 200.0, 200_000.0)
        assert row["full"] == money(1, None, None)
        assert row["total"] == money(3, None, None)
        assert row["sin_costo"] is True
        [variant] = row["variantes"]
        assert (variant["full"], variant["sin_costo"]) == (money(1, None, None), True)

    def test_rows_with_every_cost_are_not_flagged(self, client, auditor_without_cost) -> None:
        rows = self.rows(client, auditor_without_cost)
        assert rows[100]["sin_costo"] is False
        assert all(v["sin_costo"] is False for v in rows[100]["variantes"])

    def test_the_kpis_add_only_the_parts_with_a_cost_and_count_the_rest(self, client, auditor_without_cost) -> None:
        kpis = audit(client, auditor_without_cost)["kpis"]
        # The world's 5520 / 3160 plus notebook 170's ERP 200; 160's ERP and 171's Full count as units only.
        assert kpis["erp"] == money(114, 5720.0, 5_720_000.0)
        assert kpis["full"] == money(34, 3160.0, 3_160_000.0)
        assert kpis["total"] == money(148, 8880.0, 8_880_000.0)
        assert kpis["productos_sin_costo"] == 2

    def test_without_cost_problems_the_count_is_zero(self, client, auditor) -> None:
        assert audit(client, auditor)["kpis"]["productos_sin_costo"] == 0

    def test_without_the_bna_rate_the_other_currency_is_unknown_never_partial(
        self, client, auditor_without_rate
    ) -> None:
        body = audit(client, auditor_without_rate)
        rows = {row["product_item_id"]: row for row in body["rows"]}
        assert rows[100]["erp"] == money(5, 5000.0, None)
        assert rows[130]["erp"] == money(1, None, 300_000.0)
        assert rows[100]["sin_costo"] is False
        kpis = body["kpis"]
        assert (kpis["erp"]["usd"], kpis["erp"]["ars"]) == (None, None)  # USD and ARS costs mixed, no rate
        assert kpis["total"]["unidades"] == 148


# --- L7: Exportar a Excel ----------------------------------------------------------------------------------------

EXPORT_URL = "/api/ml-publications/view/stock-audit/export"


def sheet(client, headers, **params) -> list[dict]:
    """The export's rows, each as {header: value}."""
    from io import BytesIO

    from openpyxl import load_workbook

    response = client.get(EXPORT_URL, headers=headers, params=params)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert 'filename="publicaciones-ml-auditoria-stock-' in response.headers["content-disposition"]
    rows = list(load_workbook(BytesIO(response.content)).active.iter_rows(values_only=True))
    return [dict(zip(rows[0], row)) for row in rows[1:]]


@pytest.mark.postgres
class TestStockAuditExport:
    def test_without_the_permission_it_is_a_403(self, client, pg, db, rol_admin, admin_auth_headers) -> None:
        grant(db, rol_admin, "ml_ops.ver", "productos.ver")
        response = client.get(EXPORT_URL, headers=admin_auth_headers)
        assert response.status_code == 403
        assert PERMISO in response.json()["error"]["message"]

    def test_every_base_row_then_its_variants_in_the_view_order_whatever_the_page(self, client, auditor) -> None:
        rows = sheet(client, auditor, limit=1)
        assert [(r["Tipo"], r["Código"]) for r in rows] == [
            ("Producto", "C100"),
            ("Variante", "C101"),
            ("PC", "C130"),
            ("Producto", "C111"),
            ("Pack", "C110"),
            ("Producto", "C140"),
        ]
        assert rows[1]["Producto base"] == "C100"

    def test_stock_units_and_values_as_the_view_shows_them(self, client, auditor) -> None:
        rows = {r["Código"]: r for r in sheet(client, auditor)}
        notebook = rows["C100"]
        assert (notebook["Stock ERP"], notebook["Stock Full"], notebook["Stock total"]) == (5, 3, 8)
        assert (notebook["Valor ERP USD"], notebook["Valor ERP ARS"]) == (5000.0, 5_000_000.0)
        assert (notebook["Valor total USD"], notebook["Valor total ARS"]) == (8100.0, 8_100_000.0)
        pack = rows["C110"]
        assert (pack["Cantidad"], pack["Stock ERP"], pack["Stock Full"], pack["Valor Full USD"]) == (10, None, 30, 60.0)

    def test_the_order_follows_orden_and_dir(self, client, auditor) -> None:
        rows = sheet(client, auditor, orden="descripcion", dir="asc")
        assert [r["Código"] for r in rows if r["Tipo"] != "Variante" and r["Tipo"] != "Pack"] == [
            "C100",
            "C111",
            "C130",
            "C140",
        ]

    def test_without_metricas_there_are_no_sales_columns(self, client, auditor) -> None:
        headers = set(sheet(client, auditor)[0])
        assert not headers & {"Ventas 7D", "Ventas 30D", "Facturado 30D", "Total Gauss 30D", "Markup real 30D"}

    def test_with_metricas_the_sales_without_ganancia_no_profit(
        self, client, auditor, db, rol_admin, board_calls
    ) -> None:
        grant(db, rol_admin, "ml_metricas.ver")
        rows = {r["Código"]: r for r in sheet(client, auditor)}
        assert (rows["C100"]["Ventas 7D"], rows["C100"]["Ventas 30D"], rows["C100"]["Facturado 30D"]) == (1, 3, 3500.0)
        assert rows["C110"]["Ventas 30D"] == 20  # the pack's 2 sales in base units, as the view shows them
        assert not set(rows["C100"]) & {"Total Gauss 30D", "Markup real 30D", "Markup actual mín"}

    def test_with_ganancia_the_profit_and_markups(self, client, auditor, db, rol_admin, board_calls) -> None:
        grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
        notebook = {r["Código"]: r for r in sheet(client, auditor)}["C100"]
        # the sell in / out figures where they apply, as the view's Real 30D and Total Gauss
        assert (notebook["Total Gauss 30D"], notebook["Markup real 30D"]) == (380.0, 19.5)

    def test_a_product_without_cost_exports_blank_values_and_says_so(self, client, auditor_without_cost) -> None:
        row = {r["Código"]: r for r in sheet(client, auditor_without_cost)}["C160"]
        assert (row["Valor ERP USD"], row["Valor total ARS"], row["Sin costo"]) == (None, None, "Sí")

    def test_an_unknown_order_is_a_422(self, client, auditor) -> None:
        assert client.get(EXPORT_URL, headers=auditor, params={"orden": "precio"}).status_code == 422


# --- Rotación (rotacion S2): Última venta and Ageing, the Board's own figures per publication, aggregated per row -----


def sold(at: str, ageing: int) -> dict:
    return {"last_sale_at": datetime.fromisoformat(at).replace(tzinfo=timezone.utc), "ageing_days": ageing}


# MLA10 last sold on the 10th (8 days), MLA11 never (published 70 days ago), variant MLA12 on the 15th (3 days),
# the pack MLA20 never (published 40 days ago); MLA40 (the PC) has no Board row.
LAST_SALES = {
    "MLA10": sold("2026-11-10T15:00:00", 8),
    "MLA11": {"last_sale_at": None, "ageing_days": 70},
    "MLA12": sold("2026-11-15T12:30:00", 3),
    "MLA20": {"last_sale_at": None, "ageing_days": 40},
}


@pytest.fixture()
def last_sales_board(monkeypatch) -> None:
    figures = {
        mla: replace(FIGURES.get(mla) or board_row(mla, d7=0, d30=0, gross=0.0, tg=0.0, costo=0.0), **fields)
        for mla, fields in LAST_SALES.items()
    }
    monkeypatch.setattr(
        stock_audit, "metrics_by_mla", lambda db, mlas, sell_in_out=False: {m: figures[m] for m in mlas if m in figures}
    )


class TestLastSaleAndAgeingAggregation:
    """A row's last sale is its publications' latest; its ageing the Board's own rule over them (days since that last
    sale, or since its oldest publication started when none ever sold), never an average."""

    def test_with_a_sale_the_ageing_counts_from_the_latest_sale(self) -> None:
        figures = stock_audit.Sales()
        for mla in ("MLA10", "MLA11", "MLA12"):
            figures.add(replace(board_row(mla, d7=0, d30=0, gross=0.0, tg=0.0, costo=0.0), **LAST_SALES[mla]))
        out = figures.out(with_margin=False)
        assert out["ultima_venta"] == LAST_SALES["MLA12"]["last_sale_at"]
        assert (out["ultima_venta_dias"], out["ageing_dias"]) == (3, 3)

    def test_without_any_sale_the_ageing_counts_from_the_oldest_publication(self) -> None:
        figures = stock_audit.Sales()
        figures.add(replace(board_row("MLA11", d7=0, d30=0, gross=0.0, tg=0.0, costo=0.0), **LAST_SALES["MLA11"]))
        figures.add(replace(board_row("MLA20", d7=0, d30=0, gross=0.0, tg=0.0, costo=0.0), **LAST_SALES["MLA20"]))
        out = figures.out(with_margin=False)
        assert (out["ultima_venta"], out["ultima_venta_dias"], out["ageing_dias"]) == (None, None, 70)

    def test_without_a_board_row_both_are_unknown(self) -> None:
        out = stock_audit.Sales().out(with_margin=False)
        assert (out["ultima_venta"], out["ultima_venta_dias"], out["ageing_dias"]) == (None, None, None)


@pytest.mark.postgres
class TestStockAuditLastSaleAndAgeing:
    def test_each_row_and_variant_shows_its_last_sale_and_ageing(
        self, client, auditor, db, rol_admin, last_sales_board
    ) -> None:
        grant(db, rol_admin, "ml_metricas.ver")
        rows = {row["product_item_id"]: row for row in audit(client, auditor)["rows"]}
        notebook = rows[100]["ventas"]
        # its own MLA10 / MLA11 and its variant's MLA12: the variant sold last
        assert (notebook["ultima_venta"], notebook["ultima_venta_dias"], notebook["ageing_dias"]) == (
            "2026-11-15T12:30:00Z",
            3,
            3,
        )
        variant = rows[100]["variantes"][0]["ventas"]
        assert (variant["ultima_venta"], variant["ageing_dias"]) == ("2026-11-15T12:30:00Z", 3)
        mouse = rows[111]["ventas"]  # only its pack, never sold: since the pack's publication started
        assert (mouse["ultima_venta"], mouse["ultima_venta_dias"], mouse["ageing_dias"]) == (None, None, 40)
        for item in (130, 140):  # no Board row: unknown, never 0
            assert (rows[item]["ventas"]["ultima_venta"], rows[item]["ventas"]["ageing_dias"]) == (None, None)

    def test_without_metricas_there_is_no_last_sale_nor_ageing(self, client, auditor, last_sales_board) -> None:
        assert all(row["ventas"] is None for row in audit(client, auditor)["rows"])

    @pytest.mark.parametrize(
        "orden, direction, expected",
        [
            ("ultima_venta", "desc", [100, 111, 130, 140]),
            # never sold (with publications) is the oldest last sale; no publication at all is unknown, last
            ("ultima_venta", "asc", [111, 100, 130, 140]),
            ("ageing", "desc", [111, 100, 130, 140]),
            ("ageing", "asc", [100, 111, 130, 140]),
        ],
    )
    def test_it_sorts_by_last_sale_and_ageing_with_the_unknown_ones_last(
        self, client, auditor, db, rol_admin, last_sales_board, orden, direction, expected
    ) -> None:
        grant(db, rol_admin, "ml_metricas.ver")
        body = audit(client, auditor, orden=orden, dir=direction)
        assert [row["product_item_id"] for row in body["rows"]] == expected

    @pytest.mark.parametrize("orden", ["ultima_venta", "ageing"])
    def test_sorting_by_them_needs_metricas(self, client, auditor, orden) -> None:
        assert client.get(URL, headers=auditor, params={"orden": orden}).status_code == 403

    def test_the_export_carries_them_with_metricas(self, client, auditor, db, rol_admin, last_sales_board) -> None:
        grant(db, rol_admin, "ml_metricas.ver")
        rows = {r["Código"]: r for r in sheet(client, auditor)}
        assert (
            rows["C100"]["Última venta"],
            rows["C100"]["Días desde última venta"],
            rows["C100"]["Ageing (días)"],
        ) == (
            "2026-11-15",
            3,
            3,
        )
        assert (rows["C111"]["Última venta"], rows["C111"]["Ageing (días)"]) == (None, 40)
        assert rows["C140"]["Ageing (días)"] is None

    def test_the_export_has_no_rotation_columns_without_metricas(self, client, auditor) -> None:
        assert not set(sheet(client, auditor)[0]) & {"Última venta", "Ageing (días)"}


# --- Rotación (rotacion S2, L1): Días de cobertura and Rotación (veces) ----------------------------------------------


def photo(conn, day: date, **stock: tuple[int, int]) -> None:
    """The daily stock photo of `day`: item -> (erp, full), keyed `p<item>`."""
    for key, (erp, full) in stock.items():
        conn.execute(
            text("INSERT INTO producto_stock_diario VALUES (:f, :i, :e, :u)"),
            {"f": day, "i": int(key[1:]), "e": erp, "u": full},
        )


def fill_with_photos(conn) -> None:
    """The world above with two photos in the last 30 days (and one out of the window)."""
    fill(conn)
    today = board.today_business()
    photo(conn, today, p100=(4, 1), p101=(0, 1), p111=(100, 0), p110=(0, 3), p140=(2, 0))
    photo(conn, today - timedelta(days=29), p100=(4, 2), p140=(2, 0))
    photo(conn, today - timedelta(days=30), p100=(1000, 0))


@pytest.fixture()
def photographed(client, pg, db, rol_admin, admin_auth_headers, started):
    seed_rows(pg, fill_with_photos)
    grant(db, rol_admin, PERMISO, "ml_metricas.ver")
    return admin_auth_headers


def rotation(ventas: dict) -> tuple:
    keys = ("dias_cobertura", "cobertura_infinita", "rotacion", "stock_promedio", "stock_promedio_dias")
    return tuple(ventas[key] for key in keys)


@pytest.mark.postgres
class TestStockAuditCoverageAndRotation:
    def test_with_photos_the_rotation_is_over_the_average_stock_of_the_days_photographed(
        self, client, photographed, board_calls
    ) -> None:
        rows = {row["product_item_id"]: row for row in audit(client, photographed)["rows"]}
        # notebook: 3 units in 30 days (its own 2 + its variant's 1); stock now 8 (ERP 5 + Full 2 + the variant's 1)
        # -> 8 / (3 / 30) = 80 days; average stock (4 + 1 + 1, then 4 + 2) / 2 days = 6 -> 3 / 6 = 0.5 times
        assert rotation(rows[100]["ventas"]) == (80.0, False, 0.5, 6.0, 2)
        # the variant on its own: Full 1 now, 1 sold; average Full (1 + 0) / 2
        assert rotation(rows[100]["variantes"][0]["ventas"]) == (30.0, False, 2.0, 0.5, 2)
        # mice: 20 sold (2 packs of 10); 130 now (ERP 100 + 30 in packs); average (100 + 3 x 10 + 0) / 2 = 65
        assert rotation(rows[111]["ventas"]) == (195.0, False, 0.31, 65.0, 2)

    def test_stock_without_sales_lasts_forever(self, client, photographed, board_calls) -> None:
        rows = {row["product_item_id"]: row for row in audit(client, photographed)["rows"]}
        # 140: 2 in stock, nothing sold: infinite coverage, rotation 0
        assert rotation(rows[140]["ventas"]) == (None, True, 0.0, 2.0, 2)
        # the PC: stock 1 and never photographed in the window: its average is 0, a division by zero ("—")
        assert rotation(rows[130]["ventas"]) == (None, True, None, 0.0, 2)

    def test_without_photos_the_current_stock_stands_in_and_says_so(self, client, auditor, db, rol_admin, board_calls):
        grant(db, rol_admin, "ml_metricas.ver")
        rows = {row["product_item_id"]: row for row in audit(client, auditor)["rows"]}
        # 0 days photographed: the stock now (130) instead of the average, marked by stock_promedio_dias = 0
        assert rotation(rows[111]["ventas"]) == (195.0, False, 0.15, 130.0, 0)

    @pytest.mark.parametrize(
        "orden, direction, expected",
        [
            # infinite coverage is the worst: the highest
            ("cobertura", "desc", [130, 140, 111, 100]),
            ("cobertura", "asc", [100, 111, 130, 140]),
            ("rotacion", "desc", [100, 111, 140, 130]),
        ],
    )
    def test_it_sorts_by_coverage_and_rotation(
        self, client, photographed, board_calls, orden, direction, expected
    ) -> None:
        body = audit(client, photographed, orden=orden, dir=direction)
        assert [row["product_item_id"] for row in body["rows"]] == expected

    @pytest.mark.parametrize("orden", ["cobertura", "rotacion"])
    def test_sorting_by_them_needs_metricas(self, client, auditor, orden) -> None:
        assert client.get(URL, headers=auditor, params={"orden": orden}).status_code == 403

    def test_the_export_carries_coverage_and_rotation(self, client, photographed, board_calls) -> None:
        rows = {r["Código"]: r for r in sheet(client, photographed)}
        assert (rows["C100"]["Días de cobertura"], rows["C100"]["Rotación (veces)"]) == (80.0, 0.5)
        assert (rows["C140"]["Días de cobertura"], rows["C140"]["Rotación (veces)"]) == ("∞", 0.0)
        assert rows["C130"]["Rotación (veces)"] is None
        assert rows["C101"]["Rotación (veces)"] == 2.0
