"""S5: Productos' "Filtros de Presencia" reach every view of Publicaciones ML through the shared `filter_query`.

The predicates are pinned in `view/test_presence_filters_postgres.py`; this file pins that `/view/items` and
`/view/products` take the same params as `GET /productos` (`con_rebate`, `con_oferta`, `con_web_transf`,
`tn_con_descuento` / `tn_sin_descuento` / `tn_no_publicado`, `out_of_cards`).
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

from datetime import date

import pytest

from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import VER, seed_rows
from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

PRODUCTS_URL = "/api/ml-publications/view/products"


def fill(conn) -> None:
    seed.create_presence_tables(conn)
    seed.add_product(conn, 77, "R77", "Router AX", marca="TP-Link", stock=4)
    seed.add_product(conn, 78, "R78", "Antena", marca="Ubiquiti", stock=2)
    for mla in ("MLA1", "MLA2", "MLA3"):
        seed.add_item(conn, mla, status="active")
    seed.add_link(conn, "MLA1", 77)
    seed.add_link(conn, "MLA2", 78)  # MLA3: no product
    seed.add_pricing(conn, 77, participa_rebate=True, participa_web_transferencia=True, out_of_cards=True)
    seed.add_tn_variant(conn, 78, 1182984711, price=22231, promotional_price=None, activo=True)


@pytest.fixture()
def reader(client, pg, db, rol_admin, admin_auth_headers):
    seed_rows(pg, fill)
    grant(db, rol_admin, VER)
    return admin_auth_headers


def items(client, headers, **params) -> list[str]:
    response = client.get("/api/ml-publications/view/items", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return sorted(row["item_id"] for row in response.json()["items"])


def products(client, headers, **params) -> list[str]:
    response = client.get(PRODUCTS_URL, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return sorted(row["key"] for row in response.json()["rows"])


@pytest.mark.parametrize("param", ["con_rebate", "con_web_transf", "out_of_cards"])
def test_a_product_flag_filters_the_publications_and_the_products(client, reader, param) -> None:
    assert items(client, reader, **{param: "true"}) == ["MLA1"]
    assert items(client, reader, **{param: "false"}) == ["MLA2"]
    assert products(client, reader, **{param: "true"}) == ["77"]
    assert products(client, reader, **{param: "false"}) == ["78"]


def test_tienda_nube_and_mejor_oferta(client, reader) -> None:
    assert items(client, reader, tn_sin_descuento="true") == ["MLA2"]
    assert items(client, reader, tn_no_publicado="true") == ["MLA1"]
    assert products(client, reader, tn_con_descuento="true") == []
    assert items(client, reader, con_oferta="false") == ["MLA1", "MLA2", "MLA3"]


def test_a_toggle_that_is_not_a_boolean_is_a_422(client, reader) -> None:
    response = client.get("/api/ml-publications/view/items", headers=reader, params={"con_rebate": "quizas"})
    assert response.status_code == 422


def test_the_producto_view_asks_mejor_oferta_of_the_product_like_productos(client, pg, reader) -> None:
    """Productos: "con oferta" = ANY publication of the product has a current offer, "sin" = NONE has. A product with
    one MLA on offer and one without is "con" (with both publications) and never "sin"; the publication list stays
    per publication."""

    def more(conn) -> None:
        seed.add_item(conn, "MLA4", status="active")
        seed.add_link(conn, "MLA4", 77)  # 77's second publication, not on offer
        seed.add_oferta(conn, "MLA1", date.today(), date.today(), precio_final=83200, pvp_seller=86486)

    seed_rows(pg, more)
    assert products(client, reader, con_oferta="false") == ["0", "78"]  # "0": the publications with no product
    con = client.get(PRODUCTS_URL, headers=reader, params={"con_oferta": "true"}).json()["rows"]
    assert [(row["key"], row["publications_count"]) for row in con] == [("77", 2)]
    assert items(client, reader, con_oferta="true") == ["MLA1"]
    assert items(client, reader, con_oferta="false") == ["MLA2", "MLA3", "MLA4"]
