"""Auditoría de stock S9: every publication row says whether it has an applied promotion (`promo_aplicada`, a
started one, read from the mlwebhook database for the page's MLAs only), and the Con / Sin promo aplicada filter
(`promo_aplicada=con|sin`) reaches every view through the shared `filter_query`. "Sin" means no started promotion,
even when the publication has candidates. It ANDs with Productos' promo filter (`promo_estado`), which keeps
working as before. The mlwebhook readers are patched, as in the promo filter tests.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from app.routers import ml_publications_view
from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401
from tests.routers.test_ml_publications_view_promo_filters import (  # noqa: F401
    ITEMS_URL,
    PRODUCTS_URL,
    calls,
    items,
    reader,
)
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401

pytestmark = pytest.mark.postgres

# The promo filter tests' world: MLA1 -> product 77, MLA2 -> 78, MLA3 no product. Started: MLA2, MLA3.
# Candidate only: MLA1.


def test_con_lists_the_publications_with_a_started_promotion(client, reader, calls) -> None:
    assert items(client, reader, promo_aplicada="con") == ["MLA2", "MLA3"]


def test_sin_lists_the_ones_without_a_started_promotion_even_with_candidates(client, reader, calls) -> None:
    assert items(client, reader, promo_aplicada="sin") == ["MLA1"]  # MLA1 has a candidate, none started


def test_it_ands_with_productos_promo_filter_which_keeps_working(client, reader, calls) -> None:
    assert items(client, reader, promo_tipos="DEAL", promo_estado="disponible") == ["MLA1", "MLA3"]
    assert items(client, reader, promo_tipos="DEAL", promo_estado="disponible", promo_aplicada="sin") == ["MLA1"]
    assert items(client, reader, promo_tipos="DEAL", promo_estado="disponible", promo_aplicada="con") == ["MLA3"]
    assert items(client, reader, con_promo_sin_aplicar="true", promo_aplicada="con") == []


def test_it_reaches_the_products_view(client, reader, calls) -> None:
    response = client.get(PRODUCTS_URL, headers=reader, params={"promo_aplicada": "sin"})
    assert response.status_code == 200, response.text
    assert [row["key"] for row in response.json()["rows"]] == ["77"]


def test_an_unknown_value_is_a_422_naming_the_parameter(client, reader, calls) -> None:
    response = client.get(ITEMS_URL, headers=reader, params={"promo_aplicada": "si"})
    assert response.status_code == 422
    assert "promo_aplicada" in response.text


def test_a_filter_that_cannot_be_resolved_is_a_503(client, reader, monkeypatch) -> None:
    def down(*args, **kwargs):
        raise OperationalError("select", {}, Exception("mlwebhook down"))

    monkeypatch.setattr(ml_publications_view, "fetch_mlas_with_started", down)
    assert client.get(ITEMS_URL, headers=reader, params={"promo_aplicada": "sin"}).status_code == 503


def test_every_row_carries_the_badge_read_for_the_page_mlas_only(client, reader, calls) -> None:
    response = client.get(ITEMS_URL, headers=reader)
    assert response.status_code == 200, response.text
    badge = {row["item_id"]: row["promo_aplicada"] for row in response.json()["items"]}
    assert badge == {"MLA1": False, "MLA2": True, "MLA3": True}
    assert calls == [("started", (), {"mla_ids": ["MLA1", "MLA2", "MLA3"]})]  # bounded, never the whole account


def test_without_the_promo_database_the_list_answers_without_a_badge(client, reader, monkeypatch) -> None:
    def down(*args, **kwargs):
        raise OperationalError("select", {}, Exception("mlwebhook down"))

    monkeypatch.setattr(ml_publications_view, "fetch_mlas_with_started", down)
    response = client.get(ITEMS_URL, headers=reader)
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    assert len(rows) == 3 and all("promo_aplicada" not in row for row in rows)  # unknown, never a false "Sin"


def test_an_empty_page_never_reads_the_whole_account(client, reader, calls) -> None:
    assert items(client, reader, q="MLA999") == []
    assert all(call[0] != "started" for call in calls)


def test_the_facets_promo_axis_counts_without_its_own_selection(client, reader, calls) -> None:
    response = client.get(ITEMS_URL, headers=reader, params={"promo_aplicada": "sin", "facets": "true"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["facets"]["promo"] == {"con_promo": 2, "sin_promo": 1}
