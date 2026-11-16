"""abm-productos S12 / T6: one sync pass of the Tienda Nube catalog stores each TN product's name and description
(`tienda_nube_producto_textos`, one row per product), links variants to the ERP by SKU as before, and then applies the
links set by hand (`producto_tn_vinculos`) last, so a manual link always wins. Real Postgres."""

# ruff: noqa: F811 -- the fixture is imported and used by name

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.tienda_nube_sync_shared import sincronizar_catalogo
from tests.services.tienda_nube_pg import erp, links, tn_pg, tn_product  # noqa: F401

pytestmark = pytest.mark.postgres


def sync(engine, products: list[dict], *, complete: bool = True) -> dict:
    with Session(engine) as db:
        stats = sincronizar_catalogo(db, products, fetch_complete=complete)
        db.commit()
    return stats


def manual(conn, item_id: int, tn_product_id: int | None) -> None:
    conn.execute(
        text("INSERT INTO producto_tn_vinculos (item_id, tn_product_id) VALUES (:i, :p)"),
        {"i": item_id, "p": tn_product_id},
    )


class TestTexts:
    def test_one_row_per_tn_product_with_html_and_plain_text(self, tn_pg):
        sync(tn_pg, [tn_product(1, "Mouse UB500", ["455", "0455"], description="<p>Mouse<br>USB</p>")])

        with tn_pg.connect() as conn:
            rows = conn.execute(
                text("SELECT product_id, nombre, descripcion_html, descripcion_texto FROM tienda_nube_producto_textos")
            ).all()
        assert [tuple(r) for r in rows] == [(1, "Mouse UB500", "<p>Mouse<br>USB</p>", "Mouse\nUSB")]

    def test_a_later_sync_updates_the_texts(self, tn_pg):
        sync(tn_pg, [tn_product(1, "Mouse", ["455"], description="<p>Viejo</p>")])
        sync(tn_pg, [tn_product(1, "Mouse UB500", ["455"], description="<p>Nuevo</p>")])

        with tn_pg.connect() as conn:
            row = conn.execute(text("SELECT nombre, descripcion_texto FROM tienda_nube_producto_textos")).one()
        assert tuple(row) == ("Mouse UB500", "Nuevo")


class TestLinks:
    def test_sku_matching_still_links_exact_and_with_or_without_a_leading_zero(self, tn_pg):
        with tn_pg.begin() as conn:
            erp(conn, 10, "7790001", "A")
            erp(conn, 20, "0123456", "B")
            erp(conn, 30, "555", "C")
        sync(tn_pg, [tn_product(1, "A", ["7790001"]), tn_product(2, "B", ["123456"]), tn_product(3, "C", ["0555"])])

        with tn_pg.connect() as conn:
            assert links(conn) == {1: 10, 2: 20, 3: 30}

    def test_a_manual_link_survives_a_sync_run_and_takes_the_item_off_its_sku_match(self, tn_pg):
        with tn_pg.begin() as conn:
            erp(conn, 10, "7790001", "NB LENOVO V15")
            erp(conn, 20, "7790002", "NB LENOVO V15 OB")
            manual(conn, 10, 2)  # item 10 is TN product 2, whatever the SKUs say
        sync(tn_pg, [tn_product(1, "Lenovo V15", ["7790001"]), tn_product(2, "Lenovo V15 caja abierta", ["7790002"])])

        with tn_pg.connect() as conn:
            assert links(conn) == {1: None, 2: 10}

    def test_a_manual_no_link_keeps_the_item_unlinked_after_a_sync(self, tn_pg):
        with tn_pg.begin() as conn:
            erp(conn, 10, "7790001", "NB LENOVO V15")
            manual(conn, 10, None)
        sync(tn_pg, [tn_product(1, "Lenovo V15", ["7790001"])])

        with tn_pg.connect() as conn:
            assert links(conn) == {1: None}

    def test_a_partial_fetch_inactivates_nothing(self, tn_pg):
        sync(tn_pg, [tn_product(1, "A", ["1"]), tn_product(2, "B", ["2"])])
        sync(tn_pg, [tn_product(1, "A", ["1"])], complete=False)

        with tn_pg.connect() as conn:
            activos = dict(conn.execute(text("SELECT product_id, activo FROM tienda_nube_productos")).all())
        assert activos == {1: True, 2: True}

    def test_the_stats_count_variants_and_linked_rows(self, tn_pg):
        with tn_pg.begin() as conn:
            erp(conn, 10, "1", "A")
        stats = sync(tn_pg, [tn_product(1, "A", ["1"], description="<p>x</p>"), tn_product(2, "B", ["2"])])

        assert stats == {"productos": 2, "variantes": 2, "activos": 2, "inactivos": 0, "con_erp": 1, "textos": 2}
