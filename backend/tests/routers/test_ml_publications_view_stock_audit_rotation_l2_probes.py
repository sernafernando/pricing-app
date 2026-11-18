"""Verifier probes for L2: the Rotación group is the whole product's whatever the filter. Invented data only."""

# ruff: noqa: F811 -- the imported fixtures are used by name
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

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

KEYS = (
    "ultima_venta",
    "ultima_venta_dias",
    "ageing_dias",
    "dias_cobertura",
    "cobertura_infinita",
    "rotacion",
    "stock_promedio",
    "stock_promedio_dias",
)


CALLS: list = []


def at(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=timezone.utc)


def world(conn) -> None:
    fill(conn)
    today = board.today_business()
    product(conn, 160, 10, "USD", 4, 60)
    publication(conn, "MLA60", 160, "UP60")  # active, gold_special
    publication(conn, "MLA61", 160, "UP61", status="paused", kind="gold_pro")
    publication(conn, "MLA13", 101, "UP13")  # a second publication of variant 101
    seed.add_stock(conn, "UP60", full=6, own=0)
    seed.add_stock(conn, "UP61", full=6, own=0)
    seed.add_stock(conn, "UP13", full=2, own=0)
    for day in (today, today - timedelta(days=1)):
        photo(conn, day, p100=(5, 2), p101=(0, 3), p160=(4, 12))


def figures():
    def row(mla, d30, last, ageing):
        return replace(
            board_row(mla, d7=0, d30=d30, gross=10.0, tg=1.0, costo=5.0),
            last_sale_at=at(last) if last else None,
            ageing_days=ageing,
        )

    return {
        "MLA10": row("MLA10", 2, "2026-11-01T12:00:00", 20),
        "MLA12": row("MLA12", 1, "2026-11-13T12:00:00", 5),
        "MLA13": row("MLA13", 4, "2026-11-12T12:00:00", 6),
        "MLA60": row("MLA60", 12, "2026-11-10T12:00:00", 8),
        "MLA61": row("MLA61", 8, "2026-11-15T12:00:00", 3),
    }


@pytest.fixture()
def mine(client, pg, db, rol_admin, admin_auth_headers, started, monkeypatch):
    seed_rows(pg, world)
    grant(db, rol_admin, PERMISO, "ml_metricas.ver")
    data = figures()
    CALLS.clear()

    def fake(db, mlas, sell_in_out=False):
        CALLS.append(sorted(mlas))
        return {m: data[m] for m in mlas if m in data}

    monkeypatch.setattr(stock_audit, "metrics_by_mla", fake)
    return admin_auth_headers


def rot(v):
    return {k: v[k] for k in KEYS}


def by_item(body):
    return {r["product_item_id"]: r for r in body["rows"]}


@pytest.mark.postgres
class TestWholeProduct:
    def test_filters_do_not_change_the_rotation_group(self, client, mine) -> None:
        whole = rot(by_item(audit(client, mine))[160]["ventas"])
        # 20 sold (12 + 8), stock 4 + 6 + 6 = 16, last sale the 15th (MLA61), ageing 3
        assert (whole["dias_cobertura"], whole["rotacion"], whole["stock_promedio"], whole["ageing_dias"]) == (
            24.0,
            1.25,
            16.0,
            3,
        )
        assert whole["ultima_venta"] == "2026-11-15T12:00:00Z"
        for params in ({"q": "MLA60"}, {"estado": "active"}, {"tipo": "clasica"}, {"tipo": "premium"}, {"q": "MLA61"}):
            body = audit(client, mine, **params)
            rows = by_item(body)
            if 160 not in rows:
                continue
            assert rot(rows[160]["ventas"]) == whole, params

    def test_the_rest_of_the_row_still_follows_the_filter(self, client, mine) -> None:
        row = by_item(audit(client, mine, q="MLA60"))[160]
        assert row["ventas"]["unidades_30d"] == 12  # only the filtered publication
        assert rot(row["ventas"])["dias_cobertura"] == 24.0  # but the whole product's coverage

    def test_variant_filtered_out_entirely_the_base_still_counts_it(self, client, mine) -> None:
        unfiltered = by_item(audit(client, mine))[100]["ventas"]
        # base: sold 2 + 1 + 4 = 7; stock 5 + 2 + 3 = 10; average 5 + 2 + 3 = 10
        assert (unfiltered["dias_cobertura"], unfiltered["rotacion"]) == (42.9, 0.7)
        row = by_item(audit(client, mine, q="MLA10"))[100]
        assert row["variantes"] == []
        assert rot(row["ventas"]) == rot(unfiltered)

    def test_variant_row_is_the_whole_variant_with_its_other_publication_filtered(self, client, mine) -> None:
        body = audit(client, mine, q="MLA12")
        base = by_item(body)[100]
        variant = base["variantes"][0]["ventas"]
        # the variant: 1 + 4 = 5 sold; Full 1 + 2 = 3 (filtered row shows 1); average Full 3
        assert (variant["dias_cobertura"], variant["rotacion"], variant["stock_promedio"]) == (18.0, 1.67, 3.0)
        assert variant["ultima_venta"] == "2026-11-13T12:00:00Z"
        whole_variant = audit(client, mine)
        assert rot(variant) == rot(by_item(whole_variant)[100]["variantes"][0]["ventas"])
        assert rot(base["ventas"]) == rot(by_item(whole_variant)[100]["ventas"])

    def test_pack_whole_under_estado_filter(self, client, mine) -> None:
        a = by_item(audit(client, mine))[111]["ventas"]
        b = by_item(audit(client, mine, estado="active"))[111]["ventas"]
        assert rot(a) == rot(b)

    @pytest.mark.parametrize("orden", ["ultima_venta", "ageing", "cobertura", "rotacion"])
    @pytest.mark.parametrize("direction", ["asc", "desc"])
    def test_sorting_under_a_filter_keeps_the_unfiltered_relative_order(self, client, mine, orden, direction) -> None:
        full = [r["product_item_id"] for r in audit(client, mine, orden=orden, dir=direction)["rows"]]
        part = [r["product_item_id"] for r in audit(client, mine, orden=orden, dir=direction, estado="active")["rows"]]
        assert part == [i for i in full if i in part]
        assert 160 in part

    def test_export_under_a_filter(self, client, mine) -> None:
        rows = {r["Código"]: r for r in sheet(client, mine, q="MLA60")}
        assert (rows["C160"]["Días de cobertura"], rows["C160"]["Rotación (veces)"], rows["C160"]["Ageing (días)"]) == (
            24.0,
            1.25,
            3,
        )

    def test_unfiltered_reads_the_board_once(self, client, mine) -> None:
        audit(client, mine)
        assert len(CALLS) == 1

    def test_filtered_reads_the_board_once(self, client, mine) -> None:
        audit(client, mine, q="MLA60")
        assert len(CALLS) == 1  # the filtered rows and their whole products in the same read (pubml-lentitud)


@pytest.mark.postgres
class TestQueryCount:
    def test_statements_do_not_grow_with_the_number_of_products(self, client, mine, pg) -> None:
        counted: list[str] = []

        def spy(conn, cursor, statement, *a):
            counted.append(statement)

        event.listen(Engine, "before_cursor_execute", spy)
        try:
            audit(client, mine, estado="active")
            few = len(counted)
            with pg.begin() as conn:
                for i in range(30):
                    product(conn, 300 + i, 10, "USD", 3, 60)
                    publication(conn, f"MLA9{i:02d}", 300 + i, f"UP9{i:02d}")
                    seed.add_stock(conn, f"UP9{i:02d}", full=1, own=0)
            counted.clear()
            audit(client, mine, estado="active")
            many = len(counted)
        finally:
            event.remove(Engine, "before_cursor_execute", spy)
        assert many <= few + 2
