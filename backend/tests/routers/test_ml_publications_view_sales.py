"""`GET /api/ml-publications/view/items`: each row's Métricas ML figures (`metrics`, and the older `sales_30d`) and
their permissions.

Same harness as the KPI strip's (`test_ml_publications_view_kpis.py`): the store and the Board's tables in one
throwaway Postgres schema. The arithmetic is pinned in `view/test_row_metrics_postgres.py`; this file pins the
HTTP surface: the units and the gross need `ml_metricas.ver`, the markup also `ml_metricas.ver_ganancia`.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import update

from app.models.ml_order_metrics import MlOrderMetrics
from app.services.ml_daily_metrics import board as board_module, kpi_strip

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


class TestRoundingAndBusinessDay:
    """The arithmetic the deleted `test_sales_summary_postgres` pinned, now on the HTTP surface: the markup rounds
    exactly as Métricas displays it, and the 30 days are Buenos Aires business days."""

    NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)

    @pytest.fixture(autouse=True)
    def _clock(self, monkeypatch):
        from app.services.ml_daily_metrics import board

        monkeypatch.setattr(board, "now_utc", lambda: self.NOW)

    @staticmethod
    def priced(engine, order_id, mla, qty, *, tg, costo, accredited) -> None:
        sell(engine, (order_id, [(mla, None, qty)]), accredited=accredited)
        with engine.begin() as conn:
            conn.execute(
                update(MlOrderMetrics)
                .where(MlOrderMetrics.order_id == order_id)
                .values(total_gauss=Decimal(tg), costo_mercaderia=Decimal(costo))
            )

    def test_an_exact_half_tie_rounds_like_metricas_displays_it(self, client, pg, db, rol_admin, admin_auth_headers):
        """1.15 % exactly: Métricas shows `round_pp` (the float's round, 1.1 -- 1.15 is 1.1499... as a float), not
        the Decimal's half-even 1.2. The same sales must read the same number on both screens."""
        seed_rows(pg, fill)
        self.priced(pg, 1, "MLA1", 1, tg="1.15", costo="100", accredited=datetime(2026, 9, 20, 15, tzinfo=timezone.utc))
        grant(db, rol_admin, VER, METRICAS, GANANCIA)
        got = rows(client, admin_auth_headers)["MLA1"]
        expected = kpi_strip.round_pp(board_module.markup_of(Decimal("1.15"), Decimal("100")))
        assert got["metrics"]["markup_30d"] == got["sales_30d"]["markup"] == expected == 1.1

    def test_the_window_is_buenos_aires_business_days(self, client, pg, db, rol_admin, admin_auth_headers):
        seed_rows(pg, fill)
        # 23:59 of Aug 31st in Buenos Aires: the day before the window, out of it
        self.priced(pg, 1, "MLA1", 100, tg="1", costo="1", accredited=datetime(2026, 9, 1, 2, 59, tzinfo=timezone.utc))
        # 00:00 of Sep 1st in Buenos Aires: the window's first day, in it
        self.priced(pg, 2, "MLA1", 2, tg="1", costo="1", accredited=datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc))
        grant(db, rol_admin, VER, METRICAS)
        got = rows(client, admin_auth_headers)["MLA1"]
        assert got["metrics"]["units_30d"] == got["sales_30d"]["units"] == 2
        assert got["metrics"]["gross_30d"] == got["sales_30d"]["gross"] == 20.0


class TestSortingByMetricas:
    """`orden` by Métricas' figures ranks the whole filtered set (pinned in `view/test_metrics_sort_postgres.py`);
    here, the HTTP surface: who may ask for which sort, and the order across pages."""

    @pytest.fixture()
    def ranked(self, pg):
        seed_rows(pg, fill)
        sell(pg, (1, [("MLA2", None, 4)]), (2, [("MLA1", None, 1)]), accredited=seed.real_hours_ago(1))
        return pg

    @staticmethod
    def page(client, headers, **params):
        return client.get(URL, headers=headers, params=params)

    @pytest.mark.parametrize("orden", ["facturado_30d", "unidades_7d", "unidades_30d", "markup_30d", "total_gauss_30d"])
    def test_without_ml_metricas_ver_every_metricas_sort_is_403(
        self, client, ranked, db, rol_admin, admin_auth_headers, orden
    ):
        grant(db, rol_admin, VER, GANANCIA)
        response = self.page(client, admin_auth_headers, orden=orden)
        assert response.status_code == 403
        assert METRICAS in response.json()["error"]["message"]

    @pytest.mark.parametrize("orden", ["markup_30d", "total_gauss_30d"])
    def test_the_margin_sorts_also_need_ver_ganancia(self, client, ranked, db, rol_admin, admin_auth_headers, orden):
        grant(db, rol_admin, VER, METRICAS)
        response = self.page(client, admin_auth_headers, orden=orden)
        assert response.status_code == 403
        assert GANANCIA in response.json()["error"]["message"]

    def test_the_whole_set_is_ranked_then_paged(self, client, ranked, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER, METRICAS)
        first = self.page(client, admin_auth_headers, orden="facturado_30d", limit=1)
        second = self.page(client, admin_auth_headers, orden="facturado_30d", limit=1, offset=1)
        third = self.page(client, admin_auth_headers, orden="facturado_30d", dir="asc", limit=1)
        assert [r.status_code for r in (first, second, third)] == [200, 200, 200]
        assert first.json()["items"][0]["item_id"] == "MLA2"  # 4 u. over 1
        assert second.json()["items"][0]["item_id"] == "MLA1"
        assert third.json()["items"][0]["item_id"] == "MLA1"  # ascending, the unsold MLA3 still last
        assert first.json()["total"] == 3

    def test_the_margin_sorts_answer_with_ver_ganancia(self, client, ranked, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, VER, METRICAS, GANANCIA)
        for orden in ("markup_30d", "total_gauss_30d"):
            assert self.page(client, admin_auth_headers, orden=orden).status_code == 200


class TestSeveralSortKeys:
    """`orden`/`dir` as csv (Productos' multi-column sort): every key is checked as a single sort would be."""

    @staticmethod
    def page(client, headers, **params):
        return client.get(URL, headers=headers, params=params)

    def test_a_metricas_key_anywhere_needs_ml_metricas_ver(self, client, pg, db, rol_admin, admin_auth_headers):
        seed_rows(pg, fill)
        grant(db, rol_admin, VER, GANANCIA)
        response = self.page(client, admin_auth_headers, orden="facturado_30d,titulo")
        assert response.status_code == 403 and METRICAS in response.json()["error"]["message"]

    @pytest.mark.parametrize("orden", ["titulo,costo", "precio,markup", "titulo,markup_30d"])
    def test_a_margin_key_anywhere_needs_ver_ganancia(self, client, pg, db, rol_admin, admin_auth_headers, orden):
        seed_rows(pg, fill)
        grant(db, rol_admin, VER, METRICAS)
        response = self.page(client, admin_auth_headers, orden=orden)
        assert response.status_code == 403 and GANANCIA in response.json()["error"]["message"]

    def test_a_figure_after_the_first_key_is_a_422_saying_why(self, client, pg, db, rol_admin, admin_auth_headers):
        seed_rows(pg, fill)
        grant(db, rol_admin, VER, METRICAS, GANANCIA)
        response = self.page(client, admin_auth_headers, orden="titulo,facturado_30d")
        assert response.status_code == 422
        assert "only as the first sort key" in response.json()["error"]["message"]

    def test_column_keys_combine_each_with_its_direction(self, client, pg, db, rol_admin, admin_auth_headers):
        def titled(conn) -> None:
            seed.add_item(conn, "MLA1", title="Beta", price=100)
            seed.add_item(conn, "MLA2", title="Alfa", price=300)
            seed.add_item(conn, "MLA3", title="Alfa", price=200)

        seed_rows(pg, titled)
        grant(db, rol_admin, VER)
        for direction, expected in (("desc,asc", ["MLA1", "MLA3", "MLA2"]), ("asc,desc", ["MLA2", "MLA3", "MLA1"])):
            response = self.page(client, admin_auth_headers, orden="titulo,precio", dir=direction)
            assert response.status_code == 200, response.text
            assert [row["item_id"] for row in response.json()["items"]] == expected
