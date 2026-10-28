"""S12d4: `GET /api/ml-publications/view/stats`, Productos' stat cards over the screen's filters.

The counts are pinned in `view/test_stats_postgres.py`; this file pins the HTTP surface: the cards need `ml_ops.ver`
(the list's permission), the markup cards `ml_metricas.ver_ganancia` (as every markup of this screen), the filters
are the shared `filter_query`, and a slow count is the screen's controlled 503.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

import pytest
from sqlalchemy import func, text

from app.services.ml_publications.view import listing, stats as stats_service, status_block
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import GANANCIA, VER, seed_rows
from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

URL = "/api/ml-publications/view/stats"
MARKUP_CARDS = set(stats_service.MARKUP_COLUMNS)


def fill(conn) -> None:
    seed.create_presence_tables(conn)
    conn.execute(text(seed.MARKUP_DDL))
    seed.add_product(conn, 77, "R77", "Router AX", marca="TP-Link", stock=4)
    seed.add_product(conn, 78, "R78", "Antena", marca="Ubiquiti", stock=0)
    for mla in ("MLA1", "MLA2", "MLA3"):
        seed.add_item(conn, mla, status="active")
    seed.add_link(conn, "MLA1", 77)
    seed.add_link(conn, "MLA2", 78)  # MLA3: no product
    seed.add_pricing(conn, 77, precio_lista_ml=1000, markup_calculado=15)
    seed.add_pricing(conn, 78, markup_calculado=-5)


@pytest.fixture()
def viewer(client, pg, db, rol_admin, admin_auth_headers):
    seed_rows(pg, fill)
    grant(db, rol_admin, VER)
    return admin_auth_headers


def get(client, headers, **params):
    return client.get(URL, headers=headers, params=params)


def test_authentication_is_required(client, pg) -> None:
    assert client.get(URL).status_code in (401, 403)


def test_a_user_without_ml_ops_ver_gets_403(client, pg, db, rol_ventas, auth_headers) -> None:
    grant(db, rol_ventas, GANANCIA)
    response = get(client, auth_headers)
    assert response.status_code == 403 and VER in response.json()["error"]["message"]


def test_the_cards_count_the_linked_products_without_the_markup_ones(client, viewer) -> None:
    response = get(client, viewer)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["can_see_margin"] is False
    assert MARKUP_CARDS.isdisjoint(body["stats"])
    assert body["stats"] == {
        "total": 2,
        "con_stock": 1,
        "con_precio": 1,
        "con_stock_sin_precio": 0,
        "nuevos": 2,
        "nuevos_sin_precio": 1,
        "oferta_sin_rebate": 0,
    }


def test_with_ver_ganancia_the_markup_cards_come_too(client, viewer, db, rol_admin) -> None:
    grant(db, rol_admin, GANANCIA)
    body = get(client, viewer).json()
    assert body["can_see_margin"] is True
    assert body["stats"]["markup_negativo_clasica"] == 1  # 78
    assert MARKUP_CARDS <= set(body["stats"])


def test_the_screens_filters_apply(client, viewer) -> None:
    assert get(client, viewer, marcas="Ubiquiti").json()["stats"]["total"] == 1


def test_a_value_outside_a_filter_vocabulary_is_422_naming_it(client, viewer) -> None:
    response = get(client, viewer, estado="bogus")
    assert response.status_code == 422 and response.json()["error"]["field"] == "estado"


def test_a_statement_timeout_is_a_controlled_503(client, viewer, pg, monkeypatch) -> None:
    real = stats_service.build_base_select

    def slow(f, *columns, **kwargs):
        return real(f, *columns, **kwargs).where(func.pg_sleep(1).is_not(None))

    monkeypatch.setattr(listing, "STATEMENT_TIMEOUT", "50ms")
    monkeypatch.setattr(stats_service, "build_base_select", slow)
    response = get(client, viewer)
    assert response.status_code == 503 and response.json()["error"]["code"] == "consulta_lenta"
    assert pg.pool.checkedout() == 0
    status_block.REPORT.reset()
