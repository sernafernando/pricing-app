"""`GET /api/ml-publications/view/mejores-ofertas/count`: the top-bar badge that tells each PM how many of THEIR active
publications have better offers. Its count is the Publicaciones ML listing's own total for
`estado=active&hay_mejores_ofertas=1&pms=<the PM's user id>&tiendas=<main store>` (the page the badge links to), never a
query of its own. Only the main store counts: other stores' publications (e.g. TP-Link's) take no promos.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, text

from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import pg, reader, seed_rows  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

MAIN_STORE = 57997
OTHER_STORE = 2645

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
        # The PM's: active + better offers (counted), active without, paused with, and active with better offers
        # in another store (promos do not apply there: never counted)
        for item_id, status, better, store in (
            ("MLA1", "active", True, MAIN_STORE),
            ("MLA2", "active", False, MAIN_STORE),
            ("MLA3", "paused", True, MAIN_STORE),
            ("MLA6", "active", True, OTHER_STORE),
        ):
            seed.add_item(conn, item_id, status=status, official_store_id=store)
            seed.add_link(conn, item_id, 70)
            _offers(conn, item_id, better)
        # Another PM's active publication with better offers: never the logged-in PM's count
        seed.add_item(conn, "MLA4", status="active", official_store_id=MAIN_STORE)
        seed.add_link(conn, "MLA4", 80)
        _offers(conn, "MLA4", True)

    return fill


def _linked_total(client, headers, pm_id: int, tiendas: str | None = str(MAIN_STORE)) -> int:
    params = {"estado": "active", "hay_mejores_ofertas": "1", "pms": str(pm_id)}
    if tiendas is not None:
        params["tiendas"] = tiendas
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
        assert response.json() == {"pm_id": None, "count": 0, "tienda_id": MAIN_STORE}

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
        assert response.json() == {"pm_id": admin_user.id, "count": 1, "tienda_id": MAIN_STORE}

    def test_the_count_equals_the_linked_listing_total(self, client, pg, reader, admin_user) -> None:  # noqa: F811
        seed_rows(pg, _fill(admin_user.id, admin_user.id + 100))
        body = client.get(URL, headers=reader).json()
        assert body["count"] == _linked_total(client, reader, admin_user.id, str(body["tienda_id"])) == 1

    def test_another_stores_publication_is_out_of_the_count_and_the_linked_list(
        self,
        client,
        pg,  # noqa: F811
        reader,  # noqa: F811
        admin_user,
    ) -> None:
        seed_rows(pg, _fill(admin_user.id, admin_user.id + 100))
        count = client.get(URL, headers=reader).json()["count"]
        params = {"estado": "active", "hay_mejores_ofertas": "1", "pms": str(admin_user.id), "tiendas": str(MAIN_STORE)}
        listed = [row["item_id"] for row in client.get(ITEMS, headers=reader, params=params).json()["items"]]
        assert count == len(listed) == 1
        assert "MLA6" not in listed
        assert _linked_total(client, reader, admin_user.id, tiendas=None) == 2  # without the store, MLA6 shows up

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
        assert body == {
            "pm_id": active_user.id,
            "count": _linked_total(client, auth_headers, active_user.id),
            "tienda_id": MAIN_STORE,
        }


POR_PM = "/api/ml-publications/view/mejores-ofertas/por-pm"
PERMISO_PMS = "alertas.ver_mejores_ofertas_pms"


def _fill_two_pms(first_pm: int, second_pm: int, inactive_pm: int):
    """`first_pm` owns TP-Link/Redes (1 counted), `second_pm` Xiaomi/Audio (2 counted), `inactive_pm` an inactive
    user's pair and an id with no user at all (never listed)."""

    def fill(conn) -> None:
        _fill(first_pm, second_pm)(conn)
        seed.add_item(conn, "MLA5", status="active", official_store_id=MAIN_STORE)
        seed.add_link(conn, "MLA5", 80)
        _offers(conn, "MLA5", True)
        conn.execute(
            text("INSERT INTO marcas_pm (marca, categoria, usuario_id) VALUES ('lg', 'tv', :i), ('sony', 'tv', 99999)"),
            {"i": inactive_pm},
        )

    return fill


@pytest.fixture()
def inactive_user(db, rol_ventas):
    from app.models.usuario import Usuario

    user = Usuario(username="baja", email="baja@example.com", nombre="De Baja", password_hash="x", rol_id=rol_ventas.id)
    user.activo = False
    db.add(user)
    db.flush()
    return user


class TestMejoresOfertasPorPm:
    def test_authentication_is_required(self, client, pg) -> None:  # noqa: F811
        assert client.get(POR_PM).status_code in (401, 403)

    def test_the_screen_permission_alone_gets_403(self, client, pg, reader) -> None:  # noqa: F811
        response = client.get(POR_PM, headers=reader)
        assert response.status_code == 403
        assert PERMISO_PMS in response.json()["error"]["message"]

    def test_a_role_grant_denied_by_a_user_override_gets_403(
        self,
        client,
        pg,  # noqa: F811
        db,
        rol_ventas,
        active_user,
        auth_headers,
    ) -> None:
        from app.models.permiso import Permiso, UsuarioPermisoOverride

        grant(db, rol_ventas, PERMISO_PMS, "productos.ver")
        seed_rows(pg, lambda conn: conn.execute(text(MARCAS_PM_DDL)))  # no PM yet: an empty answer
        assert client.get(POR_PM, headers=auth_headers).status_code == 200  # the role alone grants it
        permiso = db.query(Permiso).filter(Permiso.codigo == PERMISO_PMS).one()
        db.add(UsuarioPermisoOverride(usuario_id=active_user.id, permiso_id=permiso.id, concedido=False))
        db.flush()
        response = client.get(POR_PM, headers=auth_headers)
        assert response.status_code == 403
        assert PERMISO_PMS in response.json()["error"]["message"]

    def test_each_pm_with_their_count_most_first(
        self,
        client,
        pg,  # noqa: F811
        db,
        rol_admin,
        admin_user,
        active_user,
        inactive_user,
        admin_auth_headers,
    ) -> None:
        grant(db, rol_admin, PERMISO_PMS)
        seed_rows(pg, _fill_two_pms(admin_user.id, active_user.id, inactive_user.id))
        response = client.get(POR_PM, headers=admin_auth_headers)
        assert response.status_code == 200, response.text
        assert response.json() == {
            "pms": [
                {"pm_id": active_user.id, "nombre": "Test User", "count": 2},
                {"pm_id": admin_user.id, "nombre": "Admin User", "count": 1},
            ],
            "total": 3,
            "tienda_id": MAIN_STORE,
        }

    def test_each_count_is_that_pms_own_count_and_listing_total(
        self,
        client,
        pg,  # noqa: F811
        db,
        rol_admin,
        rol_ventas,
        admin_user,
        active_user,
        inactive_user,
        admin_auth_headers,
        auth_headers,
    ) -> None:
        grant(db, rol_admin, PERMISO_PMS, "ml_ops.ver")
        grant(db, rol_ventas, "productos.ver")
        seed_rows(pg, _fill_two_pms(admin_user.id, active_user.id, inactive_user.id))
        rows = client.get(POR_PM, headers=admin_auth_headers).json()["pms"]
        own = {
            admin_user.id: client.get(URL, headers=admin_auth_headers).json()["count"],
            active_user.id: client.get(URL, headers=auth_headers).json()["count"],
        }
        for row in rows:
            assert row["count"] == own[row["pm_id"]] == _linked_total(client, admin_auth_headers, row["pm_id"])

    def test_every_pm_is_counted_in_one_query_whatever_their_number(
        self,
        client,
        pg,  # noqa: F811
        mlpub_pg,  # noqa: F811
        db,
        rol_admin,
        admin_user,
        active_user,
        inactive_user,
        admin_auth_headers,
    ) -> None:
        grant(db, rol_admin, PERMISO_PMS)
        seed_rows(pg, _fill_two_pms(admin_user.id, active_user.id, inactive_user.id))
        statements: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany) -> None:
            statements.append(statement.lower())

        event.listen(mlpub_pg, "before_cursor_execute", record)
        try:
            response = client.get(POR_PM, headers=admin_auth_headers)
        finally:
            event.remove(mlpub_pg, "before_cursor_execute", record)
        assert response.status_code == 200, response.text
        assert len(response.json()["pms"]) == 2
        assert sum("from marcas_pm" in s and "count(" not in s for s in statements) == 1  # the PMs and their pairs
        assert sum("count(" in s for s in statements) == 1  # every PM's count at once
