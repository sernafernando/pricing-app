"""`GET /api/ml-publications/view/items`: each row's 30-day sales summary (`sales_30d`) and its permissions.

Same harness as the KPI strip's (`test_ml_publications_view_kpis.py`): the store and the Board's tables in one
throwaway Postgres schema. The arithmetic is pinned in `view/test_sales_summary_postgres.py`; this file pins the
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
        assert "markup" not in str(got["MLA1"]["sales_30d"])

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
