"""Verifier probes for the Rotación columns (rotacion S2, L1). Invented data only."""

# ruff: noqa: F811 -- the imported fixtures are used by name
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services.ml_daily_metrics import board
from app.services.ml_publications.view import stock_audit
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import seed_rows
from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401
from tests.routers.test_ml_publications_view_stock_audit import (  # noqa: F401
    PERMISO,
    audit,
    board_row,
    fill,
    no_split,
    photo,
    product,
    publication,
    sheet,
    started,
)
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed


def world(conn) -> None:
    fill(conn)
    today = board.today_business()
    # product 160: ERP 4, two publications on two user products (Full 6 each)
    product(conn, 160, 10, "USD", 4, 60)
    publication(conn, "MLA60", 160, "UP60")
    publication(conn, "MLA61", 160, "UP61")
    seed.add_stock(conn, "UP60", full=6, own=0)
    seed.add_stock(conn, "UP61", full=6, own=0)
    # pack 110 (x10) and mouse 111: photographed with my own numbers
    for day, (erp, packs) in ((today, (80, 5)), (today - timedelta(days=1), (120, 1))):
        photo(conn, day, p111=(erp, 0), p110=(0, packs), p160=(4, 12))


@pytest.fixture()
def mine(client, pg, db, rol_admin, admin_auth_headers, started, monkeypatch):
    seed_rows(pg, world)
    grant(db, rol_admin, PERMISO, "ml_metricas.ver")
    figures = {
        "MLA20": board_row("MLA20", d7=1, d30=3, gross=100.0, tg=10.0, costo=40.0),  # 3 packs of 10 = 30 mice
        "MLA60": replace(
            board_row("MLA60", d7=0, d30=12, gross=100.0, tg=10.0, costo=40.0),
            last_sale_at=MLA60_SOLD,
            ageing_days=9,
        ),
        # the product's other publication: it sold 4 later, so the whole product's last sale is this one's
        "MLA61": replace(
            board_row("MLA61", d7=1, d30=4, gross=50.0, tg=5.0, costo=20.0),
            last_sale_at=MLA61_SOLD,
            ageing_days=2,
        ),
    }
    monkeypatch.setattr(
        stock_audit, "metrics_by_mla", lambda db, mlas, sell_in_out=False: {m: figures[m] for m in mlas if m in figures}
    )
    monkeypatch.setattr(
        stock_audit, "summed_sales", stock_audit.summed_from_rows
    )  # these Board rows, summed one by one
    return admin_auth_headers


MLA60_SOLD = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)
MLA61_SOLD = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)


def by_item(body):
    return {r["product_item_id"]: r for r in body["rows"]}


@pytest.mark.postgres
class TestPackAggregation:
    def test_pack_row_and_base_row_use_base_units_and_totals_never_averages(self, client, mine) -> None:
        rows = by_item(audit(client, mine))
        pack = rows[111]["variantes"][0]["ventas"]  # 3 packs sold, 3 packs in Full, avg Full (5+1)/2 = 3
        assert (pack["dias_cobertura"], pack["rotacion"], pack["stock_promedio"]) == (30.0, 1.0, 3.0)
        base = rows[111]["ventas"]  # 30 mice sold; stock 100 + 3x10 = 130; avg ERP (80+120)/2=100 + 3x10 = 130
        assert base["unidades_30d"] == 30
        assert (base["dias_cobertura"], base["stock_promedio"], base["rotacion"]) == (130.0, 130.0, 0.23)


@pytest.mark.postgres
class TestFilteredAudit:
    """L2 (owner): "Con filtro, usar las ventas de todo el producto" -- Última venta, Ageing, Días de cobertura and
    Rotación (veces) are the whole product's (all its publications, all its stock), whatever the filter."""

    def test_unfiltered_product_with_two_user_products(self, client, mine) -> None:
        v = by_item(audit(client, mine))[160]["ventas"]
        # stock now 4 + 6 + 6 = 16; 12 + 4 sold; avg 16
        assert v["unidades_30d"] == 16
        assert (v["dias_cobertura"], v["stock_promedio"], v["rotacion"]) == (30.0, 16.0, 1.0)

    def test_filtered_to_one_publication_the_rotation_figures_are_the_whole_products(self, client, mine) -> None:
        row = by_item(audit(client, mine, q="MLA60"))[160]
        v = row["ventas"]
        # the screen's own figures follow the filter: MLA60's 12 sold, its user product's 6 in Full
        assert (v["unidades_30d"], row["full"]["unidades"]) == (12, 6)
        # the rotation group does not: 16 in stock, 16 sold, the latest sale and its ageing are MLA61's
        assert (v["dias_cobertura"], v["stock_promedio"], v["rotacion"]) == (30.0, 16.0, 1.0)
        assert datetime.fromisoformat(v["ultima_venta"].replace("Z", "+00:00")) == MLA61_SOLD
        assert (v["ultima_venta_dias"], v["ageing_dias"]) == (2, 2)

    def test_a_filter_that_leaves_no_sale_still_shows_the_products_coverage(self, client, mine) -> None:
        v = by_item(audit(client, mine, q="MLA61"))[160]["ventas"]
        assert v["unidades_30d"] == 4
        assert (v["dias_cobertura"], v["cobertura_infinita"], v["rotacion"]) == (30.0, False, 1.0)

    def test_sorting_by_the_rotation_group_uses_the_whole_products_figures(self, client, mine) -> None:
        body = audit(client, mine, q="MLA60", orden="rotacion", dir="desc")
        assert by_item(body)[160]["ventas"]["rotacion"] == 1.0
        assert [r["product_item_id"] for r in body["rows"]] == [160]


@pytest.mark.postgres
class TestEmptyAndExport:
    def test_no_photo_at_all_is_a_200_with_the_approximation_flag(self, client, mine, pg) -> None:
        with pg.begin() as conn:
            conn.execute(text("DELETE FROM producto_stock_diario"))
        v = by_item(audit(client, mine))[160]["ventas"]
        assert (v["stock_promedio_dias"], v["stock_promedio"]) == (0, 16.0)

    def test_export_without_metricas_has_no_rotation_columns_even_when_sorted_default(
        self, client, pg, db, rol_admin, admin_auth_headers, started
    ) -> None:
        seed_rows(pg, world)
        grant(db, rol_admin, PERMISO)
        assert not set(sheet(client, admin_auth_headers)[0]) & {"Última venta", "Días de cobertura", "Rotación (veces)"}
        assert (
            client.get(
                "/api/ml-publications/view/stock-audit/export",
                headers=admin_auth_headers,
                params={"orden": "cobertura"},
            ).status_code
            == 403
        )
