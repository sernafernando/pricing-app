"""The Agrupado tree of `/ml-publications/view/groups` by DIMENSION (three of Métricas ML's own: marca, categoria,
subcategoria; tienda and pm come next), on Postgres.

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
from tests.services.ml_publications.view import seed
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


PM_DDL = (
    "CREATE TABLE marcas_pm (id serial PRIMARY KEY, marca text, categoria text, usuario_id integer)",
    "CREATE TABLE usuarios (id integer PRIMARY KEY, nombre text)",
)
# The `/items` store filter of every tienda node of `seed_stores_and_pms`: a clave covers ALL its store ids.
STORE_IDS = {"c:GAUSS": "1,3", "s:2": "2", "s:4": "4", "c:A%2CB": "5", NO_GROUP: "none"}


def seed_stores_and_pms(conn) -> None:
    """On top of `seed_catalog`: official stores (a clave shared by stores 1 and 3, a store with an empty clave, a
    clave with a comma, store 2 with no row) and PM assignments.

    Items: MLA50 (store 3, product 72), MLA51 (no store, product 74), MLA52 (store 4, product 70), MLA53 (store 5,
    product 73). PMs: TP-Link/Redes is listed for PM 7 AND (another spelling) PM 5, so the dimension gives it to the
    LOWEST id (5); Hikvision/Seguridad is PM 7's; Logitech/Perifericos is listed with no user.
    """
    stores = [(1, "Gauss", "GAUSS", 0), (3, "Gauss Outlet", "GAUSS", 1), (4, "Sin clave", "", 0), (5, "Coma", "A,B", 0)]
    for store_id, nombre, clave, orden in stores:
        conn.execute(
            text("INSERT INTO ml_tiendas_oficiales (store_id, nombre, clave, orden) VALUES (:s, :n, :c, :o)"),
            {"s": store_id, "n": nombre, "c": clave, "o": orden},
        )
    for item_id, store, product in (("MLA50", 3, 72), ("MLA51", None, 74), ("MLA52", 4, 70), ("MLA53", 5, 73)):
        seed.add_item(conn, item_id, title=f"Titulo {item_id}", status="active", official_store_id=store)
        seed.add_link(conn, item_id, product)
    for ddl in PM_DDL:
        conn.execute(text(ddl))
    for marca, categoria, user in (
        ("TP-Link", "Redes", 7),
        ("TP-LINK", "REDES", 5),
        ("Hikvision", "Seguridad", 7),
        ("Logitech", "Perifericos", None),
    ):
        conn.execute(
            text("INSERT INTO marcas_pm (marca, categoria, usuario_id) VALUES (:m, :c, :u)"),
            {"m": marca, "c": categoria, "u": user},
        )
    conn.execute(text("INSERT INTO usuarios (id, nombre) VALUES (5, 'Ana'), (7, 'Beto')"))


def tree(db: Session, dimension: str, *path: str, familias: bool = False, **params):
    return groups.list_groups(db, parse_filter(**params), list(path), familias=familias, dimension=dimension)


def expected_params(path_nodes: list, user_stores: str = "") -> dict:
    """The `/items` filters of a node, written out by hand: one per level of its ancestry (and itself). A clave's
    store ids are narrowed to the stores the user filtered by (`user_stores`), so the node's filter never widens
    the user's."""
    params: dict = {}
    for node in path_nodes:
        if node.kind == "tienda":
            ids = STORE_IDS[node.key].split(",")
            wanted = user_stores.split(",") if user_stores else ids
            params["tiendas"] = ",".join(i for i in ids if i in wanted)
        elif node.kind == "pm":
            params["pm_grupo"] = node.key
        elif node.kind == "marca":
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


class TestTienda:
    def test_the_roots_are_the_stores_grouped_by_clave_like_metricas(self, conn, db) -> None:
        seed_catalog(conn)
        seed_stores_and_pms(conn)
        roots = tree(db, "tienda")
        assert roots.level == "tienda"
        assert {k: (n.label, n.count, n.params) for k, n in by_key(roots).items()} == {
            "c:GAUSS": ("Gauss", 6, {"tiendas": "1,3"}),  # stores 1 and 3 share the clave: MLA1,2,4,6,8 + MLA50
            "s:2": ("Tienda 2", 4, {"tiendas": "2"}),  # no row for store 2
            "s:4": ("Sin clave", 1, {"tiendas": "4"}),  # an empty clave is a store of its own
            "c:A%2CB": ("Coma", 1, {"tiendas": "5"}),  # a clave with a comma travels escaped
            NO_GROUP: ("Sin tienda", 1, {"tiendas": "none"}),
        }

    def test_a_store_opens_into_its_brands_then_categories_subcategories_and_products(self, conn, db) -> None:
        seed_catalog(conn)
        seed_stores_and_pms(conn)
        assert {k: n.count for k, n in by_key(tree(db, "tienda", "c:GAUSS")).items()} == {
            "TP-LINK": 3,
            "HIKVISION": 1,
            NO_GROUP: 2,
        }
        products = tree(db, "tienda", "c:GAUSS", "TP-LINK", "REDES", "10")
        assert products.level == "producto"
        assert by_key(products)["70"].params == {
            "tiendas": "1,3",
            "marcas": "TP-LINK",
            "categorias": "REDES",
            "subcategorias": "10",
            "producto": "70",
        }
        assert tree(db, "tienda", "c:A%2CB").nodes[0].count == 1

    def test_the_clave_is_narrowed_to_the_stores_the_user_filtered_by(self, conn, db) -> None:
        seed_catalog(conn)
        seed_stores_and_pms(conn)
        node = by_key(tree(db, "tienda", tiendas="1"))["c:GAUSS"]
        assert (node.count, node.params) == (5, {"tiendas": "1"})
        assert node.count == total_of(db, {"tiendas": "1", **node.params})

    def test_a_store_key_is_a_clave_a_store_id_or_none(self, conn, db) -> None:
        seed_catalog(conn)
        seed_stores_and_pms(conn)
        for bad in ("GAUSS", "s:x", "s:", "c:", "1"):
            with pytest.raises(FilterError):
                tree(db, "tienda", bad)


class TestPm:
    def test_the_roots_are_the_pms_and_a_pair_shared_by_two_pms_counts_once_for_the_lowest_id(self, conn, db) -> None:
        seed_catalog(conn)
        seed_stores_and_pms(conn)
        roots = tree(db, "pm")
        assert roots.level == "pm"
        assert {k: (n.label, n.count, n.params) for k, n in by_key(roots).items()} == {
            "5": ("Ana", 4, {"pm_grupo": "5"}),  # product 70: MLA1, MLA2, MLA3, MLA52
            "7": ("Beto", 2, {"pm_grupo": "7"}),  # product 72: MLA5, MLA50 (never TP-Link/Redes: that pair is 5's)
            NO_GROUP: ("Sin PM", 7, {"pm_grupo": NO_GROUP}),
        }
        for node in roots.nodes:
            assert node.count == total_of(db, node.params)
        # the PM filter of the list matches the pairs of ANY listed PM: it would count TP-Link/Redes for 7 as well
        assert total_of(db, {"pms": "7"}) != by_key(roots)["7"].count

    def test_a_pm_opens_into_its_brands_then_down_to_the_products(self, conn, db) -> None:
        seed_catalog(conn)
        seed_stores_and_pms(conn)
        assert {k: n.count for k, n in by_key(tree(db, "pm", "5")).items()} == {"TP-LINK": 4}
        products = tree(db, "pm", "5", "TP-LINK", "REDES", "10")
        assert {k: n.count for k, n in by_key(products).items()} == {"70": 4}

    def test_a_pm_key_is_a_user_id_or_none(self, conn, db) -> None:
        seed_catalog(conn)
        seed_stores_and_pms(conn)
        with pytest.raises(FilterError):
            tree(db, "pm", "Ana")

    @pytest.mark.parametrize("bad", ["x", "5,7", "-1x"])
    def test_the_pm_group_filter_takes_one_user_id_or_none(self, bad) -> None:
        with pytest.raises(FilterError) as caught:
            parse_filter(pm_grupo=bad)
        assert caught.value.field == "pm_grupo"
        assert parse_filter(pm_grupo=NO_GROUP).pm_group == NO_GROUP and parse_filter(pm_grupo="7").pm_group == "7"


class TestDimension:
    def test_the_default_is_the_marca_tree(self, conn, db) -> None:
        seed_catalog(conn)
        default = groups.list_groups(db, parse_filter(), [])
        assert default == tree(db, "marca") and default.level == "marca"

    def test_the_levels_of_each_dimension_are_metricas_hierarchy_then_the_products(self) -> None:
        assert groups.levels_of("marca") == ("marca", "categoria", "subcategoria", "producto")
        assert groups.levels_of("categoria") == ("categoria", "subcategoria", "producto")
        assert groups.levels_of("subcategoria") == ("subcategoria_categoria", "producto")
        assert groups.levels_of("tienda") == ("tienda", "marca", "categoria", "subcategoria", "producto")
        assert groups.levels_of("pm") == ("pm", "marca", "categoria", "subcategoria", "producto")

    def test_an_unknown_dimension_is_a_filter_error_naming_it(self, conn, db) -> None:
        with pytest.raises(FilterError) as caught:
            tree(db, "producto")
        assert caught.value.field == "dimension"


class TestConsistencyWithItems:
    @pytest.mark.parametrize("dimension", ["marca", "categoria", "subcategoria", "tienda", "pm"])
    @pytest.mark.parametrize("familias", [False, True])
    @pytest.mark.parametrize(
        "user_params",
        [{}, {"tiendas": "1"}, {"tiendas": "1,3,none"}, {"tiendas": "2", "estado": "active"}, {"pms": "7"}],
    )
    def test_every_node_count_equals_the_items_total_for_its_filters(
        self, conn, db, dimension, familias, user_params
    ) -> None:
        seed_catalog(conn)
        comma_catalog(conn)
        seed_stores_and_pms(conn)
        checked = 0
        for node, ancestors in walk(db, dimension, user_params, familias):
            assert node.params == expected_params([*ancestors, node], user_params.get("tiendas", ""))
            assert node.count == total_of(db, {**user_params, **node.params}), (dimension, node.kind, node.key)
            checked += 1
        assert checked >= 4

    @pytest.mark.parametrize("dimension", ["categoria", "subcategoria", "tienda", "pm"])
    def test_the_children_of_a_node_add_up_to_the_node(self, conn, db, dimension) -> None:
        seed_catalog(conn)
        seed_stores_and_pms(conn)
        for node, ancestors in walk(db, dimension, {}, True):
            if not node.leaf:
                children = tree(db, dimension, *[a.key for a in ancestors], node.key, familias=True)
                assert sum(c.count for c in children.nodes) == node.count, (node.kind, node.key)
