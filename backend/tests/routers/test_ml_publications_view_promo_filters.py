"""P6d: Productos' promo filter (`promo_tipos` + `promo_estado`, or the legacy `con_promo_aplicada` /
`con_promo_sin_aplicar`) and its "Con precios mayoristas" (`con_pxq`) reach every view through the shared
`filter_query`. Both resolve, through the same `select_promo_resolver` Productos uses, to MLA sets read from the
mlwebhook database (patched here); the two sets AND. A resolver that cannot answer is a 503, never the full list.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from app.routers import ml_publications_view
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import VER, seed_rows
from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

ITEMS_URL = "/api/ml-publications/view/items"
PRODUCTS_URL = "/api/ml-publications/view/products"


def fill(conn) -> None:
    seed.create_presence_tables(conn)
    seed.add_product(conn, 77, "R77", "Router AX", marca="TP-Link", stock=4)
    seed.add_product(conn, 78, "R78", "Antena", marca="Ubiquiti", stock=2)
    for mla in ("MLA1", "MLA2", "MLA3"):
        seed.add_item(conn, mla, status="active")
    seed.add_link(conn, "MLA1", 77)
    seed.add_link(conn, "MLA2", 78)


@pytest.fixture()
def calls(monkeypatch) -> list[tuple]:
    seen: list[tuple] = []

    def resolver(name, answer):
        def fetch(*args, **kwargs):
            seen.append((name, args, kwargs))
            return set(answer)

        return fetch

    monkeypatch.setattr(ml_publications_view, "fetch_mlas_with_active_promo_type", resolver("tipo", {"MLA1", "MLA3"}))
    monkeypatch.setattr(ml_publications_view, "fetch_mlas_with_candidate_only_for_types", resolver("sin", {"MLA2"}))
    monkeypatch.setattr(ml_publications_view, "fetch_mlas_with_started", resolver("started", {"MLA2", "MLA3"}))
    monkeypatch.setattr(ml_publications_view, "fetch_mlas_with_candidate_only", resolver("candidate", {"MLA1"}))
    monkeypatch.setattr(ml_publications_view, "fetch_mlas_with_pxq_tiers", resolver("pxq", {"MLA3", "MLA2"}))
    monkeypatch.setattr(ml_publications_view, "fetch_mlas_by_promo_name", resolver("nombre", {"MLA2"}))
    return seen


@pytest.fixture()
def reader(client, pg, db, rol_admin, admin_auth_headers):
    seed_rows(pg, fill)
    grant(db, rol_admin, VER)
    return admin_auth_headers


def items(client, headers, **params) -> list[str]:
    response = client.get(ITEMS_URL, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return sorted(row["item_id"] for row in response.json()["items"])


def test_promo_types_and_state_dispatch_like_productos(client, reader, calls) -> None:
    assert items(client, reader, promo_tipos="DEAL,SMART", promo_estado="aplicada") == ["MLA1", "MLA3"]
    assert calls[-1] == ("tipo", (["DEAL", "SMART"], True), {"mla_ids": None})
    assert items(client, reader, promo_tipos="DEAL", promo_estado="sin_aplicar") == ["MLA2"]
    assert items(client, reader, con_promo_aplicada="true") == ["MLA2", "MLA3"]
    assert items(client, reader, con_promo_sin_aplicar="true") == ["MLA1"]


def test_pxq_ands_with_the_promo_filter_and_reaches_the_products(client, reader, calls) -> None:
    assert items(client, reader, con_pxq="true") == ["MLA2", "MLA3"]
    assert items(client, reader, con_pxq="true", con_promo_aplicada="true") == ["MLA2", "MLA3"]
    assert items(client, reader, con_pxq="true", promo_tipos="DEAL") == ["MLA3"]
    response = client.get(PRODUCTS_URL, headers=reader, params={"con_pxq": "true"})
    assert sorted(row["key"] for row in response.json()["rows"]) == ["0", "78"]  # MLA3 is the no-product row


def test_no_promo_param_asks_nothing(client, reader, calls) -> None:
    assert items(client, reader) == ["MLA1", "MLA2", "MLA3"]
    assert calls == []


def test_an_unknown_type_or_state_is_a_422(client, reader, calls) -> None:
    assert client.get(ITEMS_URL, headers=reader, params={"promo_tipos": "REGALO"}).status_code == 422
    assert client.get(ITEMS_URL, headers=reader, params={"promo_tipos": "DEAL", "promo_estado": "x"}).status_code == 422


def test_a_resolver_that_cannot_answer_is_a_503(client, reader, monkeypatch) -> None:
    def down(*args, **kwargs):
        raise OperationalError("select", {}, Exception("mlwebhook down"))

    monkeypatch.setattr(ml_publications_view, "fetch_mlas_with_pxq_tiers", down)
    response = client.get(ITEMS_URL, headers=reader, params={"con_pxq": "true"})
    assert response.status_code == 503


def test_promo_search_with_a_known_type_reads_its_active_promotions_like_productos(client, reader, calls) -> None:
    assert items(client, reader, q="promo:deal") == ["MLA1", "MLA3"]
    assert calls == [("tipo", (["DEAL"],), {"applied_only": False})]


def test_promo_search_with_any_other_text_reads_the_promotion_name(client, reader, calls) -> None:
    assert items(client, reader, q="promo: Hot Sale") == ["MLA2"]
    assert calls == [("nombre", ("Hot Sale",), {})]


def test_promo_search_ands_with_the_promo_filter(client, reader, calls) -> None:
    assert items(client, reader, q="promo:hot sale", promo_tipos="DEAL") == []  # {MLA2} and {MLA1, MLA3}


def test_promo_search_reaches_the_products_and_finds_none_without_mla(client, reader, calls) -> None:
    response = client.get(PRODUCTS_URL, headers=reader, params={"q": "promo:deal"})
    assert sorted(row["key"] for row in response.json()["rows"]) == ["0", "77"]  # MLA3 is the no-product row
    response = client.get(PRODUCTS_URL, headers=reader, params={"q": "promo:deal", "con_mla": "false"})
    assert response.status_code == 200, response.text
    assert response.json()["rows"] == []  # a product without MLA has no promotion


def test_mla_search_asks_no_resolver(client, reader, calls) -> None:
    assert items(client, reader, q="mla:mla2") == ["MLA2"]
    assert calls == []


@pytest.mark.parametrize(
    ("resolver", "q"),
    [("fetch_mlas_by_promo_name", "promo:hot sale"), ("fetch_mlas_with_active_promo_type", "promo:deal")],
)
def test_a_promo_search_that_cannot_be_resolved_is_a_503(client, reader, monkeypatch, resolver, q) -> None:
    def down(*args, **kwargs):
        raise OperationalError("select", {}, Exception("mlwebhook down"))

    monkeypatch.setattr(ml_publications_view, resolver, down)
    response = client.get(ITEMS_URL, headers=reader, params={"q": q})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "filtro_no_disponible"
