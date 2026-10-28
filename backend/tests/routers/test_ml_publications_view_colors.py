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

from app.models.equipo import Equipo, EquipoMiembro, ProductoColor
from app.models.producto import ProductoERP
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import VER, seed_rows
from tests.routers.test_ml_publications_view_kpis import pg, view_pg  # noqa: F401
from tests.routers.test_ml_publications_view_presence import fill
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view.test_groups_postgres import seed_catalog

pytestmark = pytest.mark.postgres

ITEMS_URL = "/api/ml-publications/view/items"
PRODUCTS_URL = "/api/ml-publications/view/products"
GROUPS_URL = "/api/ml-publications/view/groups"
COLOR_KEYS = ("color_marcado", "color_hint_global", "color_hint_equipo_inicial")


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


def test_the_filter_colors_are_exactly_productos_colors() -> None:
    """The view package may not import Productos (the ERP guard), so its list is a copy: this keeps it one."""
    from app.api.endpoints.productos_colors import COLORES_VALIDOS
    from app.services.ml_publications.view.filters import COLOR_VALUES

    assert set(COLOR_VALUES) == {c for c in COLORES_VALIDOS if c is not None}
