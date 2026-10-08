"""P7a.T3: `GET /api/ml-publications/view/groups` (permission, contract, validation, timeouts, constant statements).

Same harness as `test_ml_publications_view.py` (permissions in the SQLite test database, the store in a throwaway
Postgres schema). The nodes themselves are pinned in `view/test_groups_postgres.py`; this file pins the HTTP surface
and that the node `params` really fetch the node's publications from `/items`.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, func

from app.routers import ml_publications_view
from app.services.ml_publications.view import groups, listing, status_block
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import (  # noqa: F401
    URL as ITEMS_URL,
    VER,
    get as get_items,
    pg as view_pg,
    seed_rows,
)
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_groups_postgres import seed_catalog

pytestmark = pytest.mark.postgres

URL = "/api/ml-publications/view/groups"


@pytest.fixture()
def pg(view_pg):  # noqa: F811 -- the imported fixture is used by name
    return view_pg


@pytest.fixture()
def reader(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER)
    return admin_auth_headers


def get(client, headers, **params):
    return client.get(URL, headers=headers, params=params)


class TestPermission:
    def test_authentication_is_required(self, client, pg) -> None:
        assert client.get(URL).status_code in (401, 403)

    def test_a_user_without_ml_ops_ver_gets_403(self, client, pg, auth_headers) -> None:
        response = get(client, auth_headers)
        assert response.status_code == 403 and VER in response.json()["error"]["message"]

    def test_who_may_ask_is_decided_before_what_is_asked(self, client, pg, auth_headers) -> None:
        bad = {"estado": "bogus"}  # a 422 on its own
        assert client.get(URL, params=bad).status_code in (401, 403)
        assert get(client, auth_headers, **bad).status_code == 403
        assert client.get(ITEMS_URL, params=bad).status_code in (401, 403)
        assert get_items(client, auth_headers, **bad).status_code == 403

    def test_the_router_has_exactly_the_groups_read_added(self) -> None:
        paths = {r.path for r in ml_publications_view.router.routes if "/groups" in r.path}
        assert paths == {"/ml-publications/view/groups"}


class TestContract:
    def test_the_root_lists_the_brands_with_the_page_envelope(self, client, pg, reader) -> None:
        seed_rows(pg, seed_catalog)
        body = get(client, reader).json()
        assert {k: body[k] for k in ("level", "path", "total", "limit", "offset", "familias")} == {
            "level": "marca",
            "path": [],
            "total": 4,
            "limit": 100,
            "offset": 0,
            "familias": False,
        }
        brand = next(n for n in body["nodes"] if n["key"] == "HIKVISION")
        assert brand == {
            "kind": "marca",
            "key": "HIKVISION",
            "label": "Hikvision",
            "count": 1,
            "leaf": False,
            "params": {"marcas": "HIKVISION"},
        }  # no keys that do not apply to a brand (no producto_item_id, family_id, ...)

    def test_a_product_node_and_a_family_node_carry_their_own_fields(self, client, pg, reader) -> None:
        seed_rows(pg, seed_catalog)
        products = get(client, reader, path="TP-LINK,REDES,10", familias="true").json()
        node = next(n for n in products["nodes"] if n["key"] == "70")
        assert node == {
            "kind": "producto",
            "key": "70",
            "label": "Router AX",
            "count": 3,
            "leaf": False,
            "params": {"marcas": "TP-LINK", "categorias": "REDES", "subcategorias": "10", "producto": "70"},
            "producto_item_id": 70,
            "codigo": "A1",
        }
        families = get(client, reader, path="TP-LINK,REDES,10,70", familias="true").json()
        assert families["level"] == "familia" and families["path"] == ["TP-LINK", "REDES", "10", "70"]
        family = next(n for n in families["nodes"] if n["kind"] == "familia")
        assert family["family_id"] == 900 and family["params"]["familia"] == "900"
        single = next(n for n in families["nodes"] if n["kind"] == "item")
        assert single["item_id"] == "MLA3" and single["params"]["q"] == "MLA3"

    def test_the_filters_of_the_list_apply_including_the_store(self, client, pg, reader) -> None:
        seed_rows(pg, seed_catalog)
        body = get(client, reader, tiendas="2").json()
        assert {n["key"]: n["count"] for n in body["nodes"]} == {
            "TP-LINK": 1,
            "HIKVISION": 1,
            "LOGITECH": 1,
            "__none__": 1,
        }

    def test_the_node_params_fetch_exactly_the_node_publications_from_items(self, client, pg, reader) -> None:
        seed_rows(pg, seed_catalog)
        checked = 0
        pending = [[]]
        while pending:
            path = pending.pop()
            body = get(client, reader, path=",".join(path), familias="true", tiendas="1,2").json()
            for node in body["nodes"]:
                items = get_items(client, reader, tiendas="1,2", **node["params"]).json()
                assert items["total"] == node["count"], node
                checked += 1
                if not node["leaf"]:
                    pending.append([*path, node["key"]])
        assert checked >= 15


class TestKeysWithSeparators:
    def test_a_brand_with_a_comma_opens_and_its_params_fetch_exactly_its_publications(self, client, pg, reader) -> None:
        def fill(conn) -> None:
            seed.add_product(conn, 95, "K1", "Parlante", marca="Audio, Video Inc", categoria="Camaras, Fotos")
            for n in (40, 41):
                seed.add_item(conn, f"MLA{n}", title="t", status="active")
                seed.add_link(conn, f"MLA{n}", 95)

        seed_rows(pg, fill)
        brand = get(client, reader).json()["nodes"][0]
        assert brand["label"] == "Audio, Video Inc" and "," not in brand["key"]
        children = get(client, reader, path=brand["key"]).json()
        assert children["level"] == "categoria" and [(n["label"], n["count"]) for n in children["nodes"]] == [
            ("Camaras, Fotos", 2)
        ]
        assert get_items(client, reader, **brand["params"]).json()["total"] == brand["count"] == 2
        category = children["nodes"][0]
        assert get_items(client, reader, **category["params"]).json()["total"] == 2


class TestInvalidParams:
    @pytest.mark.parametrize(
        "params, field",
        [
            ({"path": "A,B,10,70"}, "path"),  # a product is a leaf with families off
            ({"path": "A,B,x"}, "path"),
            ({"path": "A,B,10,70,x", "familias": "true"}, "path"),
            ({"estado": "bogus"}, "estado"),
            ({"producto": "x"}, "producto"),
            ({"evento": "price_changed"}, "evento"),  # the events flag is off
        ],
    )
    def test_a_bad_value_is_422_naming_the_param(self, client, pg, reader, params, field) -> None:
        response = get(client, reader, **params)
        assert response.status_code == 422 and response.json()["error"]["field"] == field

    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
    def test_the_page_size_is_bounded_by_the_framework(self, client, pg, reader, params) -> None:
        assert get(client, reader, **params).status_code == 422

    def test_a_path_key_is_taken_as_text_so_an_unknown_brand_is_just_empty(self, client, pg, reader) -> None:
        seed_rows(pg, seed_catalog)
        body = get(client, reader, path="NO-SUCH-BRAND").json()
        assert body["level"] == "categoria" and body["nodes"] == [] and body["total"] == 0


class TestStatementCount:
    def statements(self, client, pg, reader, **params) -> list[str]:
        recorded: list[str] = []

        def record(conn, cursor, statement, *rest) -> None:
            recorded.append(statement)

        event.listen(pg, "before_cursor_execute", record)
        try:
            assert get(client, reader, **params).status_code == 200
        finally:
            event.remove(pg, "before_cursor_execute", record)
        return recorded

    def test_the_count_does_not_depend_on_the_number_of_nodes(self, client, pg, reader) -> None:
        seed_rows(pg, seed_catalog)
        get(client, reader)  # warm
        few = self.statements(client, pg, reader, path="TP-LINK,REDES,10")

        def many(conn) -> None:
            for n in range(150):
                seed.add_product(
                    conn, 3000 + n, f"Z{n}", f"Producto Z{n}", marca="TP-Link", categoria="Redes", subcategoria_id=10
                )
                seed.add_item(conn, f"MLZ{n:04d}", title="t")
                seed.add_link(conn, f"MLZ{n:04d}", 3000 + n)

        seed_rows(pg, many)
        lots = self.statements(client, pg, reader, path="TP-LINK,REDES,10")
        assert len(few) == len(lots) <= 4


class TestSlowQuery:
    def test_a_statement_timeout_is_a_controlled_503_and_the_connection_goes_back(
        self, client, pg, reader, monkeypatch
    ) -> None:
        seed_rows(pg, seed_catalog)
        real = groups.build_base_select

        def slow(f, *columns, **kwargs):
            return real(f, *columns, func.pg_sleep(1), **kwargs)

        monkeypatch.setattr(listing, "STATEMENT_TIMEOUT", "50ms")
        monkeypatch.setattr(groups, "build_base_select", slow)
        response = get(client, reader)
        assert response.status_code == 503 and response.json()["error"]["code"] == "consulta_lenta"
        assert pg.pool.checkedout() == 0
        monkeypatch.setattr(listing, "STATEMENT_TIMEOUT", "8s")
        monkeypatch.setattr(groups, "build_base_select", real)
        status_block.REPORT.reset()
        assert get(client, reader).status_code == 200
