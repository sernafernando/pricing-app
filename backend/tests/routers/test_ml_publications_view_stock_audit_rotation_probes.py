"""Verifier probes for the Rotación columns (rotacion S2, L1). Invented data only."""

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
    PERMISO,
    audit,
    board_row,
    fill,
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
        "MLA60": board_row("MLA60", d7=0, d30=12, gross=100.0, tg=10.0, costo=40.0),
    }
    monkeypatch.setattr(
        stock_audit, "metrics_by_mla", lambda db, mlas, sell_in_out=False: {m: figures[m] for m in mlas if m in figures}
    )
    return admin_auth_headers


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
    def test_unfiltered_product_with_two_user_products(self, client, mine) -> None:
        v = by_item(audit(client, mine))[160]["ventas"]
        # stock now 4 + 6 + 6 = 16; 12 sold; avg 16
        assert (v["dias_cobertura"], v["stock_promedio"], v["rotacion"]) == (40.0, 16.0, 0.75)

    def test_filtered_the_average_stays_the_whole_products(self, client, mine) -> None:
        """The daily photo is per product (L1): a publication filter scopes the stock now and the sales, not the
        average stock, which stays the product's whole stock (pending the orchestrator's call)."""
        v = by_item(audit(client, mine, q="MLA60"))[160]["ventas"]
        assert (v["dias_cobertura"], v["stock_promedio"], v["rotacion"]) == (25.0, 16.0, 0.75)


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
