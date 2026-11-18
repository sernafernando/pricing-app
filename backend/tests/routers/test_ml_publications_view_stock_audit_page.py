"""The Auditoría de stock reads sales, rotation and markups for the page it answers, not for every row (pubml-lentitud).

A value, unit, name or promo order does not depend on them, so the rows are sorted and cut first and only the page's
rows are enriched, with ONE Board read for their sales and their whole products' rotation. A sales or margin order,
a Marca / Categoría level and the export need every row's figures, so they still read them all (once). Whatever the
path, a page's row is exactly the row the full read answers. Invented data only (the L2 probes' world).
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

import pytest

from app.services.ml_publications.view import stock_audit
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401
from tests.routers.test_ml_publications_view_stock_audit import audit, no_split, started  # noqa: F401
from tests.routers.test_ml_publications_view_stock_audit_rotation_l2_probes import CALLS, mine  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401

# Notebook 100's whole product: its own MLA10/MLA11 and its variant 101's MLA12/MLA13.
NOTEBOOK_MLAS = {"MLA10", "MLA11", "MLA12", "MLA13"}


@pytest.fixture()
def markup_reads(monkeypatch) -> list[set[str]]:
    seen: list[set[str]] = []

    def spy(db, pricing_db, mlas):
        seen.append(set(mlas))
        return {}

    monkeypatch.setattr(stock_audit, "publication_markups", spy)
    return seen


@pytest.mark.postgres
class TestPageFirst:
    def test_a_value_order_reads_the_board_only_for_the_page(self, client, mine) -> None:
        body = audit(client, mine, limit=1)
        assert [row["product_item_id"] for row in body["rows"]] == [100]
        assert len(CALLS) == 1
        assert set(CALLS[0]) <= NOTEBOOK_MLAS

    def test_a_filtered_page_reads_the_board_once(self, client, mine) -> None:
        audit(client, mine, estado="active", limit=1)
        assert len(CALLS) == 1  # the page's sales and its whole products' rotation, together

    def test_a_filtered_full_read_reads_the_board_once(self, client, mine) -> None:
        audit(client, mine, q="MLA60")
        assert len(CALLS) == 1

    def test_the_markups_are_read_only_for_the_page(self, client, db, rol_admin, mine, markup_reads) -> None:
        grant(db, rol_admin, "ml_metricas.ver_ganancia")
        audit(client, mine, limit=1)
        assert len(markup_reads) == 1
        assert markup_reads[0] <= NOTEBOOK_MLAS

    @pytest.mark.parametrize("orden", ["unidades_30d", "rotacion"])
    def test_a_sales_order_reads_every_row(self, client, mine, orden) -> None:
        audit(client, mine, orden=orden, limit=1)
        assert len(CALLS) == 1
        assert {"MLA10", "MLA20", "MLA60"} <= set(CALLS[0])

    def test_a_group_level_reads_every_row(self, client, mine) -> None:
        audit(client, mine, nivel="marca", limit=1)
        assert len(CALLS) == 1
        assert {"MLA10", "MLA20", "MLA60"} <= set(CALLS[0])


@pytest.fixture()
def margin(db, rol_admin, mine, markup_reads):
    """The auditor also sees margins: every order is allowed and the markups are read (spied, none found)."""
    grant(db, rol_admin, "ml_metricas.ver_ganancia")
    return mine


def assert_pages_are_the_full_read(client, headers, **params) -> None:
    """Page 1 and page 2 (2 rows each) answer exactly the full read's rows in its order, with the same total and
    every KPI (L4: the numbers never depend on the page)."""
    full = audit(client, headers, limit=50, **params)
    assert full["total"] >= 3, params  # so that page 2 is not empty
    for offset in (0, 2):
        page = audit(client, headers, limit=2, offset=offset, **params)
        assert page["rows"] == full["rows"][offset : offset + 2], (params, offset)
        assert {k: v for k, v in page.items() if k not in ("rows", "offset", "limit")} == {
            k: v for k, v in full.items() if k not in ("rows", "offset", "limit")
        }, (params, offset)


@pytest.mark.postgres
class TestPageParity:
    @pytest.mark.parametrize("orden", stock_audit.ORDERS)
    @pytest.mark.parametrize("direction", ["asc", "desc"])
    def test_every_order_pages_like_the_full_read(self, client, margin, orden, direction) -> None:
        assert_pages_are_the_full_read(client, margin, orden=orden, dir=direction)

    @pytest.mark.parametrize("orden", ["valor_total", "descripcion", "unidades_30d", "rotacion", "markup"])
    def test_every_order_pages_like_the_full_read_under_a_filter(self, client, margin, orden) -> None:
        assert_pages_are_the_full_read(client, margin, orden=orden, estado="active")

    @pytest.mark.parametrize("nivel", ["marca", "categoria"])
    @pytest.mark.parametrize("orden", ["valor_total", "unidades_30d"])
    def test_a_group_level_answers_the_same_groups(self, client, margin, nivel, orden) -> None:
        full = audit(client, margin, nivel=nivel, orden=orden, limit=50)
        page = audit(client, margin, nivel=nivel, orden=orden, limit=1)
        assert page["rows"] == full["rows"][:1]
        assert (page["total"], page["kpis"]) == (full["total"], full["kpis"])

    def test_without_the_margin_permission_a_page_is_the_full_reads(self, client, mine) -> None:
        assert_pages_are_the_full_read(client, mine, orden="valor_total")
        assert_pages_are_the_full_read(client, mine, orden="unidades_30d")


def baseline(client, headers, monkeypatch, **params) -> dict:
    """The answer of the path before pubml-lentitud: every row enriched first, then sorted and cut."""
    with monkeypatch.context() as patch:
        patch.setattr(stock_audit, "page_first", lambda orden, nivel: False)
        return audit(client, headers, **params)


@pytest.mark.postgres
class TestOldVersusNew:
    """L4 (owner: "que los datos no sean mentira"): the page-first answer equals the old full path's answer, row by
    row, with the same total and KPIs, for every order, both directions, pages 1 and 2, with and without a filter."""

    @pytest.mark.parametrize("orden", stock_audit.ORDERS)
    @pytest.mark.parametrize("direction", ["asc", "desc"])
    def test_every_order_answers_what_the_old_path_answered(
        self, client, margin, monkeypatch, orden, direction
    ) -> None:
        for filters in ({}, {"estado": "active"}):
            for offset in (0, 2):
                params = {"orden": orden, "dir": direction, "limit": 2, "offset": offset, **filters}
                assert audit(client, margin, **params) == baseline(client, margin, monkeypatch, **params), params

    def test_without_the_margin_permission_too(self, client, mine, monkeypatch) -> None:
        for orden in ("valor_total", "descripcion", "promos_aplicadas", "unidades_30d"):
            params = {"orden": orden, "limit": 2}
            assert audit(client, mine, **params) == baseline(client, mine, monkeypatch, **params), params
