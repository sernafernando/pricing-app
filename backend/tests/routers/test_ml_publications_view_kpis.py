"""P9b.T1: `GET /api/ml-publications/view/kpis` (permissions, shape, period, filters, equality with Métricas).

Same harness as `test_ml_publications_view.py` (permissions in the SQLite test database, the store in a throwaway
Postgres schema), plus the Board's tables in that schema: the strip reads both in one transaction, as production
does. The arithmetic itself is pinned in `view/test_kpis_postgres.py`; this file pins the HTTP surface.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import String, func, literal, select, union_all
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.routers import ml_metricas, ml_publications_view
from app.services.ml_daily_metrics import board
from app.services.ml_publications.view import kpis as kpis_service, listing, status_block
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import (  # noqa: F401
    GANANCIA,
    URL as ITEMS_URL,
    VER,
    pg as view_pg,
    seed_rows,
)
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_units_sold_postgres import order

pytestmark = pytest.mark.postgres

URL = "/api/ml-publications/view/kpis"
METRICAS = "ml_metricas.ver"
PERIOD = {"desde": "2026-09-01", "hasta": "2026-09-30"}
SOLD = datetime(2026, 9, 20, 15, tzinfo=timezone.utc)


@pytest.fixture()
def pg(view_pg):  # noqa: F811 -- the imported fixture is used by name
    seed.create_board_tables(view_pg)
    return view_pg


@pytest.fixture(autouse=True)
def _seller(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)


@pytest.fixture()
def reader(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER, METRICAS)
    return admin_auth_headers


def get(client, headers, **params):
    return client.get(URL, headers=headers, params=params)


def sell(engine, *orders, accredited=SOLD) -> None:
    """`orders`: (order_id, [(mla, variation_id, qty)])."""
    session = sessionmaker(bind=engine)()
    for order_id, lines in orders:
        order(session, order_id, lines, accredited=accredited)
    session.commit()
    session.close()


def fill(conn) -> None:
    seed.add_item(conn, "MLA1", status="active")
    seed.add_item(conn, "MLA2", status="active")
    seed.add_item(conn, "MLA3", status="paused")


class TestPermission:
    def test_authentication_is_required(self, client, pg) -> None:
        assert client.get(URL).status_code in (401, 403)

    def test_a_user_without_ml_ops_ver_gets_403(self, client, pg, db, rol_ventas, auth_headers) -> None:
        grant(db, rol_ventas, METRICAS)
        response = get(client, auth_headers)
        assert response.status_code == 403 and VER in response.json()["error"]["message"]

    def test_a_user_without_ml_metricas_ver_gets_403_even_with_ml_ops_ver(
        self, client, pg, db, rol_ventas, auth_headers
    ) -> None:
        grant(db, rol_ventas, VER)
        response = get(client, auth_headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"
        assert METRICAS in response.json()["error"]["message"]

    def test_who_may_ask_is_decided_before_what_is_asked(self, client, pg, db, rol_ventas, auth_headers) -> None:
        bad = {"periodo": "bogus", "estado": "bogus"}
        assert client.get(URL, params=bad).status_code in (401, 403)
        assert get(client, auth_headers, **bad).status_code == 403
        grant(db, rol_ventas, VER)
        assert get(client, auth_headers, **bad).status_code == 403  # still no ml_metricas.ver

    def test_the_permission_code_is_the_metricas_one(self) -> None:
        assert ml_publications_view.PERMISO_METRICAS == METRICAS == ml_metricas.PERMISO_VER

    def test_a_pm_is_not_scoped(self, client, pg, db, active_user, rol_ventas, auth_headers, monkeypatch) -> None:
        from app.models.marca_pm import MarcaPM

        grant(db, rol_ventas, VER, METRICAS)
        db.add(MarcaPM(marca="OTRA", categoria="OTRA", usuario_id=active_user.id))
        db.flush()
        seed_rows(pg, fill)
        seen: list = []
        real = board.Board.__init__

        def spy(self, db_, f, *args, **kwargs):
            seen.append(kwargs.get("scope_pairs", "missing"))
            real(self, db_, f, *args, **kwargs)

        monkeypatch.setattr(board.Board, "__init__", spy)
        assert get(client, auth_headers, **PERIOD).status_code == 200
        assert seen == [None]


class TestContract:
    def test_the_response_shape_without_the_profit_permission(self, client, pg, reader) -> None:
        seed_rows(pg, fill)
        sell(pg, (1, [("MLA1", None, 2)]), (2, [("MLA2", 11, 3), ("MLA2", 12, 4)]))
        body = get(client, reader, **PERIOD).json()
        assert set(body) == {"period", "kpis", "mla_count", "can_see_margin"}
        assert body["period"] == {
            "date_from": "2026-09-01",
            "date_to": "2026-09-30",
            "prev_from": "2026-08-02",
            "prev_to": "2026-08-31",
        }
        assert (
            body["can_see_margin"] is False and body["mla_count"] == 3
        )  # the paused one is selected too: the default hides only gone items
        assert set(body["kpis"]) == {"units", "gross", "rows_with_sales", "ageing"}  # no profit fields at all
        assert body["kpis"]["units"]["value"] == 9
        assert len(body["kpis"]["units"]["series"]) == 30
        assert "ads" not in body and "total_gauss" not in str(body)

    def test_the_profit_fields_come_with_ver_ganancia(self, client, pg, db, rol_admin, reader) -> None:
        seed_rows(pg, fill)
        sell(pg, (1, [("MLA1", None, 2)]))
        grant(db, rol_admin, GANANCIA)
        body = get(client, reader, **PERIOD).json()
        assert body["can_see_margin"] is True
        assert set(body["kpis"]) == {"units", "gross", "total_gauss", "markup", "rows_with_sales", "ageing"}

    def test_it_is_what_metricas_answers_for_the_same_set_and_period(self, client, pg, db, rol_admin, reader) -> None:
        seed_rows(pg, fill)
        sell(pg, (1, [("MLA1", None, 2)]), (2, [("MLA2", 11, 3)]), (3, [("MLA3", None, 100)]))
        grant(db, rol_admin, GANANCIA)
        body = get(client, reader, estado="active", **PERIOD).json()
        f = board.BoardFilter(
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 30),
            group_by="publication",
            mla_source=union_all(*(select(literal(v, String).label("mla")) for v in ("MLA1", "MLA2"))),
        )
        session = sessionmaker(bind=pg)()
        with board.Board(session, f, scope_pairs=None) as b:
            expected = ml_metricas._kpis(b.kpis(), True).model_dump(mode="json")
        session.close()
        assert body["kpis"] == expected
        assert body["kpis"]["units"]["value"] == 5

    def test_the_filters_of_the_list_select_the_set(self, client, pg, reader) -> None:
        seed_rows(pg, fill)
        sell(pg, (1, [("MLA1", None, 2)]), (3, [("MLA3", None, 100)]))
        everything = get(client, reader, estado="active,paused", **PERIOD).json()
        assert (everything["mla_count"], everything["kpis"]["units"]["value"]) == (3, 102)
        paused = get(client, reader, estado="paused", **PERIOD).json()
        assert (paused["mla_count"], paused["kpis"]["units"]["value"]) == (1, 100)
        assert get(client, reader, q="MLA1", **PERIOD).json()["mla_count"] == 1
        assert get(client, reader, q="nothing-matches", **PERIOD).json()["kpis"]["units"]["value"] == 0

    def test_the_timing_is_reported_in_a_header_and_in_the_log(self, client, pg, reader, caplog) -> None:
        seed_rows(pg, fill)
        with caplog.at_level(logging.INFO, logger="pubml.view"):
            response = get(client, reader, **PERIOD)
        assert "kpis;dur=" in response.headers["server-timing"]
        (line,) = [r.getMessage() for r in caplog.records if r.name == "pubml.view"]
        assert line.startswith("pubml.view endpoint=kpis total_ms=") and "mla_count=3" in line


class TestPeriod:
    def test_the_default_is_the_last_30_days_up_to_today(self, client, pg, reader) -> None:
        seed_rows(pg, fill)
        sell(pg, (1, [("MLA1", None, 2)]), accredited=seed.real_hours_ago(1))  # the real clock: the window is "now"
        body = get(client, reader).json()
        today = board.today_business()
        assert body["period"]["date_to"] == today.isoformat()
        assert body["period"]["date_from"] == (today - timedelta(days=29)).isoformat()
        assert body["kpis"]["units"]["value"] == 2

    @pytest.mark.parametrize("days", [7, 15, 30, 60, 90])
    def test_the_period_presets(self, client, pg, reader, days) -> None:
        body = get(client, reader, periodo=days).json()
        first, last = date.fromisoformat(body["period"]["date_from"]), date.fromisoformat(body["period"]["date_to"])
        assert (last - first).days + 1 == days and last == board.today_business()

    def test_a_custom_range_and_the_comparison(self, client, pg, reader) -> None:
        body = get(client, reader, comparar_con="anio_anterior", **PERIOD).json()
        assert body["period"]["prev_from"] == "2025-09-01" and body["period"]["prev_to"] == "2025-09-30"

    def test_only_hasta_ends_the_default_length_there(self, client, pg, reader) -> None:
        body = get(client, reader, hasta="2026-09-30").json()
        assert body["period"]["date_from"] == "2026-09-01"

    @pytest.mark.parametrize(
        "params, field",
        [
            ({"periodo": "45"}, "periodo"),
            ({"periodo": "x"}, "periodo"),
            ({"periodo": "7", "desde": "2026-09-01"}, "periodo"),
            ({"desde": "2026-09-01x"}, "desde"),
            ({"hasta": "yesterday"}, "hasta"),
            ({"desde": "2026-10-01", "hasta": "2026-09-01"}, "desde"),
            ({"desde": "2025-01-01", "hasta": "2026-09-01"}, "desde"),  # over a year
            ({"desde": "1999-01-01", "hasta": "2000-01-01"}, "desde"),
            ({"hasta": "2001-01-05"}, "hasta"),  # the default length would start before the lower bound
            ({"hasta": "2101-01-01"}, "hasta"),
            ({"comparar_con": "bogus"}, "comparar_con"),
            ({"estado": "bogus"}, "estado"),
        ],
    )
    def test_invalid_params_are_422_naming_the_param(self, client, pg, reader, params, field) -> None:
        response = get(client, reader, **params)
        assert response.status_code == 422 and response.json()["error"]["field"] == field


class TestSlowQuery:
    def test_a_statement_timeout_is_a_controlled_503_and_the_connection_goes_back(
        self, client, pg, reader, monkeypatch
    ) -> None:
        seed_rows(pg, fill)
        real = kpis_service.build_base_select

        def slow(f, *columns, **kwargs):  # the set is one column, so the delay goes in the WHERE
            return real(f, *columns, **kwargs).where(func.pg_sleep(1).is_not(None))

        monkeypatch.setattr(listing, "STATEMENT_TIMEOUT", "50ms")
        monkeypatch.setattr(kpis_service, "build_base_select", slow)
        response = get(client, reader, **PERIOD)
        assert response.status_code == 503 and response.json()["error"]["code"] == "consulta_lenta"
        assert pg.pool.checkedout() == 0
        monkeypatch.setattr(listing, "STATEMENT_TIMEOUT", "8s")
        monkeypatch.setattr(kpis_service, "build_base_select", real)
        status_block.REPORT.reset()
        assert get(client, reader, **PERIOD).status_code == 200
