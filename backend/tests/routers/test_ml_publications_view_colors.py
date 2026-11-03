"""S8: Productos' row colors (and their team layers) on Publicaciones ML's rows.

A color belongs to the PRODUCT, per layer (`producto_color`, the `ml` slot, docs/color-teams-frontend-contract.md):
a publication row carries its linked product's, a Producto-view row and a product node of the tree carry their own.
`equipo_id` picks the layer exactly as `GET /productos` does (omitted = the global one; another team needs
membership, else 403). The fields appear only when they have a value, so a list without colors is unchanged:
`color_marcado` (the active layer), `color_hint_global` (the global one, for a row the team has not painted) and
`color_hint_equipo_inicial` (the team's initial, on a team layer).
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

import pytest

from app.models.equipo import Equipo, EquipoMiembro, ProductoColor, PublicacionColor
from app.models.producto import ProductoERP
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import VER, seed_rows
from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401
from tests.routers.test_ml_publications_view_presence import fill
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_groups_postgres import seed_catalog

pytestmark = pytest.mark.postgres

ITEMS_URL = "/api/ml-publications/view/items"
PRODUCTS_URL = "/api/ml-publications/view/products"
GROUPS_URL = "/api/ml-publications/view/groups"
COLOR_KEYS = (
    "color_marcado",
    "color_hint_global",
    "color_hint_equipo_inicial",
    "color_propio",
    "color_producto",
    "color_hint_global_propio",
    "color_hint_global_producto",
)


@pytest.fixture()
def layers(db, admin_user) -> dict[str, int]:
    """Global: 77 rojo, 78 azul, 70 amarillo. Team "Ventas" (the admin is a member): 77 verde."""
    global_id = db.query(Equipo).filter(Equipo.es_global.is_(True)).one().id
    # The colors live in the application's tables, next to its catalog (the view's store is another database here).
    db.add_all(
        ProductoERP(item_id=item_id, codigo=f"C{item_id}", descripcion=f"P{item_id}") for item_id in (70, 77, 78)
    )
    team = Equipo(nombre="Ventas", es_global=False)
    other = Equipo(nombre="Compras", es_global=False)
    db.add_all([team, other])
    db.flush()
    db.add(EquipoMiembro(equipo_id=team.id, usuario_id=admin_user.id, rol="admin"))
    for equipo_id, item_id, color in ((global_id, 77, "rojo"), (global_id, 78, "azul"), (global_id, 70, "amarillo")):
        db.add(ProductoColor(equipo_id=equipo_id, item_id=item_id, color_ml=color))
    db.add(ProductoColor(equipo_id=team.id, item_id=77, color_ml="verde", color_tienda="rojo"))
    db.flush()
    return {"global": global_id, "team": team.id, "other": other.id}


@pytest.fixture()
def reader(client, db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER)
    return admin_auth_headers


def colors(row: dict) -> dict:
    return {key: row[key] for key in COLOR_KEYS if key in row}


def items(client, headers, **params) -> dict[str, dict]:
    response = client.get(ITEMS_URL, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return {row["item_id"]: colors(row) for row in response.json()["items"]}


def products(client, headers, **params) -> dict[str, dict]:
    response = client.get(PRODUCTS_URL, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return {row["key"]: colors(row) for row in response.json()["rows"]}


class TestPublicationRows:
    def test_the_global_layer_paints_each_publication_with_its_product_color(self, client, pg, reader, layers) -> None:
        seed_rows(pg, fill)
        assert items(client, reader) == {
            "MLA1": {"color_marcado": "rojo"},  # no hint on the global layer: it is the color itself
            "MLA2": {"color_marcado": "azul"},
            "MLA3": {},  # no product, no color
        }

    def test_a_team_layer_shows_the_team_color_the_global_hint_and_the_team_initial(
        self, client, pg, reader, layers
    ) -> None:
        seed_rows(pg, fill)
        assert items(client, reader, equipo_id=layers["team"]) == {
            "MLA1": {"color_marcado": "verde", "color_hint_global": "rojo", "color_hint_equipo_inicial": "V"},
            "MLA2": {"color_hint_global": "azul", "color_hint_equipo_inicial": "V"},
            "MLA3": {"color_hint_equipo_inicial": "V"},
        }

    def test_the_global_layer_asked_by_id_is_the_default(self, client, pg, reader, layers) -> None:
        seed_rows(pg, fill)
        assert items(client, reader, equipo_id=layers["global"]) == items(client, reader)

    def test_a_team_the_user_is_not_in_is_a_403(self, client, pg, reader, layers) -> None:
        seed_rows(pg, fill)
        response = client.get(ITEMS_URL, headers=reader, params={"equipo_id": layers["other"]})
        assert response.status_code == 403

    def test_without_any_color_the_rows_are_unchanged(self, client, pg, reader) -> None:
        seed_rows(pg, fill)
        assert items(client, reader) == {"MLA1": {}, "MLA2": {}, "MLA3": {}}


class TestProductRows:
    def test_each_product_row_carries_its_color_and_the_no_product_row_none(self, client, pg, reader, layers) -> None:
        seed_rows(pg, fill)
        assert products(client, reader, equipo_id=layers["team"]) == {
            "77": {"color_marcado": "verde", "color_hint_global": "rojo", "color_hint_equipo_inicial": "V"},
            "78": {"color_hint_global": "azul", "color_hint_equipo_inicial": "V"},
            "0": {"color_hint_equipo_inicial": "V"},  # the "Sin producto" row: no color, the layer still says whose
        }

    def test_a_team_the_user_is_not_in_is_a_403(self, client, pg, reader, layers) -> None:
        seed_rows(pg, fill)
        assert client.get(PRODUCTS_URL, headers=reader, params={"equipo_id": layers["other"]}).status_code == 403


class TestTreeNodes:
    def test_a_product_node_carries_its_color_and_the_other_levels_none(self, client, pg, reader, layers) -> None:
        seed_rows(pg, seed_catalog)
        root = client.get(GROUPS_URL, headers=reader).json()
        assert all(colors(node) == {} for node in root["nodes"])  # brands are not painted
        body = client.get(GROUPS_URL, headers=reader, params={"path": "TP-LINK,REDES,10"}).json()
        node = next(n for n in body["nodes"] if n["key"] == "70")
        assert colors(node) == {"color_marcado": "amarillo"}

    def test_a_team_the_user_is_not_in_is_a_403(self, client, pg, reader, layers) -> None:
        seed_rows(pg, seed_catalog)
        assert client.get(GROUPS_URL, headers=reader, params={"equipo_id": layers["other"]}).status_code == 403


class TestSlowColors:
    @pytest.mark.parametrize("url", [ITEMS_URL, PRODUCTS_URL, GROUPS_URL])
    def test_a_color_read_over_statement_timeout_is_the_same_controlled_503(
        self, client, pg, reader, layers, monkeypatch, url
    ) -> None:
        from sqlalchemy.exc import OperationalError

        from app.services import ml_publication_colors

        class Canceled(Exception):
            pgcode = "57014"

        def slow(*_args, **_kwargs):
            raise OperationalError("SELECT producto_color", {}, Canceled())

        seed_rows(pg, seed_catalog if url == GROUPS_URL else fill)
        monkeypatch.setattr(ml_publication_colors, "batch_colores", slow)
        params = {"path": "TP-LINK,REDES,10"} if url == GROUPS_URL else {}
        response = client.get(url, headers=reader, params=params)
        assert response.status_code == 503 and response.json()["error"]["code"] == "consulta_lenta"


PRODUCT_IDS_URL = "/api/ml-publications/view/product-ids"


class TestColorFilter:
    """`colores` (P6): Productos' color filter -- csv of colors plus `sin_color` -- on the layer on show (`equipo_id`,
    omitted = the global one), on every read the filters reach."""

    def test_a_color_keeps_the_publications_whose_product_has_it_on_the_global_layer(
        self, client, pg, reader, layers
    ) -> None:
        seed_rows(pg, fill)
        assert set(items(client, reader, colores="rojo")) == {"MLA1"}
        assert set(items(client, reader, colores="rojo,azul")) == {"MLA1", "MLA2"}

    def test_sin_color_keeps_the_unpainted_ones_and_the_publications_with_no_product(
        self, client, pg, reader, layers
    ) -> None:
        seed_rows(pg, fill)
        assert set(items(client, reader, colores="sin_color")) == {"MLA3"}
        assert set(items(client, reader, colores="azul,sin_color")) == {"MLA2", "MLA3"}

    def test_on_a_team_layer_it_is_that_team_color(self, client, pg, reader, layers) -> None:
        seed_rows(pg, fill)
        assert set(items(client, reader, colores="verde", equipo_id=layers["team"])) == {"MLA1"}
        assert set(items(client, reader, colores="rojo", equipo_id=layers["team"])) == set()
        assert set(items(client, reader, colores="sin_color", equipo_id=layers["team"])) == {"MLA2", "MLA3"}

    def test_the_producto_view_and_the_bulk_set_apply_it_too(self, client, pg, reader, layers) -> None:
        seed_rows(pg, fill)
        assert set(products(client, reader, colores="azul")) == {"78"}
        response = client.get(PRODUCT_IDS_URL, headers=reader, params={"colores": "verde", "equipo_id": layers["team"]})
        assert response.status_code == 200, response.text
        assert response.json()["item_ids"] == [77]

    def test_a_team_the_user_is_not_in_is_a_403_wherever_the_filter_goes(self, client, pg, reader, layers) -> None:
        seed_rows(pg, fill)
        params = {"colores": "rojo", "equipo_id": layers["other"]}
        assert client.get(PRODUCT_IDS_URL, headers=reader, params=params).status_code == 403

    def test_a_color_outside_the_vocabulary_is_a_422_naming_it(self, client, pg, reader, layers) -> None:
        seed_rows(pg, fill)
        response = client.get(ITEMS_URL, headers=reader, params={"colores": "fucsia"})
        assert response.status_code == 422
        assert "colores" in response.text

    def test_without_it_nothing_changes(self, client, pg, reader, layers) -> None:
        seed_rows(pg, fill)
        assert set(items(client, reader)) == {"MLA1", "MLA2", "MLA3"}


def fill_sibling(conn) -> None:
    """`fill` plus MLA4, a second publication of product 77 (MLA1's)."""
    fill(conn)
    seed.add_item(conn, "MLA4", status="active")
    seed.add_link(conn, "MLA4", 77)


class TestPublicationOwnColor:
    """seleccion-por-publicacion S3: a publication painted on its own (`publicacion_color`) shows its own color on
    that layer; without one it shows its product's. The other publications of the product and the product rows keep
    the product's color."""

    def paint(self, db, equipo_id: int, item_id: str, color: str) -> None:
        db.add(PublicacionColor(equipo_id=equipo_id, item_id=item_id, color_ml=color))
        db.flush()

    def test_its_own_color_wins_over_its_products_and_the_siblings_keep_the_products(
        self, client, pg, db, reader, layers
    ) -> None:
        seed_rows(pg, fill_sibling)
        self.paint(db, layers["global"], "MLA4", "azul")
        self.paint(db, layers["global"], "MLA3", "gris")  # no product: its own color still shows
        assert items(client, reader) == {
            "MLA1": {"color_marcado": "rojo"},
            "MLA2": {"color_marcado": "azul"},
            "MLA3": {"color_marcado": "gris", "color_propio": "gris"},
            # Its own color and its product's apart too, so a repaint of either shows without asking again.
            "MLA4": {"color_marcado": "azul", "color_propio": "azul", "color_producto": "rojo"},
        }

    def test_on_a_team_layer_its_own_team_and_global_colors_win_each_on_its_layer(
        self, client, pg, db, reader, layers
    ) -> None:
        seed_rows(pg, fill_sibling)
        self.paint(db, layers["team"], "MLA4", "naranja")
        self.paint(db, layers["global"], "MLA4", "gris")
        self.paint(db, layers["other"], "MLA1", "purpura")  # another team's color never shows here
        assert items(client, reader, equipo_id=layers["team"])["MLA4"] == {
            "color_marcado": "naranja",
            "color_hint_global": "gris",
            "color_hint_equipo_inicial": "V",
            "color_propio": "naranja",
            "color_producto": "verde",
            "color_hint_global_propio": "gris",
            "color_hint_global_producto": "rojo",
        }
        assert items(client, reader, equipo_id=layers["team"])["MLA1"] == {
            "color_marcado": "verde",
            "color_hint_global": "rojo",
            "color_hint_equipo_inicial": "V",
        }

    def test_the_color_filter_follows_the_effective_color(self, client, pg, db, reader, layers) -> None:
        seed_rows(pg, fill_sibling)
        self.paint(db, layers["global"], "MLA4", "azul")  # its product is rojo
        self.paint(db, layers["global"], "MLA3", "gris")  # no product
        assert set(items(client, reader, colores="rojo")) == {"MLA1"}
        assert set(items(client, reader, colores="azul")) == {"MLA2", "MLA4"}
        assert set(items(client, reader, colores="gris")) == {"MLA3"}
        assert set(items(client, reader, colores="sin_color")) == set()
        assert set(items(client, reader, colores="verde", equipo_id=layers["team"])) == {"MLA1", "MLA4"}
        self.paint(db, layers["team"], "MLA4", "naranja")
        assert set(items(client, reader, colores="verde", equipo_id=layers["team"])) == {"MLA1"}
        assert set(items(client, reader, colores="sin_color", equipo_id=layers["team"])) == {"MLA2", "MLA3"}

    def test_with_a_catalog_filter_and_in_the_tree_it_is_the_same_effective_color(
        self, client, pg, db, reader, layers
    ) -> None:
        # The catalog filter and the tree check the color on the linked product too: an own color passes there.
        seed_rows(pg, fill_sibling)
        self.paint(db, layers["global"], "MLA4", "azul")  # its product 77 (TP-Link) is rojo
        assert set(items(client, reader, colores="azul", marcas="TP-Link")) == {"MLA4"}
        assert set(items(client, reader, colores="rojo", marcas="TP-Link")) == {"MLA1"}
        response = client.get(GROUPS_URL, headers=reader, params={"colores": "azul"})
        assert response.status_code == 200, response.text
        assert {node["key"]: node["count"] for node in response.json()["nodes"]} == {"TP-LINK": 1, "UBIQUITI": 1}

    def test_the_bulk_price_set_takes_the_product_of_a_publication_kept_by_its_own_color(
        self, client, pg, db, reader, layers
    ) -> None:
        # The operator sees MLA4 under `colores=azul`: the bulk action reaches its product, as it reaches MLA2's.
        seed_rows(pg, fill_sibling)
        self.paint(db, layers["global"], "MLA4", "azul")
        response = client.get(PRODUCT_IDS_URL, headers=reader, params={"colores": "azul"})
        assert response.status_code == 200, response.text
        assert response.json()["item_ids"] == [77, 78]

    def test_the_producto_view_reads_only_product_colors_even_when_every_publication_is_painted(
        self, client, pg, db, reader, layers
    ) -> None:
        # 78 is azul and its only publication MLA2 is painted rojo on its own: the product row is still azul, whole.
        seed_rows(pg, fill_sibling)
        self.paint(db, layers["global"], "MLA2", "rojo")
        assert set(products(client, reader, colores="azul")) == {"78"}
        assert "78" not in products(client, reader, colores="rojo")
        response = client.get(PRODUCTS_URL, headers=reader, params={"colores": "rojo"})
        assert {row["key"]: row["publications_count"] for row in response.json()["rows"]} == {"77": 2}
        # Its bulk set and cards ask the same (`color_por_producto`), so they act on exactly its rows.
        by_product = {"colores": "azul", "color_por_producto": "true"}
        response = client.get(PRODUCT_IDS_URL, headers=reader, params=by_product)
        assert response.status_code == 200, response.text
        assert response.json()["item_ids"] == [78]
        # Opening the row asks `/items` with its `params` on the same filters: they hold exactly what it counts.
        [row] = client.get(PRODUCTS_URL, headers=reader, params={"colores": "azul"}).json()["rows"]
        opened = client.get(ITEMS_URL, headers=reader, params={"colores": "azul", **row["params"]}).json()
        assert opened["total"] == row["publications_count"] == 1
        # The cards count 78 only with the flag: without it MLA2's own rojo drops it, as on the Publicación view.
        stats_url = "/api/ml-publications/view/stats"
        assert client.get(stats_url, headers=reader, params=by_product).json()["stats"]["total"] == 1
        assert client.get(stats_url, headers=reader, params={"colores": "azul"}).json()["stats"]["total"] == 0

    def test_the_brand_facet_counts_a_publication_kept_by_its_own_color(self, client, pg, db, reader, layers) -> None:
        # MLA4 is painted azul on its own on 77, a rojo TP-Link product: the list keeps it, so its brand counts it.
        seed_rows(pg, fill_sibling)
        self.paint(db, layers["global"], "MLA4", "azul")
        response = client.get(ITEMS_URL, headers=reader, params={"colores": "azul", "facets": "true"})
        assert response.status_code == 200, response.text
        assert set(item["item_id"] for item in response.json()["items"]) == {"MLA2", "MLA4"}
        assert response.json()["facets"]["marcas"] == {"TP-LINK": 1, "UBIQUITI": 1}

    def test_product_rows_keep_the_products_color(self, client, pg, db, reader, layers) -> None:
        seed_rows(pg, fill_sibling)
        self.paint(db, layers["global"], "MLA4", "azul")
        assert products(client, reader)["77"] == {"color_marcado": "rojo"}
        assert set(products(client, reader, colores="azul")) == {"78"}


def test_the_filter_colors_are_exactly_productos_colors() -> None:
    """The view package may not import Productos (the ERP guard), so its list is a copy: this keeps it one."""
    from app.api.endpoints.productos_colors import COLORES_VALIDOS
    from app.services.ml_publications.view.filters import COLOR_VALUES

    assert set(COLOR_VALUES) == {c for c in COLORES_VALIDOS if c is not None}
