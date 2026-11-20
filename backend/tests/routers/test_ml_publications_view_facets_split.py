"""pubml-lentitud T2: the facets in their own request, next to the rows (the rows paint without waiting for them).

L4 (owner): "que los datos no sean mentira" -- `GET /view/facets` answers exactly the counts `GET /view/items?facets=true`
answers for the same filter (every axis, the "Todos" totals, the promo axis, the product options); only the list's own
`total` stays the items' answer, the one number both requests already share.
"""

# ruff: noqa: F811 -- the router fixtures are imported and used by name

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.routers import ml_publications_view
from app.services.ml_publications.view import listing
from tests.routers.test_ml_publications_view import (  # noqa: F401
    VER,
    TestContract,
    mlpub_pg,
    pg,
    reader,
    seed_rows,
)
from tests.services.ml_publications.view import seed

ITEMS = "/api/ml-publications/view/items"
FACETS = "/api/ml-publications/view/facets"


def fill(conn) -> None:
    TestContract().fill(conn)
    seed.add_product(conn, 71, "7790002", "Switch 8p", marca="TP-Link", categoria="Redes")
    seed.add_product(conn, 72, "7790003", "Mouse", marca="Logitech", categoria="Perifericos")
    conn.execute(text("INSERT INTO ml_tiendas_oficiales (store_id, nombre) VALUES (57997, 'Gauss')"))
    for mla, product, status, store, qty in (
        ("MLA3", 71, "active", 57997, 0),
        ("MLA4", 71, "paused", 2645, 2),
        ("MLA5", 72, "active", 57997, 5),
        ("MLA6", 72, "closed", None, 0),
    ):
        seed.add_item(
            conn, mla, title=f"Pub {mla}", status=status, official_store_id=store, price=500, available_quantity=qty
        )
        seed.add_link(conn, mla, product)


FILTERS = (
    {},
    {"estado": "active"},
    {"estado": "paused"},
    {"tiendas": "2645"},
    {"marcas": "TP-LINK"},
    {"q": "Pub"},
    {"estado": "active", "tiendas": "57997"},
    {"con_promo_aplicada": "true"},
)


@pytest.fixture()
def world(pg, monkeypatch):
    seed_rows(pg, fill)
    monkeypatch.setattr(ml_publications_view, "fetch_mlas_with_started", lambda mla_ids=None: {"MLA1", "MLA5"})
    return pg


@pytest.mark.parametrize("params", FILTERS, ids=lambda p: "&".join(f"{k}={v}" for k, v in p.items()) or "none")
def test_the_facets_request_counts_what_the_combined_request_counts(client, world, reader, params) -> None:
    combined = client.get(ITEMS, headers=reader, params={**params, "facets": "true"})
    alone = client.get(FACETS, headers=reader, params=params)
    assert combined.status_code == 200, combined.text
    assert alone.status_code == 200, alone.text
    expected = {k: v for k, v in combined.json()["facets"].items() if k != "total"}
    assert alone.json() == expected


@pytest.mark.parametrize("params", FILTERS[:4], ids=lambda p: "&".join(f"{k}={v}" for k, v in p.items()) or "none")
def test_the_rows_without_facets_are_the_rows_with_them(client, world, reader, params) -> None:
    combined = client.get(ITEMS, headers=reader, params={**params, "facets": "true"}).json()
    rows = client.get(ITEMS, headers=reader, params=params).json()
    assert rows["items"] == combined["items"]
    assert rows["total"] == combined["total"]
    assert "facets" not in rows


def test_the_facets_request_reads_no_row(client, world, reader, monkeypatch) -> None:
    # the point of the split: the counts never wait on (nor pay for) the page's rows
    monkeypatch.setattr(listing, "list_items", lambda *a, **k: pytest.fail("the facets request listed rows"))
    assert client.get(FACETS, headers=reader, params={"estado": "active"}).status_code == 200


def test_the_facets_request_needs_the_screens_permission(client, world, auth_headers) -> None:
    assert client.get(FACETS, headers=auth_headers).status_code == 403


def test_a_bad_filter_is_a_422_as_in_the_items_request(client, world, reader) -> None:
    assert client.get(FACETS, headers=reader, params={"evento": "nope"}).status_code == 422
