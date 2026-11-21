"""Markup real 30D c/ SISO on the Producto view and the exports, and the markup c/ SISO's range on Auditoría de stock
(pubml-markup-siso S1, S3, S4). The Producto rows read the Board with its sell in / sell out (`sell_in_out=True`,
margin readers only): `markup_sell_30d` is (mtg + m_sell_out) / costo over the summed row (`view.real_so`), null
where no sold line has a sell out. D1 (sell-in-costo-si T3 PR 5, owner L12: "SO va en la venta, como ganancia
adicional"): the Board's sell in is never read, so a sell in alone gives no figure and next to a sell out changes
nothing.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models.ml_orders_ops import MlOrderItemOps
from app.models.sell_in import SellInConsumo
from app.services.ml_publications.view import cost_lines, stock_audit
from app.services.ml_publications.view.markup import PublicationMarkup
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import GANANCIA, VER
from tests.routers.test_ml_publications_view_export import PRODUCTS_CSV, column, read_csv
from tests.routers.test_ml_publications_view_kpis import METRICAS, _seller, pg, view_pg  # noqa: F401
from tests.routers.test_ml_publications_view_products import body, by_key, sold  # noqa: F401
from tests.routers.test_ml_publications_view import seed_rows
from tests.routers.test_ml_publications_view_stock_audit import (  # noqa: F401
    PERMISO,
    audit,
    auditor,
    board_calls,
    list_markups,
    no_split,
    sheet,
    started,
)
from tests.routers.test_ml_publications_view_stock_audit_niveles import LENOVO, fill_groups, splits  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.costo_si_lista import costo_si_lista  # noqa: F401 (the costo SI reader's SQLite stand-in)

pytestmark = [pytest.mark.postgres, pytest.mark.usefixtures("costo_si_lista")]


def sell_in_on_order(engine, order_id: int, descuento: str) -> None:
    """A sell in of `descuento` ARS on the (one) line of `order_id`, as the allocator books it (`venta_ref` = the
    line's id, channel 'ml')."""
    session = sessionmaker(bind=engine)()
    line = session.query(MlOrderItemOps).filter(MlOrderItemOps.order_id == order_id).one()
    session.add(
        SellInConsumo(
            compra_item_id=1,
            canal="ml",
            venta_ref=line.id,
            item_id=77,
            fecha_venta=date.today(),
            unidades=1,
            descuento_ars=Decimal(descuento),
        )
    )
    session.commit()
    session.close()


def sell_out_on_order(engine, order_id: int, monto: str) -> None:
    """A sell out of `monto` ARS on the (one) line of `order_id`, as the allocator books it (an ARS campaign, channel
    'ml', `venta_ref` = the line's id)."""
    session = sessionmaker(bind=engine)()
    line = session.query(MlOrderItemOps).filter(MlOrderItemOps.order_id == order_id).one()
    campana = session.execute(
        text(
            "INSERT INTO sell_out_campanas (nombre, fecha_desde, fecha_hasta, tipo, monto_unit, base_porcentaje, "
            "moneda, acumulable, monto_incluye_iva, estado, usuario_id) VALUES ('SO', :d, :d, 'por_unidad', :m, "
            "'costo', 'ARS', true, false, 'activa', 7) RETURNING id"
        ),
        {"d": date.today(), "m": Decimal(monto)},
    ).scalar_one()
    session.execute(
        text(
            "INSERT INTO sell_out_consumos (campana_id, canal, venta_ref, item_id, fecha_venta, unidades, monto) "
            "VALUES (:c, 'ml', :v, 77, :d, 1, :m)"
        ),
        {"c": campana, "v": line.id, "d": date.today(), "m": Decimal(monto)},
    )
    session.commit()
    session.close()


class TestProductRows:
    def test_with_ver_ganancia_a_product_row_carries_its_markup_with_sell_out(
        self, client, sold, db, rol_admin, admin_auth_headers
    ) -> None:
        grant(db, rol_admin, VER, METRICAS, GANANCIA)
        sell_out_on_order(sold, 1, "0.50")

        rows = by_key(body(client, admin_auth_headers)["rows"])

        plain, with_sell = rows["77"]["metrics"]["markup_30d"], rows["77"]["metrics"]["markup_sell_30d"]
        assert with_sell is not None and with_sell > plain  # a sell out adds to the profit: the markup goes up
        assert rows["0"]["metrics"]["markup_sell_30d"] is None  # "Sin producto": no sell out, never a copy

    def test_a_sell_in_next_to_the_sell_out_changes_nothing(
        self, client, sold, db, rol_admin, admin_auth_headers
    ) -> None:
        grant(db, rol_admin, VER, METRICAS, GANANCIA)
        sell_out_on_order(sold, 1, "0.50")
        sin_sell_in = by_key(body(client, admin_auth_headers)["rows"])["77"]["metrics"]["markup_sell_30d"]
        sell_in_on_order(sold, 1, "0.50")

        rows = by_key(body(client, admin_auth_headers)["rows"])

        assert sin_sell_in is not None and rows["77"]["metrics"]["markup_sell_30d"] == sin_sell_in

    def test_a_sell_in_alone_gives_no_markup_with_sell_out(
        self, client, sold, db, rol_admin, admin_auth_headers
    ) -> None:
        grant(db, rol_admin, VER, METRICAS, GANANCIA)
        sell_in_on_order(sold, 1, "0.50")

        rows = by_key(body(client, admin_auth_headers)["rows"])

        assert rows["77"]["metrics"]["markup_30d"] is not None
        assert rows["77"]["metrics"]["markup_sell_30d"] is None  # D1: the sell in never lowers the cost

    def test_without_ver_ganancia_there_is_no_markup_with_sell_in_out(
        self, client, sold, db, rol_admin, admin_auth_headers
    ) -> None:
        grant(db, rol_admin, VER, METRICAS)
        rows = body(client, admin_auth_headers)["rows"]
        assert all("markup_sell_30d" not in (row["metrics"] or {}) for row in rows)

    def test_sorting_by_it_puts_the_shown_value_in_order(self, client, sold, db, rol_admin, admin_auth_headers) -> None:
        grant(db, rol_admin, VER, METRICAS, GANANCIA)
        sell_out_on_order(sold, 1, "0.50")

        found = body(client, admin_auth_headers, orden="markup_sell_30d", dir="desc")["rows"]

        shown = [
            (
                r["metrics"]["markup_sell_30d"]
                if r["metrics"]["markup_sell_30d"] is not None
                else r["metrics"]["markup_30d"]
            )
            for r in found
            if r["metrics"] and r["metrics"]["units_30d"]
        ]
        assert shown == sorted(shown, reverse=True) and found[0]["key"] == "77"

    def test_sorting_by_it_needs_ver_ganancia(self, client, sold, db, rol_admin, admin_auth_headers) -> None:
        grant(db, rol_admin, VER, METRICAS)
        response = client.get(
            "/api/ml-publications/view/products", headers=admin_auth_headers, params={"orden": "markup_sell_30d"}
        )
        assert response.status_code == 403

    def test_the_export_has_the_column_with_ver_ganancia(self, client, sold, db, rol_admin, admin_auth_headers) -> None:
        grant(db, rol_admin, VER, METRICAS, GANANCIA)
        sell_out_on_order(sold, 1, "0.50")
        rows = by_key(body(client, admin_auth_headers)["rows"])

        header, lines = read_csv(client.get(PRODUCTS_CSV, headers=admin_auth_headers))

        by_code = dict(zip(column(header, lines, "Código"), column(header, lines, "Markup real 30D c/ SO")))
        assert by_code["R77"] == f"{rows['77']['metrics']['markup_sell_30d']:.2f}".replace(".", ",")


@pytest.mark.usefixtures("no_split")
class TestAudit:
    @pytest.fixture()
    def siso_ten_up(self, monkeypatch) -> None:
        """Every publication's markup c/ SISO, 10 points above its plain markup (`list_markups`' ranges)."""

        def fake(pricing_db, items):
            return {
                mla: cost_lines.SisoMarkup(
                    PublicationMarkup((), m.markup.value_min + 10, m.markup.value_max + 10, None, False, 0, ""), 0, True
                )
                for mla, m in items.items()
            }

        monkeypatch.setattr(stock_audit, "siso_markups", fake)

    def test_a_row_carries_the_range_of_its_publications_markup_with_sell_in_out(
        self, client, auditor, db, rol_admin, board_calls, list_markups, siso_ten_up
    ) -> None:
        grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
        rows = {row["product_item_id"]: row for row in audit(client, auditor)["rows"]}
        assert rows[100]["markup_siso"] == {"min": 26.0, "max": 32.0}  # its own and its variant's, as Actual
        assert rows[100]["variantes"][0]["markup_siso"] == {"min": 32.0, "max": 32.0}
        assert rows[111]["markup_siso"] == {"min": 40.0, "max": 40.0}
        assert rows[130]["markup_siso"] is None and rows[140]["markup_siso"] is None

    def test_sorting_by_it_orders_by_the_low_end(
        self, client, auditor, db, rol_admin, board_calls, list_markups, siso_ten_up
    ) -> None:
        grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
        rows = audit(client, auditor, orden="markup_siso", dir="asc")["rows"]
        lows = [row["markup_siso"]["min"] for row in rows if row["markup_siso"] is not None]
        assert lows == sorted(lows) and rows[0]["product_item_id"] == 100

    def test_without_ver_ganancia_a_row_has_no_markup_with_sell_in_out(
        self, client, auditor, db, rol_admin, board_calls, list_markups
    ) -> None:
        grant(db, rol_admin, "ml_metricas.ver")
        rows = audit(client, auditor)["rows"]
        assert all("markup_siso" not in row for row in rows)
        assert all("markup_siso" not in v for row in rows for v in row["variantes"])


@pytest.mark.postgres
class TestAuditLevels:
    """pubml-markup-siso S4 on the Marca and Categoría levels (#2343): a brand's or a category's markup c/ SISO is the
    range of its products' ranges, the rule its plain `markup_actual` follows (no average)."""

    @pytest.fixture()
    def margin_groups(self, client, pg, db, rol_admin, admin_auth_headers, started, splits, list_markups, monkeypatch):
        seed_rows(pg, fill_groups)
        grant(db, rol_admin, PERMISO, "ml_metricas.ver", "ml_metricas.ver_ganancia")

        def fake(pricing_db, items):  # 10 points above the plain markup, MLA11's low end 5 points below it
            return {
                mla: cost_lines.SisoMarkup(
                    PublicationMarkup(
                        (),
                        m.markup.value_min + (-5 if mla == "MLA11" else 10),
                        m.markup.value_max + 10,
                        None,
                        False,
                        0,
                        "",
                    ),
                    0,
                    True,
                )
                for mla, m in items.items()
            }

        monkeypatch.setattr(stock_audit, "siso_markups", fake)
        return admin_auth_headers

    @staticmethod
    def span(rows: list[dict]) -> Optional[dict]:
        ranges = [r["markup_siso"] for r in rows if r.get("markup_siso")]
        if not ranges:
            return None
        return {"min": min(r["min"] for r in ranges), "max": max(r["max"] for r in ranges)}

    def test_a_brand_and_its_categories_carry_the_range_of_their_products(self, client, margin_groups) -> None:
        brands = by_level_key(audit(client, margin_groups, nivel="marca"))
        lenovo = brands["marca:LENOVO"]
        products = audit(client, margin_groups, nivel="producto", grupo_marca=LENOVO)["rows"]
        # notebook 100 (MLA10, MLA11 and its variant's MLA12): MLA11's low end 16 - 5, MLA12's 22 + 10
        assert lenovo["markup_siso"] == self.span(products) == {"min": 11.0, "max": 32.0}
        assert brands["marca:LOGI"]["markup_siso"] == {"min": 40.0, "max": 40.0}  # the pack's MLA20
        for category in lenovo["categorias"]:
            drilled = audit(
                client,
                margin_groups,
                nivel="producto",
                grupo_marca=LENOVO,
                grupo_categoria=category["grupo"]["categoria"],
            )["rows"]
            assert category["markup_siso"] == self.span(drilled), category["key"]

    def test_the_categoria_level_too(self, client, margin_groups) -> None:
        for row in audit(client, margin_groups, nivel="categoria")["rows"]:
            drilled = audit(client, margin_groups, nivel="producto", grupo_categoria=row["grupo"]["categoria"])["rows"]
            assert row["markup_siso"] == self.span(drilled), row["key"]

    def test_the_export_carries_it_on_the_brand_and_category_lines(self, client, margin_groups) -> None:
        lines = sheet(client, margin_groups, nivel="marca", orden="valor_total", dir="desc")
        lenovo = next(line for line in lines if (line["Tipo"], line["Producto"]) == ("Marca", "Lenovo"))
        notebooks = next(line for line in lines if (line["Tipo"], line["Producto"]) == ("Categoría", "Notebooks"))
        siso = ("Markup actual c/ SO mín", "Markup actual c/ SO máx")
        assert tuple(lenovo[h] for h in siso) == (11.0, 32.0)  # the brand's range, as the screen shows it
        assert tuple(notebooks[h] for h in siso) == (11.0, 32.0)

    def test_the_brands_sort_by_it(self, client, margin_groups) -> None:
        rows = audit(client, margin_groups, nivel="marca", orden="markup_siso", dir="asc")["rows"]
        lows = [r["markup_siso"]["min"] for r in rows if r["markup_siso"] is not None]
        assert lows == sorted(lows) and len(lows) == 2

    def test_without_ver_ganancia_no_group_has_it(self, client, pg, db, rol_admin, admin_auth_headers, started, splits):
        seed_rows(pg, fill_groups)
        grant(db, rol_admin, PERMISO, "ml_metricas.ver")
        rows = audit(client, admin_auth_headers, nivel="marca")["rows"]
        assert all("markup_siso" not in r for r in rows)
        assert all("markup_siso" not in c for r in rows for c in r.get("categorias") or [])


def by_level_key(body: dict) -> dict[str, dict]:
    return {row["key"]: row for row in body["rows"]}
