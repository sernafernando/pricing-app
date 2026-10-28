"""S5: Productos' "Filtros de Presencia" reach every view of Publicaciones ML through the shared `filter_query`.

The predicates are pinned in `view/test_presence_filters_postgres.py`; this file pins that `/view/items` and
`/view/products` take the same params as `GET /productos` (`con_rebate`, `con_oferta`, `con_web_transf`,
`tn_con_descuento` / `tn_sin_descuento` / `tn_no_publicado`, `out_of_cards`).
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import VER, seed_rows
from tests.routers.test_ml_publications_view_kpis import METRICAS, pg, view_pg  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

PRODUCTS_URL = "/api/ml-publications/view/products"
ITEMS_URL = "/api/ml-publications/view/items"
KPIS_URL = "/api/ml-publications/view/kpis"
# A current offer: wide enough that the process date (Python) and the database's `current_date` agree on it even
# when they straddle midnight (UTC vs UTC-3).
CURRENT = (date.today() - timedelta(days=5), date.today() + timedelta(days=5))


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


def more(conn) -> None:
    seed.add_item(conn, "MLA4", status="active")
    seed.add_link(conn, "MLA4", 77)  # 77's second publication, not on offer
    seed.add_oferta(conn, "MLA1", *CURRENT, precio_final=83200, pvp_seller=86486)


@pytest.fixture()
def mixed(client, pg, reader):
    """77 has one publication on offer (MLA1) and one without (MLA4); 78 has MLA2; MLA3 has no product."""
    seed_rows(pg, more)
    return reader


def test_the_producto_view_asks_mejor_oferta_of_the_product_like_productos(client, mixed) -> None:
    """Productos: "con oferta" = ANY publication of the product has a current offer, "sin" = NONE has. A product with
    one MLA on offer and one without is "con" (with both publications) and never "sin"; the publication list stays
    per publication."""
    assert products(client, mixed, con_oferta="false") == ["0", "78"]  # "0": the publications with no product
    con = client.get(PRODUCTS_URL, headers=mixed, params={"con_oferta": "true"}).json()["rows"]
    assert [(row["key"], row["publications_count"]) for row in con] == [("77", 2)]
    assert items(client, mixed, con_oferta="true") == ["MLA1"]
    assert items(client, mixed, con_oferta="false") == ["MLA2", "MLA3", "MLA4"]


TOGGLES = [
    {"con_rebate": "true"},
    {"con_rebate": "false"},
    {"con_web_transf": "true"},
    {"con_web_transf": "false"},
    {"out_of_cards": "true"},
    {"out_of_cards": "false"},
    {"con_oferta": "true"},
    {"con_oferta": "false"},
    {"tn_con_descuento": "true"},
    {"tn_sin_descuento": "true"},
    {"tn_no_publicado": "true"},
]


@pytest.mark.parametrize("toggle", TOGGLES, ids=lambda t: "=".join(*t.items()))
def test_a_product_row_opens_into_exactly_its_publications_under_every_toggle(client, mixed, db, rol_admin, toggle):
    """`ProductRowOut`: a row's `params`, over the same filters, select exactly its `publications_count` publications
    in `/items`; and the KPI strip the Producto view asks counts the publications the product rows hold."""
    grant(db, rol_admin, METRICAS)
    response = client.get(PRODUCTS_URL, headers=mixed, params=toggle)
    assert response.status_code == 200, response.text
    page = response.json()
    for row in page["rows"]:
        opened = client.get(ITEMS_URL, headers=mixed, params={**toggle, **row["params"]})
        assert opened.status_code == 200, opened.text
        assert opened.json()["total"] == row["publications_count"], row["key"]
    # what the page asks in the Producto view (`buildKpiParams`): the offer of the product, as the rows ask it
    kpi_params = {**toggle, "oferta_por_producto": "true"} if "con_oferta" in toggle else toggle
    kpis = client.get(KPIS_URL, headers=mixed, params=kpi_params)
    assert kpis.status_code == 200, kpis.text
    assert kpis.json()["mla_count"] == page["mla_count"]


def test_the_audit_filter_reaches_the_view_and_a_bad_date_is_a_422(client, reader, pg) -> None:
    with pg.begin() as conn:
        seed.create_audit_tables(conn)
        ana = seed.add_user(conn, "Ana", "ana")
        seed.add_auditoria(
            conn, "ACTIVAR_REBATE", {}, datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc), ana, item_id=78
        )
    assert items(client, reader, audit_tipos_accion="activar_rebate") == ["MLA2"]
    assert products(client, reader, audit_usuarios=str(ana)) == ["78"]
    response = client.get(ITEMS_URL, headers=reader, params={"audit_fecha_desde": "ayer"})
    assert response.status_code == 422


def fill_paused(conn) -> None:
    fill(conn)
    seed.add_item(conn, "MLA4", status="paused")
    seed.add_link(conn, "MLA4", 78)  # 78: MLA2 active, MLA4 paused -- not "Pausadas"
    seed.add_product(conn, 79, "R79", "Switch", marca="TP-Link", stock=1)
    seed.add_item(conn, "MLA5", status="paused")
    seed.add_link(conn, "MLA5", 79)


def test_estado_mla_filters_the_publications_and_the_products(client, pg, db, rol_admin, admin_auth_headers):
    seed_rows(pg, fill_paused)
    grant(db, rol_admin, VER)
    assert items(client, admin_auth_headers, estado_mla="pausada") == ["MLA5"]
    assert products(client, admin_auth_headers, estado_mla="pausada") == ["79"]
    assert items(client, admin_auth_headers, estado_mla="activa") == ["MLA1", "MLA2", "MLA4"]
    assert products(client, admin_auth_headers, estado_mla="activa") == ["77", "78"]


@pytest.mark.parametrize("value", ["inactiva", "paused", "activa,pausada"])
def test_estado_mla_refuses_any_other_value(client, reader, value) -> None:
    response = client.get(ITEMS_URL, headers=reader, params={"estado_mla": value})
    assert response.status_code == 422, response.text
