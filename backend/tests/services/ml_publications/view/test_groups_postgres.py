"""P7a.T2: the nodes of `/ml-publications/view/groups` on Postgres (the Agrupado tree, counts only).

Tree (decision 1): marca > categoria > subcategoria > producto > [familia] > MLA. The store is a filter, not a level.
The key test is CONSISTENCY: the `count` of every node equals the `/items` total with the node's own filters
(`node["params"]`, written out by hand below as `expected_params` so the contract is pinned by the test).

Rows are plain inserts (`seed.py`) over the real store migrations in a throwaway schema.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.comision_config import SubcategoriaGrupo
from app.services.ml_daily_metrics.groups import NO_GROUP
from app.services.ml_publications.view import groups, listing
from app.services.ml_publications.view.filters import FilterError, parse_filter
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
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


def seed_catalog(conn) -> None:
    """Five products and ten publications covering every branch of the tree.

    TP-Link (two spellings of one brand) > Redes > Routers: products 70 and 71. Hikvision > Seguridad > Camaras: 72.
    A product with no brand/category/subcategory: 73. Logitech > Perifericos with no subcategory: 74.
    """
    conn.execute(text("INSERT INTO subcategorias_grupos (subcat_id, nombre_subcategoria) VALUES (10, 'Routers')"))
    conn.execute(text("INSERT INTO subcategorias_grupos (subcat_id, nombre_subcategoria) VALUES (20, 'Camaras')"))
    seed.add_product(conn, 70, "A1", "Router AX", marca="TP-Link", categoria="Redes", subcategoria_id=10)
    seed.add_product(conn, 71, "A2", "Switch 8p", marca=" tp-link", categoria="redes ", subcategoria_id=10)
    seed.add_product(conn, 72, "B1", "Camara domo", marca="Hikvision", categoria="Seguridad", subcategoria_id=20)
    seed.add_product(conn, 73, "C1", "Cable suelto")
    seed.add_product(conn, 74, "D1", "Mouse", marca="Logitech", categoria="Perifericos")
    rows = [
        # item, product, store, family
        ("MLA1", 70, 1, 900),
        ("MLA2", 70, 1, 900),
        ("MLA3", 70, 2, 901),
        ("MLA4", 71, 1, None),
        ("MLA5", 72, 2, None),
        ("MLA6", None, 1, None),  # no link at all
        ("MLA7", None, 2, 900),  # a link row that matched nothing
        ("MLA8", 73, 1, None),
        ("MLA9", 74, 2, None),
        ("MLA10", 72, 1, None),  # gone from ML: hidden by default
    ]
    for item_id, product, store, family in rows:
        gone = {"gone_at": seed.NOW} if item_id == "MLA10" else {}
        seed.add_item(
            conn,
            item_id,
            title=f"Titulo {item_id}",
            status="paused" if item_id == "MLA9" else "active",
            official_store_id=store,
            family_id=family,
            family_name="Familia 900" if family == 900 else None,
            **gone,
        )
        if product is not None:
            seed.add_link(conn, item_id, product)
    seed.add_link(conn, "MLA7", None, match_status="no_product")


def tree(db: Session, *path: str, familias: bool = False, limit: int = 100, offset: int = 0, **params):
    return groups.list_groups(db, parse_filter(**params), list(path), familias=familias, limit=limit, offset=offset)


def by_key(page) -> dict:
    return {node.key: node for node in page.nodes}


def total_of(db: Session, params: dict) -> int:
    return listing.list_items(db, parse_filter(**params), listing.parse_sort(None, None), 1, 0, events=True).total


class TestRoot:
    def test_the_root_is_the_brands_with_their_publication_counts(self, conn, db) -> None:
        seed_catalog(conn)
        page = tree(db)
        assert page.level == "marca" and page.total == 4
        assert {key: (node.label, node.count, node.leaf) for key, node in by_key(page).items()} == {
            "TP-LINK": ("TP-Link", 4, False),  # the two spellings are ONE brand; the label is the one that sorts last
            "HIKVISION": ("Hikvision", 1, False),  # MLA10 is gone: not counted
            "LOGITECH": ("Logitech", 1, False),
            NO_GROUP: ("Sin marca", 3, False),  # the product with no brand (MLA8) AND the unlinked ones (MLA6, MLA7)
        }

    def test_the_active_filters_apply_including_the_store(self, conn, db) -> None:
        seed_catalog(conn)
        counts = {key: node.count for key, node in by_key(tree(db, tiendas="1")).items()}
        assert counts == {"TP-LINK": 3, NO_GROUP: 2}  # MLA1, MLA2, MLA4 | MLA6, MLA8
        counts = {key: node.count for key, node in by_key(tree(db, tiendas="2")).items()}
        assert counts == {"TP-LINK": 1, "HIKVISION": 1, "LOGITECH": 1, NO_GROUP: 1}

    def test_a_filter_that_matches_nothing_is_an_empty_level_with_total_zero(self, conn, db) -> None:
        seed_catalog(conn)
        page = tree(db, q="no existe ninguna publicacion asi")
        assert page.nodes == [] and page.total == 0 and page.level == "marca"


class TestDescent:
    def test_a_brand_opens_into_its_categories_then_subcategories_then_products(self, conn, db) -> None:
        seed_catalog(conn)
        categories = tree(db, "TP-LINK")
        assert categories.level == "categoria"
        assert {k: (n.label, n.count) for k, n in by_key(categories).items()} == {"REDES": ("redes ", 4)}
        subcategories = tree(db, "TP-LINK", "REDES")
        assert subcategories.level == "subcategoria"
        assert {k: (n.label, n.count) for k, n in by_key(subcategories).items()} == {"10": ("Routers", 4)}
        products = tree(db, "TP-LINK", "REDES", "10")
        assert products.level == "producto"
        assert {k: (n.label, n.count) for k, n in by_key(products).items()} == {
            "70": ("Router AX", 3),
            "71": ("Switch 8p", 1),
        }

    def test_a_product_node_carries_its_id_and_code_and_is_a_leaf(self, conn, db) -> None:
        seed_catalog(conn)
        node = by_key(tree(db, "TP-LINK", "REDES", "10"))["70"]
        assert (node.kind, node.producto_item_id, node.codigo, node.leaf) == ("producto", 70, "A1", True)

    def test_a_missing_category_or_subcategory_is_a_none_node_never_dropped(self, conn, db) -> None:
        seed_catalog(conn)
        # Logitech has a category but no subcategory
        sub = by_key(tree(db, "LOGITECH", "PERIFERICOS"))
        assert {k: (n.label, n.count) for k, n in sub.items()} == {NO_GROUP: ("Sin subcategoría", 1)}
        # the brandless product: no brand, no category, no subcategory
        cat = by_key(tree(db, NO_GROUP))
        assert {k: (n.label, n.count) for k, n in cat.items()} == {NO_GROUP: ("Sin categoría", 3)}
        assert tree(db, NO_GROUP, NO_GROUP).level == "subcategoria"
        assert {k: n.count for k, n in by_key(tree(db, NO_GROUP, NO_GROUP)).items()} == {NO_GROUP: 3}

    def test_the_subcategory_label_is_its_name_and_unknown_ids_get_a_readable_fallback(self, conn, db) -> None:
        seed_catalog(conn)
        seed.add_product(
            conn, 75, "E1", "Sin nombre de subcat", marca="Epson", categoria="Impresion", subcategoria_id=99
        )
        seed.add_item(conn, "MLA11", title="x")
        seed.add_link(conn, "MLA11", 75)
        assert by_key(tree(db, "EPSON", "IMPRESION"))["99"].label == "Subcategoría #99"
        assert by_key(tree(db, "HIKVISION", "SEGURIDAD"))["20"].label == "Camaras"

    def test_a_path_deeper_than_the_tree_is_a_422_style_filter_error(self, conn, db) -> None:
        seed_catalog(conn)
        with pytest.raises(FilterError) as caught:
            tree(db, "TP-LINK", "REDES", "10", "70")  # a product is a leaf unless families are on
        assert caught.value.field == "path"
        with pytest.raises(FilterError):
            tree(db, "TP-LINK", "REDES", "10", "70", "x", familias=True)
        with pytest.raises(FilterError):
            tree(db, "TP-LINK", "REDES", "no-es-un-id")  # a subcategory key is an id
        with pytest.raises(FilterError):
            tree(db, "TP-LINK", "REDES", "10", "no-es-un-id")  # a product key is an id


class TestSinProducto:
    def test_unlinked_publications_sit_under_a_sin_producto_node_whose_children_are_the_mlas(self, conn, db) -> None:
        seed_catalog(conn)
        products = tree(db, NO_GROUP, NO_GROUP, NO_GROUP)
        assert {k: (n.kind, n.label, n.count, n.leaf) for k, n in by_key(products).items()} == {
            NO_GROUP: ("producto", "Sin producto", 2, True),  # MLA6 (no link) and MLA7 (no product)
            "73": ("producto", "Cable suelto", 1, True),
        }
        assert by_key(products)[NO_GROUP].producto_item_id is None
        assert by_key(products)[NO_GROUP].params["sin_producto"] == "true"


class TestFamilies:
    def test_default_is_off_so_a_product_is_a_leaf_with_all_its_publications(self, conn, db) -> None:
        seed_catalog(conn)
        node = by_key(tree(db, "TP-LINK", "REDES", "10"))["70"]
        assert node.leaf is True and node.count == 3

    def test_on_a_product_with_a_shared_family_stops_being_a_leaf(self, conn, db) -> None:
        seed_catalog(conn)
        products = by_key(tree(db, "TP-LINK", "REDES", "10", familias=True))
        assert products["70"].leaf is False and products["70"].count == 3  # MLA1+MLA2 share family 900
        assert products["71"].leaf is True  # its only publication has no family

    def test_a_family_of_two_or_more_is_a_node_and_a_single_mla_stays_an_mla(self, conn, db) -> None:
        seed_catalog(conn)
        page = tree(db, "TP-LINK", "REDES", "10", "70", familias=True)
        assert page.level == "familia" and page.total == 2
        nodes = {n.key: n for n in page.nodes}
        family = nodes["900"]
        assert (family.kind, family.label, family.count, family.leaf, family.family_id) == (
            "familia",
            "Familia 900",
            2,
            True,
            900,
        )
        single = nodes["MLA3"]  # family 901 has ONE publication under this product: not a node
        assert (single.kind, single.count, single.leaf, single.item_id, single.family_id) == (
            "item",
            1,
            True,
            "MLA3",
            None,
        )

    def test_an_mla_is_labelled_with_its_title_even_when_its_family_has_a_name(self, conn, db) -> None:
        seed.add_product(conn, 90, "F1", "Producto F", marca="Zeta", categoria="Z", subcategoria_id=1)
        seed.add_item(
            conn, "MLA30", title="Titulo propio", family_id=902, family_name="Nombre de familia", status="active"
        )
        seed.add_link(conn, "MLA30", 90)
        seed.add_item(conn, "MLA31", title="Otro", family_id=903, family_name=None, status="active")
        seed.add_item(conn, "MLA32", title="Hermano", family_id=903, family_name=None, status="active")
        seed.add_link(conn, "MLA31", 90)
        seed.add_link(conn, "MLA32", 90)
        nodes = {n.key: n for n in tree(db, "ZETA", "Z", "1", "90", familias=True).nodes}
        assert nodes["MLA30"].label == "Titulo propio" and nodes["MLA30"].kind == "item"
        assert (nodes["903"].kind, nodes["903"].label, nodes["903"].count) == ("familia", "Familia 903", 2)

    def test_a_family_shared_with_another_product_is_split_by_product(self, conn, db) -> None:
        seed_catalog(conn)
        # MLA7 (unlinked) is in family 900 too, but under "Sin producto", not under product 70
        under_70 = {n.key: n.count for n in tree(db, "TP-LINK", "REDES", "10", "70", familias=True).nodes}
        assert under_70["900"] == 2
        unlinked = tree(db, NO_GROUP, NO_GROUP, NO_GROUP, NO_GROUP, familias=True)
        assert {n.key: (n.kind, n.count) for n in unlinked.nodes} == {"MLA6": ("item", 1), "MLA7": ("item", 1)}


class TestPaging:
    def seed_many(self, conn, products: int) -> None:
        for n in range(products):
            seed.add_product(
                conn, 1000 + n, f"P{n:04d}", f"Producto {n:04d}", marca="Masiva", categoria="C", subcategoria_id=5
            )
            seed.add_item(conn, f"MLB{n:04d}", title="t")
            seed.add_link(conn, f"MLB{n:04d}", 1000 + n)

    def test_pages_of_100_with_the_total_and_no_repeats_or_gaps(self, conn, db) -> None:
        self.seed_many(conn, 230)
        first = tree(db, "MASIVA", "C", "5")
        assert (len(first.nodes), first.total) == (100, 230)
        second = tree(db, "MASIVA", "C", "5", offset=100)
        third = tree(db, "MASIVA", "C", "5", offset=200)
        assert (len(second.nodes), len(third.nodes), third.total) == (100, 30, 230)
        seen = [n.key for page in (first, second, third) for n in page.nodes]
        assert len(seen) == len(set(seen)) == 230
        assert seen == sorted(seen, key=lambda key: f"Producto {int(key) - 1000:04d}")  # by label

    def test_an_offset_past_the_end_is_empty_but_keeps_the_total(self, conn, db) -> None:
        self.seed_many(conn, 3)
        page = tree(db, "MASIVA", "C", "5", offset=50)
        assert page.nodes == [] and page.total == 3


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
        elif node.kind == "producto":
            params.update({"sin_producto": "true"} if node.key == NO_GROUP else {"producto": node.key})
        elif node.kind == "familia":
            params["familia"] = node.key
        else:
            params["q"] = node.key
    return params


def walk(db: Session, user_params: dict, familias: bool):
    """Every node of the tree under `user_params`, with its ancestry: (node, ancestors)."""
    pending: list[list] = [[]]
    while pending:
        ancestors = pending.pop()
        page = tree(db, *[a.key for a in ancestors], familias=familias, **user_params)
        for node in page.nodes:
            yield node, ancestors
            if not node.leaf:
                pending.append([*ancestors, node])


def comma_catalog(conn) -> None:
    """A brand and a category whose names hold the separators of the CSV parameters (`,`) and of the key encoding (`%`)."""
    seed.add_product(
        conn, 95, "K1", "Parlante", marca="Audio, Video Inc", categoria="Camaras, Fotos", subcategoria_id=10
    )
    seed.add_product(conn, 96, "K2", "Cable", marca="100% Pure", categoria="Cables, %2C", subcategoria_id=20)
    for n, product in enumerate((95, 95, 96), start=40):
        seed.add_item(conn, f"MLA{n}", title=f"Titulo {n}", status="active")
        seed.add_link(conn, f"MLA{n}", product)


class TestConsistencyWithItems:
    """The key test: a node's `count` IS the `/items` total with the node's filters, at every level."""

    @pytest.mark.parametrize("familias", [False, True])
    @pytest.mark.parametrize(
        "user_params", [{}, {"tiendas": "1"}, {"tiendas": "2", "estado": "active"}, {"q": "Titulo"}]
    )
    def test_every_node_count_equals_the_items_total_for_its_filters(self, conn, db, user_params, familias) -> None:
        seed_catalog(conn)
        checked = 0
        for node, ancestors in walk(db, user_params, familias):
            hand_written = expected_params([*ancestors, node])
            assert node.params == hand_written
            assert node.count == total_of(db, {**user_params, **hand_written}), (node.kind, node.key, user_params)
            checked += 1
        assert checked >= 8  # the walk really visited the tree (a vacuous loop would pass trivially)

    def test_a_name_that_python_and_postgres_upper_case_differently_still_round_trips(self, conn, db) -> None:
        # Postgres keeps the sharp s (C.UTF-8) where Python would write SS: the filter must not upper-case in Python
        seed.add_product(conn, 80, "S1", "Masa", marca="Maßstab", categoria="Straße")
        seed.add_item(conn, "MLA20", title="Masa", status="active")
        seed.add_link(conn, "MLA20", 80)
        brand = next(n for n in tree(db).nodes if n.label == "Maßstab")
        assert brand.count == 1 and total_of(db, {"marcas": brand.key}) == 1
        category = next(n for n in tree(db, brand.key).nodes)
        assert total_of(db, {"marcas": brand.key, "categorias": category.key}) == category.count == 1

    @pytest.mark.parametrize("familias", [False, True])
    def test_a_brand_or_category_with_a_comma_or_a_percent_opens_and_counts_like_any_other(
        self, conn, db, familias
    ) -> None:
        seed_catalog(conn)
        comma_catalog(conn)
        nodes = {node.label: node for node, _ in walk(db, {}, familias)}
        assert {"Audio, Video Inc", "Camaras, Fotos", "100% Pure", "Cables, %2C"} <= set(nodes)
        for node, ancestors in walk(db, {}, familias):
            assert "," not in node.key and all("," not in v for v in node.params.values())
            assert node.count == total_of(db, {**node.params}), (node.kind, node.key)
        brand = nodes["Audio, Video Inc"]
        assert brand.count == 2 and tree(db, brand.key).nodes[0].count == 2  # it opens: it is not split in two keys

    def test_the_children_of_a_node_add_up_to_the_node(self, conn, db) -> None:
        seed_catalog(conn)
        for familias in (False, True):
            for node, ancestors in walk(db, {}, familias):
                if node.leaf:
                    continue
                children = tree(db, *[a.key for a in ancestors], node.key, familias=familias)
                assert sum(c.count for c in children.nodes) == node.count, (node.kind, node.key)


class TestStatementCount:
    def count_statements(self, env, run) -> int:  # noqa: F811
        recorded: list[str] = []

        def record(conn, cursor, statement, *rest) -> None:
            recorded.append(statement)

        event.listen(env, "before_cursor_execute", record)
        try:
            run()
        finally:
            event.remove(env, "before_cursor_execute", record)
        return len(recorded)

    def test_the_statement_count_does_not_depend_on_the_number_of_nodes(self, env, conn, db) -> None:  # noqa: F811
        seed_catalog(conn)
        few = self.count_statements(env, lambda: tree(db, "TP-LINK", "REDES", "10"))
        for n in range(150):
            seed.add_product(
                conn, 2000 + n, f"Q{n}", f"Producto Q{n}", marca="TP-Link", categoria="Redes", subcategoria_id=10
            )
            seed.add_item(conn, f"MLC{n:04d}", title="t")
            seed.add_link(conn, f"MLC{n:04d}", 2000 + n)
        many = self.count_statements(env, lambda: tree(db, "TP-LINK", "REDES", "10"))
        assert few == many and many <= 2  # one page query and one count
        assert len(tree(db, "TP-LINK", "REDES", "10").nodes) == 100

    def test_every_level_costs_the_same_fixed_number_of_statements(self, env, conn, db) -> None:  # noqa: F811
        seed_catalog(conn)
        paths = [(), ("TP-LINK",), ("TP-LINK", "REDES"), ("TP-LINK", "REDES", "10"), ("TP-LINK", "REDES", "10", "70")]
        counts = {path: self.count_statements(env, lambda p=path: tree(db, *p, familias=True)) for path in paths}
        assert set(counts.values()) == {2}, counts
