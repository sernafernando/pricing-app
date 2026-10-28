"""P6b: Productos' markup sign filters (`markup_clasica_positivo`, `markup_rebate_positivo`, `markup_oferta_positivo`,
`markup_web_transf_positivo`) reach every view through the shared `filter_query`, and, like every markup of this
screen, only for users with `ml_metricas.ver_ganancia`: a markup sign is a margin figure. The predicates are pinned in
`view/test_presence_filters_postgres.py`.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import GANANCIA, VER, seed_rows
from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

ITEMS_URL = "/api/ml-publications/view/items"
PRODUCT_IDS_URL = "/api/ml-publications/view/product-ids"


def fill(conn) -> None:
    seed.create_presence_tables(conn)
    conn.execute(text(seed.MARKUP_DDL))
    seed.add_product(conn, 77, "R77", "Router AX", marca="TP-Link", stock=4)
    seed.add_product(conn, 78, "R78", "Antena", marca="Ubiquiti", stock=2)
    for mla in ("MLA1", "MLA2"):
        seed.add_item(conn, mla, status="active")
    seed.add_link(conn, "MLA1", 77)
    seed.add_link(conn, "MLA2", 78)
    seed.add_pricing(conn, 77, markup_calculado=15)
    seed.add_pricing(conn, 78, markup_calculado=-5)


@pytest.fixture()
def viewer(client, pg, db, rol_admin, admin_auth_headers):
    seed_rows(pg, fill)
    grant(db, rol_admin, VER)
    return admin_auth_headers


def test_with_ver_ganancia_the_sign_filters_the_publications(client, viewer, db, rol_admin) -> None:
    grant(db, rol_admin, GANANCIA)
    response = client.get(ITEMS_URL, headers=viewer, params={"markup_clasica_positivo": "false"})
    assert response.status_code == 200, response.text
    assert [row["item_id"] for row in response.json()["items"]] == ["MLA2"]


@pytest.mark.parametrize("url", [ITEMS_URL, PRODUCT_IDS_URL])
def test_without_ver_ganancia_a_markup_sign_is_a_403(client, viewer, url) -> None:
    response = client.get(url, headers=viewer, params={"markup_rebate_positivo": "true"})
    assert response.status_code == 403
    assert GANANCIA in response.json()["error"]["message"]


def test_without_ver_ganancia_the_other_filters_still_answer(client, viewer) -> None:
    assert client.get(ITEMS_URL, headers=viewer, params={"con_precio": "true"}).status_code == 200
