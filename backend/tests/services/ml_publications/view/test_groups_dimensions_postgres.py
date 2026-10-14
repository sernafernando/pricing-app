"""The Agrupado tree of `/ml-publications/view/groups` by DIMENSION (Métricas ML's own: marca, categoria,
subcategoria, tienda, pm), on Postgres.

Each dimension is Métricas' hierarchy of group levels (`ml_daily_metrics.groups.HIERARCHIES`) with the products (and
the families) below, exactly like the default `marca` tree. The key test is the same as the default tree's: the
`count` of every node equals the `/items` total with the node's own filters (`params`, written out by hand below).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.models.comision_config import SubcategoriaGrupo
from app.services.ml_daily_metrics.groups import NO_GROUP
from app.services.ml_publications.view import groups
from app.services.ml_publications.view.filters import FilterError, parse_filter
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view.test_groups_postgres import by_key, comma_catalog, seed_catalog, total_of
from tests.services.ml_publications.view.test_listing_postgres import STORES_DDL

pytestmark = pytest.mark.postgres


@pytest.fixture()
def conn(env):  # noqa: F811
    SubcategoriaGrupo.__table__.create(bind=env)
    with env.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(STORES_DDL))
        yield connection


@pytest.fixture()
def db(env, conn):  # noqa: F811
    session = sessionmaker(bind=env, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def tree(db: Session, dimension: str, *path: str, familias: bool = False, **params):
    return groups.list_groups(db, parse_filter(**params), list(path), familias=familias, dimension=dimension)


def expected_params(path_nodes: list) -> dict:
    """The `/items` filters of a node, written out by hand: one per level of its ancestry (and itself)."""
    params: dict = {}
    for node in path_nodes:
        if node.kind == "marca":
            params["marcas"] = node.key
        elif node.kind == "categoria":
            params["categorias"] = node.key
        elif node.kind == "subcategoria":
            params["subcategorias"] = node.key
        elif node.kind == "subcategoria_categoria":
            subcategoria, categoria = node.key.split("|", 1)
            params.update({"subcategorias": subcategoria, "categorias": categoria})
        elif node.kind == "producto":
            params.update({"sin_producto": "true"} if node.key == NO_GROUP else {"producto": node.key})
        elif node.kind == "familia":
            params["familia"] = node.key
        else:
            params["q"] = node.key
    return params


def walk(db: Session, dimension: str, user_params: dict, familias: bool):
    pending: list[list] = [[]]
    while pending:
        ancestors = pending.pop()
        page = tree(db, dimension, *[a.key for a in ancestors], familias=familias, **user_params)
        for node in page.nodes:
            yield node, ancestors
            if not node.leaf:
                pending.append([*ancestors, node])


class TestCategoria:
    def test_the_roots_are_the_categories_then_subcategories_then_products(self, conn, db) -> None:
        seed_catalog(conn)
        roots = tree(db, "categoria")
        assert roots.level == "categoria" and roots.total == 4
        assert {k: (n.label, n.count) for k, n in by_key(roots).items()} == {
            "REDES": ("Redes", 4),
            "SEGURIDAD": ("Seguridad", 1),
            "PERIFERICOS": ("Perifericos", 1),
            NO_GROUP: ("Sin categoría", 3),
        }
        assert by_key(roots)["REDES"].params == {"categorias": "REDES"}
        subcategories = tree(db, "categoria", "REDES")
        assert subcategories.level == "subcategoria"
        assert {k: n.count for k, n in by_key(subcategories).items()} == {"10": 4}
        products = tree(db, "categoria", "REDES", "10")
        assert products.level == "producto"
        assert {k: n.count for k, n in by_key(products).items()} == {"70": 3, "71": 1}
        assert by_key(products)["70"].params == {"categorias": "REDES", "subcategorias": "10", "producto": "70"}

    def test_a_product_opens_into_its_families_when_they_are_on(self, conn, db) -> None:
        seed_catalog(conn)
        families = tree(db, "categoria", "REDES", "10", "70", familias=True)
        assert families.level == "familia" and {n.key: n.count for n in families.nodes} == {"900": 2, "MLA3": 1}

    def test_the_path_is_checked_by_the_kind_of_each_level_not_by_its_depth(self, conn, db) -> None:
        seed_catalog(conn)
        with pytest.raises(FilterError) as caught:
            tree(db, "categoria", "REDES", "no-es-un-id")  # depth 1 is the subcategory here
        assert caught.value.field == "path"
        with pytest.raises(FilterError):
            tree(db, "categoria", "REDES", "10", "no-es-un-id")  # depth 2 is the product
        with pytest.raises(FilterError):
            tree(db, "categoria", "REDES", "10", "70")  # a product is a leaf with families off
        assert tree(db, "categoria", "REDES", "10", "70", familias=True).level == "familia"


class TestSubcategoria:
    def test_the_roots_are_each_subcategory_in_its_category_and_open_into_products(self, conn, db) -> None:
        seed_catalog(conn)
        roots = tree(db, "subcategoria")
        assert roots.level == "subcategoria_categoria"
        assert {k: (n.label, n.count) for k, n in by_key(roots).items()} == {
            "10|REDES": ("Routers · Redes", 4),
            "20|SEGURIDAD": ("Camaras · Seguridad", 1),
            f"{NO_GROUP}|PERIFERICOS": ("Sin subcategoría · Perifericos", 1),
            f"{NO_GROUP}|{NO_GROUP}": ("Sin subcategoría · Sin categoría", 3),
        }
        assert by_key(roots)["10|REDES"].params == {"subcategorias": "10", "categorias": "REDES"}
        products = tree(db, "subcategoria", f"{NO_GROUP}|{NO_GROUP}")
        assert products.level == "producto"
        assert {k: n.count for k, n in by_key(products).items()} == {NO_GROUP: 2, "73": 1}

    def test_a_subcategory_key_must_be_an_id_and_its_category(self, conn, db) -> None:
        seed_catalog(conn)
        for bad in ("x|REDES", "10", "10|", "²|REDES"):
            with pytest.raises(FilterError):
                tree(db, "subcategoria", bad)

    def test_a_category_with_a_comma_or_a_percent_travels_escaped_and_round_trips(self, conn, db) -> None:
        comma_catalog(conn)
        roots = by_key(tree(db, "subcategoria"))
        assert set(roots) == {"10|CAMARAS%2C FOTOS", "20|CABLES%2C %252C"}
        for key, node in roots.items():
            assert node.count == total_of(db, node.params) and "," not in "".join(node.params.values())
            assert sum(n.count for n in tree(db, "subcategoria", key).nodes) == node.count


class TestDimension:
    def test_the_default_is_the_marca_tree(self, conn, db) -> None:
        seed_catalog(conn)
        default = groups.list_groups(db, parse_filter(), [])
        assert default == tree(db, "marca") and default.level == "marca"

    def test_the_levels_of_each_dimension_are_metricas_hierarchy_then_the_products(self) -> None:
        assert groups.levels_of("marca") == ("marca", "categoria", "subcategoria", "producto")
        assert groups.levels_of("categoria") == ("categoria", "subcategoria", "producto")
        assert groups.levels_of("subcategoria") == ("subcategoria_categoria", "producto")

    def test_an_unknown_dimension_is_a_filter_error_naming_it(self, conn, db) -> None:
        with pytest.raises(FilterError) as caught:
            tree(db, "producto")
        assert caught.value.field == "dimension"


class TestConsistencyWithItems:
    @pytest.mark.parametrize("dimension", ["marca", "categoria", "subcategoria"])
    @pytest.mark.parametrize("familias", [False, True])
    @pytest.mark.parametrize("user_params", [{}, {"tiendas": "1"}, {"tiendas": "2", "estado": "active"}])
    def test_every_node_count_equals_the_items_total_for_its_filters(
        self, conn, db, dimension, familias, user_params
    ) -> None:
        seed_catalog(conn)
        comma_catalog(conn)
        checked = 0
        for node, ancestors in walk(db, dimension, user_params, familias):
            assert node.params == expected_params([*ancestors, node])
            assert node.count == total_of(db, {**user_params, **node.params}), (dimension, node.kind, node.key)
            checked += 1
        assert checked >= 6

    @pytest.mark.parametrize("dimension", ["categoria", "subcategoria"])
    def test_the_children_of_a_node_add_up_to_the_node(self, conn, db, dimension) -> None:
        seed_catalog(conn)
        for node, ancestors in walk(db, dimension, {}, True):
            if not node.leaf:
                children = tree(db, dimension, *[a.key for a in ancestors], node.key, familias=True)
                assert sum(c.count for c in children.nodes) == node.count, (node.kind, node.key)
