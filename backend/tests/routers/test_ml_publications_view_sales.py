"""`GET /api/ml-publications/view/items`: each row's Métricas ML figures (`metrics`, and the older `sales_30d`) and
their permissions.

Same harness as the KPI strip's (`test_ml_publications_view_kpis.py`): the store and the Board's tables in one
throwaway Postgres schema. The arithmetic is pinned in `view/test_row_metrics_postgres.py`; this file pins the
HTTP surface: the units and the gross need `ml_metricas.ver`, the markup also `ml_metricas.ver_ganancia`.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

import pytest

from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import GANANCIA, URL, VER, seed_rows
from tests.routers.test_ml_publications_view_kpis import METRICAS, _seller, fill, pg, sell, view_pg  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres


def rows(client, headers) -> dict:
    response = client.get(URL, headers=headers)
    assert response.status_code == 200, response.text
    return {row["item_id"]: row for row in response.json()["items"]}


@pytest.fixture()
def sold(pg):
    seed_rows(pg, fill)
    sell(pg, (1, [("MLA1", None, 2)]), (2, [("MLA1", 11, 3)]), accredited=seed.real_hours_ago(1))
    return pg


class TestSales30d:
    def test_without_ml_metricas_ver_there_is_no_sales_summary(self, client, sold, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER, GANANCIA)
        got = rows(client, admin_auth_headers)
        assert all("sales_30d" not in row for row in got.values())

    def test_units_and_gross_with_ml_metricas_ver_and_no_markup_without_ver_ganancia(
        self, client, sold, db, rol_admin, admin_auth_headers
    ):
        grant(db, rol_admin, VER, METRICAS)
        got = rows(client, admin_auth_headers)
        assert got["MLA1"]["sales_30d"] == {"units": 5, "gross": 50.0}
        assert "markup" not in got["MLA1"]["sales_30d"]

    def test_the_markup_comes_with_ver_ganancia(self, client, sold, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER, METRICAS, GANANCIA)
        got = rows(client, admin_auth_headers)
        # every seeded order: Total Gauss 1 over cost 1
        assert got["MLA1"]["sales_30d"] == {"units": 5, "gross": 50.0, "markup": 100.0}

    def test_a_publication_without_sales_reads_zero_and_no_markup(
        self, client, sold, db, rol_admin, admin_auth_headers
    ):
        grant(db, rol_admin, VER, METRICAS, GANANCIA)
        got = rows(client, admin_auth_headers)
        assert got["MLA2"]["sales_30d"] == {"units": 0, "gross": 0.0, "markup": None}


class TestMetrics:
    """`metrics`: Métricas ML's publication row over the last 30 business days (the Board's own figures, pinned in
    `view/test_row_metrics_postgres.py`). Units, gross, series, last sale and ageing need `ml_metricas.ver`; the
    markup, its trend and Total Gauss also `ml_metricas.ver_ganancia` -- absent, never zero, without it."""

    MARGIN = {"total_gauss_30d", "markup_30d", "markup_delta_pp", "series_markup_90d"}

    def test_without_ml_metricas_ver_there_are_no_metrics(self, client, sold, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER, GANANCIA)
        assert all("metrics" not in row for row in rows(client, admin_auth_headers).values())

    def test_sales_and_rotation_with_ml_metricas_ver_and_no_margin_without_ver_ganancia(
        self, client, sold, db, rol_admin, admin_auth_headers
    ):
        grant(db, rol_admin, VER, METRICAS)
        got = rows(client, admin_auth_headers)["MLA1"]["metrics"]
        assert (got["units_7d"], got["units_30d"], got["gross_30d"]) == (5, 5, 50.0)
        assert len(got["series_units_90d"]) == 90 and sum(got["series_units_90d"]) == 5
        assert got["last_sale_at"] is not None and got["ageing_days"] in (0, 1)
        assert self.MARGIN.isdisjoint(got)

    def test_the_margin_comes_with_ver_ganancia(self, client, sold, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER, METRICAS, GANANCIA)
        got = rows(client, admin_auth_headers)["MLA1"]["metrics"]
        # every seeded order: Total Gauss 1 over cost 1
        assert (got["total_gauss_30d"], got["markup_30d"]) == (2.0, 100.0)
        assert len(got["series_markup_90d"]) == 90 and 100.0 in got["series_markup_90d"]
        assert "markup_delta_pp" in got

    def test_a_publication_metricas_has_no_row_for_reads_null(self, client, sold, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER, METRICAS, GANANCIA)
        got = rows(client, admin_auth_headers)
        assert got["MLA2"]["metrics"] is None
        assert got["MLA2"]["sales_30d"] == {"units": 0, "gross": 0.0, "markup": None}  # unchanged for older screens

    def test_one_board_for_the_whole_page(self, client, sold, db, rol_admin, admin_auth_headers, monkeypatch):
        from app.services.ml_daily_metrics import board

        grant(db, rol_admin, VER, METRICAS, GANANCIA)
        entered: list = []
        real = board.Board.__enter__
        monkeypatch.setattr(board.Board, "__enter__", lambda self: entered.append(self.f.group_by) or real(self))
        rows(client, admin_auth_headers)
        assert entered == ["publication"]
