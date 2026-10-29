"""The PPP and sell in lines under the Costo of a publication row (`GET /api/ml-publications/view/items`, detail).

Productos draws two companion lines under its cost: the PPP (the ERP's weighted-average cost) and the cost with sell
in. The publication rows carry the same payloads Productos builds (`resolver_ppp_batch` + `PppMarkups`,
`resolver_sell_in_out_batch`), next to `costo` and only with `ml_metricas.ver_ganancia`. Both resolvers read the
pricing database. Same harness as `test_ml_publications_view_markup.py`.
"""

# ruff: noqa: F811 -- the fixtures are imported from the markup test module and used by name

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.models.item_cost_list_history import ItemCostListHistory
from app.models.producto import ProductoERP
from app.models.sell_in import SellInCompra, SellInCompraItem
from tests.routers.test_ml_publications_view import get, seed_rows
from tests.routers.test_ml_publications_view_markup import (  # noqa: F401
    analyst,
    fill,
    pg,
    pricing,
    reader,
    view_pg,
)
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401

pytestmark = pytest.mark.postgres

DETAIL = "/api/ml-publications/view/items/{}"


def seed_lines(db, user, item_id: int, costo: float, ppp: float = 850.0, descuento: str = "200.00") -> int:
    """In the pricing database: a PPP row of `item_id` and a purchase with `descuento` ARS of sell in over 2 units."""
    if db.get(ProductoERP, item_id) is None:
        db.add(ProductoERP(item_id=item_id, codigo=f"C{item_id}", costo=costo, moneda_costo="ARS", iva=21.0))
    db.add(
        ItemCostListHistory(
            iclh_id=90000 + item_id,
            coslis_id=1,
            item_id=item_id,
            iclh_price=ppp,
            iclh_price_aw=ppp,
            curr_id=1,
            iclh_cd=datetime(2026, 2, 14),
        )
    )
    compra = SellInCompra(
        fecha_compra=date(2020, 1, 1), moneda="ARS", monto_total=descuento, estado="activa", usuario_id=user.id
    )
    db.add(compra)
    db.flush()
    linea = SellInCompraItem(
        compra_id=compra.id, item_id=item_id, cantidad=2, costo_base_unit=1000, monto_asignado=descuento
    )
    db.add(linea)
    db.commit()
    return linea.id


def expected_lines(linea: int, costo: float, ppp: float = 850.0) -> dict:
    return {
        "ppp": {"costo": ppp, "moneda": "ARS", "fecha": "2026-02-14", "markups": {}},
        "sell_in_out": {
            "sell_in": {
                "compra_item_id": linea,
                "bono_id": None,  # a FIFO lot (T25: a cost bonus fills it)
                "descuento_unit": 100.0,
                "costo": costo - 100.0,
                "unidades_restantes": 2,
            },
            "sell_out": None,
            "markups_sell_in": {},
            "markups_sell_in_out": {},
        },
    }


class TestListRow:
    def test_with_ver_ganancia_a_row_carries_the_ppp_and_sell_in_of_its_product(
        self, client, pg, analyst, pricing, db, admin_user
    ) -> None:
        seed_rows(pg, fill)
        linea = seed_lines(db, admin_user, 70, 40000.0)

        rows = {row["item_id"]: row for row in get(client, analyst).json()["items"]}

        assert {k: rows["MLA1"][k] for k in ("ppp", "sell_in_out")} == expected_lines(linea, 40000.0)
        assert rows["MLA1"]["costo"] == {"amount": 40000.0, "currency": "ARS"}  # the cost stays as it was
        assert rows["MLA3"]["ppp"] is None and rows["MLA3"]["sell_in_out"] is None  # no product

    def test_a_product_with_no_ppp_row_and_no_sell_in_carries_both_lines_as_null(
        self, client, pg, analyst, pricing, db, admin_user
    ) -> None:
        seed_rows(pg, fill)
        seed_lines(db, admin_user, 70, 40000.0)  # only product 70 has a PPP row and a sell in

        rows = {row["item_id"]: row for row in get(client, analyst).json()["items"]}

        assert rows["MLA2"]["costo"] is not None  # a linked product with a cost: the frontend reads "sin PPP"
        assert rows["MLA2"]["ppp"] is None and rows["MLA2"]["sell_in_out"] is None

    def test_without_ver_ganancia_neither_key_is_present(self, client, pg, reader, pricing, db, admin_user) -> None:
        seed_rows(pg, fill)
        seed_lines(db, admin_user, 70, 40000.0)

        items = get(client, reader).json()["items"]

        assert all("ppp" not in row and "sell_in_out" not in row for row in items)


class TestDetailRow:
    def test_the_detail_row_carries_the_same_lines(self, client, pg, analyst, pricing, db, admin_user) -> None:
        seed_rows(pg, fill)
        linea = seed_lines(db, admin_user, 70, 40000.0)

        response = client.get(DETAIL.format("MLA1"), headers=analyst)

        assert response.status_code == 200, response.text
        row = response.json()["row"]
        assert {k: row[k] for k in ("ppp", "sell_in_out")} == expected_lines(linea, 40000.0)


# A failing PPP, sell in or exchange-rate read: the list answers as before the lines existed (each row with its cost,
# no line keys) and logs the failure; it never turns the whole page into a 500.
FALLAS = ["resolver_ppp_batch", "resolver_sell_in_out_batch", "obtener_tipo_cambio_actual"]


def falla(monkeypatch, nombre: str) -> None:
    """Makes one of the reads behind the cost lines raise, as a database error would."""
    from sqlalchemy.exc import OperationalError

    from app.services.ml_publications.view import cost_lines as module

    def roto(*args, **kwargs):
        raise OperationalError("SELECT", {}, Exception(f"{nombre} down"))

    monkeypatch.setattr(module, nombre, roto)


class TestAFailingLineRead:
    @pytest.mark.parametrize("nombre", FALLAS)
    def test_the_list_keeps_each_cost_without_the_lines(
        self, client, pg, analyst, pricing, db, admin_user, monkeypatch, caplog, nombre
    ) -> None:
        seed_rows(pg, fill)
        seed_lines(db, admin_user, 70, 40000.0)
        falla(monkeypatch, nombre)

        with caplog.at_level("ERROR"):
            response = get(client, analyst)

        assert response.status_code == 200, response.text
        rows = {row["item_id"]: row for row in response.json()["items"]}
        assert rows["MLA1"]["costo"] == {"amount": 40000.0, "currency": "ARS"}
        assert all("ppp" not in row and "sell_in_out" not in row for row in rows.values())
        assert any(r.exc_info and f"{nombre} down" in str(r.exc_info[1]) for r in caplog.records)

    def test_the_detail_keeps_its_cost_without_the_lines(
        self, client, pg, analyst, pricing, db, admin_user, monkeypatch
    ) -> None:
        seed_rows(pg, fill)
        seed_lines(db, admin_user, 70, 40000.0)
        falla(monkeypatch, "resolver_ppp_batch")

        response = client.get(DETAIL.format("MLA1"), headers=analyst)

        assert response.status_code == 200, response.text
        row = response.json()["row"]
        assert row["costo"] == {"amount": 40000.0, "currency": "ARS"}
        assert "ppp" not in row and "sell_in_out" not in row
