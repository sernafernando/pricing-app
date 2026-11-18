"""Markup real 30D c/ SISO on the Producto view and the exports, and the markup c/ SISO's range on Auditoría de stock
(pubml-markup-siso S1, S3, S4). The Producto rows read the Board with its sell in / sell out (`sell_in_out=True`,
margin readers only): `markup_sell_30d` is the Board's `markup_sell` over the summed row, null where neither applies.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
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
from tests.routers.test_ml_publications_view_stock_audit import (  # noqa: F401
    audit,
    auditor,
    board_calls,
    list_markups,
    started,
)
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401

pytestmark = pytest.mark.postgres


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


class TestProductRows:
    def test_with_ver_ganancia_a_product_row_carries_its_markup_with_sell_in_out(
        self, client, sold, db, rol_admin, admin_auth_headers
    ) -> None:
        grant(db, rol_admin, VER, METRICAS, GANANCIA)
        sell_in_on_order(sold, 1, "0.50")

        rows = by_key(body(client, admin_auth_headers)["rows"])

        plain, with_sell = rows["77"]["metrics"]["markup_30d"], rows["77"]["metrics"]["markup_sell_30d"]
        assert with_sell is not None and with_sell > plain  # a sell in lowers the cost: the markup goes up
        assert rows["0"]["metrics"]["markup_sell_30d"] is None  # "Sin producto": neither applies, never a copy

    def test_without_ver_ganancia_there_is_no_markup_with_sell_in_out(
        self, client, sold, db, rol_admin, admin_auth_headers
    ) -> None:
        grant(db, rol_admin, VER, METRICAS)
        rows = body(client, admin_auth_headers)["rows"]
        assert all("markup_sell_30d" not in (row["metrics"] or {}) for row in rows)

    def test_sorting_by_it_puts_the_shown_value_in_order(self, client, sold, db, rol_admin, admin_auth_headers) -> None:
        grant(db, rol_admin, VER, METRICAS, GANANCIA)
        sell_in_on_order(sold, 1, "0.50")

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
        sell_in_on_order(sold, 1, "0.50")
        rows = by_key(body(client, admin_auth_headers)["rows"])

        header, lines = read_csv(client.get(PRODUCTS_CSV, headers=admin_auth_headers))

        by_code = dict(zip(column(header, lines, "Código"), column(header, lines, "Markup real 30D c/ SISO")))
        assert by_code["R77"] == f"{rows['77']['metrics']['markup_sell_30d']:.2f}".replace(".", ",")


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
