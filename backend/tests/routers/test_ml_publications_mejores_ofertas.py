"""`GET /api/ml-publications/view/mejores-ofertas/count`: the top-bar badge that tells each PM how many of THEIR active
publications have better offers. Its count is the Publicaciones ML listing's own total for
`estado=active&hay_mejores_ofertas=1&pms=<the PM's user id>` (the page the badge links to), never a query of its own.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import pg, reader, seed_rows  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

URL = "/api/ml-publications/view/mejores-ofertas/count"
ITEMS = "/api/ml-publications/view/items"

MARCAS_PM_DDL = "CREATE TABLE marcas_pm (id serial PRIMARY KEY, marca text, categoria text, usuario_id integer)"


def _offers(conn, item_id: str, better: bool) -> None:
    conn.execute(
        text("INSERT INTO ml_item_seller_promotions (item_id, hay_mejores_ofertas) VALUES (:i, :b)"),
        {"i": item_id, "b": better},
    )


def _fill(pm_id: int, other_pm_id: int):
    def fill(conn) -> None:
        conn.execute(text(MARCAS_PM_DDL))
        conn.execute(
            text(
                "INSERT INTO marcas_pm (marca, categoria, usuario_id) VALUES ('tp-link', 'redes', :pm), ('xiaomi', 'audio', :other)"
            ),
            {"pm": pm_id, "other": other_pm_id},
        )
        seed.add_product(conn, 70, "A1", "Router", marca="TP-Link", categoria="Redes")
        seed.add_product(conn, 80, "B1", "Parlante", marca="Xiaomi", categoria="Audio")
        # The PM's: active + better offers (counted), active without, paused with
        for item_id, status, better in (("MLA1", "active", True), ("MLA2", "active", False), ("MLA3", "paused", True)):
            seed.add_item(conn, item_id, status=status)
            seed.add_link(conn, item_id, 70)
            _offers(conn, item_id, better)
        # Another PM's active publication with better offers: never the logged-in PM's count
        seed.add_item(conn, "MLA4", status="active")
        seed.add_link(conn, "MLA4", 80)
        _offers(conn, "MLA4", True)

    return fill


def _linked_total(client, headers, pm_id: int) -> int:
    params = {"estado": "active", "hay_mejores_ofertas": "1", "pms": str(pm_id)}
    response = client.get(ITEMS, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["total"]


class TestMejoresOfertasCount:
    def test_authentication_is_required(self, client, pg) -> None:  # noqa: F811
        assert client.get(URL).status_code in (401, 403)

    def test_a_user_without_the_screen_permission_gets_403(self, client, pg, auth_headers) -> None:  # noqa: F811
        assert client.get(URL, headers=auth_headers).status_code == 403

    def test_a_user_who_is_not_a_pm_gets_no_pm_and_zero(self, client, pg, reader, admin_user) -> None:  # noqa: F811
        seed_rows(pg, _fill(admin_user.id + 100, admin_user.id + 200))
        response = client.get(URL, headers=reader)
        assert response.status_code == 200, response.text
        assert response.json() == {"pm_id": None, "count": 0}

    def test_a_pm_counts_only_their_active_publications_with_better_offers(
        self,
        client,
        pg,  # noqa: F811
        reader,  # noqa: F811
        admin_user,
    ) -> None:
        seed_rows(pg, _fill(admin_user.id, admin_user.id + 100))
        response = client.get(URL, headers=reader)
        assert response.status_code == 200, response.text
        assert response.json() == {"pm_id": admin_user.id, "count": 1}

    def test_the_count_equals_the_linked_listing_total(self, client, pg, reader, admin_user) -> None:  # noqa: F811
        seed_rows(pg, _fill(admin_user.id, admin_user.id + 100))
        count = client.get(URL, headers=reader).json()["count"]
        assert count == _linked_total(client, reader, admin_user.id) == 1

    def test_productos_ver_alone_also_reads_the_count(
        self,
        client,
        pg,  # noqa: F811
        db,
        rol_ventas,
        active_user,
        auth_headers,
    ) -> None:
        grant(db, rol_ventas, "productos.ver")
        seed_rows(pg, _fill(active_user.id, active_user.id + 100))
        body = client.get(URL, headers=auth_headers).json()
        assert body == {"pm_id": active_user.id, "count": _linked_total(client, auth_headers, active_user.id)}
