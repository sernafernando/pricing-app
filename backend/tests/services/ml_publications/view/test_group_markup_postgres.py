"""P7b.T1: the markup aggregates of the nodes of the Agrupado tree (owner decision 7), on Postgres.

A node shows how many publications it holds (`count`), how many of them have ANY negative variation
(`negative_count`) and the range of the markups of the node (`markup_min` / `markup_max`). There is NO average and
no Ads sum. The figures exist only when the caller may see margins (a `MarkupQuery` is given).

The maths is P2's and the set-wide computation is P6's (`compute_markups`): the pricing context and the shipping
batch are stubbed as in the P6 tests, so this file pins the aggregation and its consistency with `/items`.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.comision_config import SubcategoriaGrupo
from app.services.ml_daily_metrics.groups import NO_GROUP
from app.services.ml_publications.view import groups, listing, markup_service
from app.services.ml_publications.view.filters import MarkupFilter, parse_filter
from app.services.ml_publications.view.markup import unit_markup
from app.services.ml_publications.view.markup_service import AdsPlan, MarkupQuery
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_listing_postgres import STORES_DDL
from tests.services.ml_publications.view.test_unit_markup import make_ctx, make_inputs

pytestmark = pytest.mark.postgres

COST = {70: 40000.0, 71: 60000.0, 72: 50000.0, 73: 45000.0}


def worst_of(product: int) -> float:
    value = unit_markup(make_ctx(), make_inputs(producto_item_id=product, costo=COST[product]), {}).value
    assert value is not None
    return value


@pytest.fixture()
def conn(env):  # noqa: F811
    SubcategoriaGrupo.__table__.create(bind=env)
    with env.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(STORES_DDL))
        connection.execute(text(seed.PRICING_DDL))
        yield connection


@pytest.fixture()
def db(env, conn):  # noqa: F811
    session = sessionmaker(bind=env, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def envio_calls(monkeypatch):
    """The pricing context and the real-shipping batch, stubbed; the batch calls are recorded."""
    calls: list[list[int]] = []
    monkeypatch.setattr(markup_service, "build_pricing_context", lambda db: make_ctx())

    def fake(session, product_ids, **kwargs):
        calls.append(list(product_ids))
        return {}

    monkeypatch.setattr(markup_service, "resolver_costos_envio_batch", fake)
    return calls


def seed_catalog(conn) -> None:
    """Alfa: products 70 (positive markup) and 71 (negative). Beta: 72 (negative) and 73 (positive).

    MLA1 -> 70, MLA2 -> 71, MLA5 -> 72, MLA6 -> 73. MLA3 has no link. MLA4 has two variations, on 70 and on 71, and no
    item-level link: it sits in "Sin marca" and its range spans both products.
    """
    for item_id, brand in ((70, "Alfa"), (71, "Alfa"), (72, "Beta"), (73, "Beta")):
        seed.add_product(conn, item_id, f"C{item_id}", f"Producto {item_id}", marca=brand, subcategoria_id=3845)
        seed.add_cost(conn, item_id, COST[item_id])
    for number in range(1, 7):
        seed.add_item(conn, f"MLA{number}", listing_type_id="gold_pro", tags=["9x_campaign"], price=90000)
        seed.add_sale_price(conn, f"MLA{number}", 100000)
    seed.add_link(conn, "MLA1", 70)
    seed.add_link(conn, "MLA2", 71)
    seed.add_link(conn, "MLA5", 72)
    seed.add_link(conn, "MLA6", 73)
    seed.add_variation(conn, "MLA4", 11)
    seed.add_variation(conn, "MLA4", 12)
    seed.add_link(conn, "MLA4", 70, variation_id=11)
    seed.add_link(conn, "MLA4", 71, variation_id=12)


def tree(db: Session, *path: str, markup=None, familias: bool = False, **params):
    return groups.list_groups(db, parse_filter(**params), list(path), familias=familias, markup=markup)


def by_key(page) -> dict:
    return {node.key: node for node in page.nodes}


def figures(node) -> tuple:
    return node.negative_count, node.markup_min, node.markup_max


class FakeAds:
    def __init__(self, amounts) -> None:
        self._amounts = amounts

    def amounts(self, mla_ids, date_from, date_to):
        return self._amounts


class FakeUnits:
    def __init__(self, units) -> None:
        self._units = units

    def units_by_mla(self, db, mlas, date_from, date_to):
        return self._units


class TestRootAggregates:
    def test_a_node_counts_its_negative_publications_and_spans_the_range_of_its_markups(
        self, conn, db, envio_calls
    ) -> None:
        seed_catalog(conn)
        nodes = by_key(tree(db, markup=MarkupQuery(db)))
        # MLA4 is linked per variation to 70 and 71: it has their brand (S12g), one negative publication more
        assert nodes["ALFA"].count == 3
        assert figures(nodes["ALFA"]) == (2, worst_of(71), worst_of(70))
        assert nodes["BETA"].count == 2
        assert figures(nodes["BETA"]) == (1, worst_of(72), worst_of(73))

    def test_any_negative_variation_makes_the_publication_negative_and_every_unit_is_in_the_range(
        self, conn, db, envio_calls
    ) -> None:
        seed_catalog(conn)
        # MLA4 has one negative and one positive variation (linked to 71 and 70): under its brand it is ONE negative
        # publication whose range reaches both units; under each product, only that product's unit (#1870 B1)
        assert figures(by_key(tree(db, markup=MarkupQuery(db)))["ALFA"]) == (2, worst_of(71), worst_of(70))
        products = by_key(tree(db, "ALFA", "__none__", "3845", markup=MarkupQuery(db)))
        assert figures(products["70"]) == (0, worst_of(70), worst_of(70))
        assert figures(products["71"]) == (2, worst_of(71), worst_of(71))
        # MLA3, with no link, is the only publication without brand
        none = by_key(tree(db, markup=MarkupQuery(db)))[NO_GROUP]
        assert none.count == 1 and figures(none) == (0, None, None)

    def test_a_node_whose_publications_have_no_value_has_a_null_range_and_no_negatives(
        self, conn, db, envio_calls
    ) -> None:
        seed_catalog(conn)
        none = by_key(tree(db, markup=MarkupQuery(db), q="MLA3"))[NO_GROUP]
        assert none.count == 1
        assert figures(none) == (0, None, None)

    def test_there_is_no_average_and_no_ads_sum_on_a_node(self, conn, db, envio_calls) -> None:
        seed_catalog(conn)
        node = by_key(tree(db, markup=MarkupQuery(db)))["ALFA"]
        assert {f for f in vars(node) if "avg" in f or "mean" in f or "ads" in f or "promedio" in f} == set()

    def test_without_a_markup_query_the_figures_are_absent_and_nothing_is_computed(self, conn, db, envio_calls) -> None:
        seed_catalog(conn)
        nodes = by_key(tree(db))
        assert all(node.negative_count is None and node.markup_min is None for node in nodes.values())
        assert envio_calls == []


class TestEveryLevel:
    def test_product_and_publication_levels_aggregate_their_own_publications(self, conn, db, envio_calls) -> None:
        seed_catalog(conn)
        markup = MarkupQuery(db)
        products = by_key(tree(db, "ALFA", "__none__", "3845", markup=markup))
        # MLA4 (linked per variation to both) is in each, with only its units of that product
        assert figures(products["70"]) == (0, worst_of(70), worst_of(70))
        assert figures(products["71"]) == (2, worst_of(71), worst_of(71))

    def test_a_family_node_and_a_lone_publication_node_aggregate_too(self, conn, db, envio_calls) -> None:
        seed_catalog(conn)
        conn.execute(text("UPDATE ml_items SET family_id = 900, family_name = 'Fam' WHERE item_id = 'MLA1'"))
        for item_id in ("MLA8", "MLA9"):
            seed.add_item(conn, item_id, listing_type_id="gold_pro", tags=["9x_campaign"], price=90000)
            seed.add_sale_price(conn, item_id, 100000)
            seed.add_link(conn, item_id, 70)
        conn.execute(text("UPDATE ml_items SET family_id = 900, family_name = 'Fam' WHERE item_id = 'MLA8'"))
        nodes = by_key(tree(db, "ALFA", "__none__", "3845", "70", markup=MarkupQuery(db), familias=True))
        assert nodes["900"].kind == "familia" and nodes["900"].count == 2
        assert figures(nodes["900"]) == (0, worst_of(70), worst_of(70))
        assert nodes["MLA9"].kind == "item"
        assert figures(nodes["MLA9"]) == (0, worst_of(70), worst_of(70))

    def test_a_lone_publication_that_has_a_family_id_keeps_its_figures(self, conn, db, envio_calls) -> None:
        """Its family has no other member under this product (another product holds it): it is an `item` node keyed
        by its MLA, but the family level groups by the family id. The figures must follow the node, not the group."""
        seed_catalog(conn)
        for item_id, product in (("MLA10", 71), ("MLA11", 70)):
            seed.add_item(conn, item_id, listing_type_id="gold_pro", tags=["9x_campaign"], price=90000)
            seed.add_sale_price(conn, item_id, 100000)
            seed.add_link(conn, item_id, product)
        conn.execute(
            text("UPDATE ml_items SET family_id = 777, family_name = 'Fam' WHERE item_id IN ('MLA10','MLA11')")
        )
        page = tree(db, "ALFA", "__none__", "3845", "71", markup=MarkupQuery(db), familias=True)
        lone = by_key(page)["MLA10"]
        assert lone.kind == "item" and lone.count == 1
        assert figures(lone) == (1, worst_of(71), worst_of(71))
        negatives = MarkupQuery(db, MarkupFilter(negative=True))
        assert lone.negative_count == TestConsistencyWithItems.items_total(db, lone.params, negatives)

    def test_the_counts_of_a_level_still_add_up_with_the_figures_on(self, conn, db, envio_calls) -> None:
        seed_catalog(conn)
        page = tree(db, markup=MarkupQuery(db))
        assert sum(node.count for node in page.nodes) == 6
        assert sum(node.negative_count for node in page.nodes) == 3


class TestOneSetWidePass:
    def test_one_inputs_pass_and_one_shipping_batch_whatever_the_number_of_nodes(
        self,
        conn,
        db,
        envio_calls,
        env,  # noqa: F811
    ) -> None:
        seed_catalog(conn)
        statements: list[str] = []
        event.listen(env, "before_cursor_execute", lambda c, cur, stmt, *a: statements.append(stmt))
        tree(db, markup=MarkupQuery(db))
        assert len(envio_calls) == 1
        small = len(statements)
        for number in range(20, 40):  # twenty more brands: more nodes, the same statements
            seed.add_product(conn, 100 + number, f"X{number}", "x", marca=f"Marca {number}", subcategoria_id=3845)
            seed.add_item(conn, f"MLB{number}", listing_type_id="gold_pro", price=90000)
            seed.add_link(conn, f"MLB{number}", 100 + number)
        statements.clear()
        envio_calls.clear()
        page = tree(db, markup=MarkupQuery(db))
        assert page.total > 20 and len(statements) == small and len(envio_calls) == 1


class TestWhichPathPricesTheNodes:
    """A small slice (a deep level) is priced by the ids of its publications; a slice too big for an id list is priced
    by the whole filter. Either way the figures are the same: P6 pins that both paths give identical values."""

    def spy(self, monkeypatch):
        calls: list[dict] = []
        real = groups.compute_markups

        def spy(db, pricing_db, **kwargs):
            calls.append(kwargs)
            return real(db, pricing_db, **kwargs)

        monkeypatch.setattr(groups, "compute_markups", spy)
        return calls

    def test_a_small_slice_is_priced_by_its_ids(self, conn, db, envio_calls, monkeypatch) -> None:
        seed_catalog(conn)
        calls = self.spy(monkeypatch)
        tree(db, markup=MarkupQuery(db))
        assert "item_ids" in calls[0] and "f" not in calls[0]

    def test_a_slice_over_the_limit_is_priced_by_the_whole_filter_with_the_same_figures(
        self, conn, db, envio_calls, monkeypatch
    ) -> None:
        seed_catalog(conn)
        by_ids = {k: figures(n) for k, n in by_key(tree(db, markup=MarkupQuery(db))).items()}
        monkeypatch.setattr(groups, "ITEM_IDS_MAX", 1)
        calls = self.spy(monkeypatch)
        by_filter = {k: figures(n) for k, n in by_key(tree(db, markup=MarkupQuery(db))).items()}
        assert "f" in calls[0] and "item_ids" not in calls[0]
        assert by_filter == by_ids


class TestStringOrderIsLocaleIndependent:
    def test_the_figures_follow_the_nodes_the_page_returns_under_a_collation_free_order(
        self, conn, db, envio_calls
    ) -> None:
        seed_catalog(conn)
        keys = [node.key for node in tree(db, markup=MarkupQuery(db)).nodes]
        assert keys == ["ALFA", "BETA", NO_GROUP]


class TestConsistencyWithItems:
    @staticmethod
    def items_total(db, params: dict, markup: MarkupQuery) -> int:
        f = parse_filter(**params)
        sort = listing.parse_sort(None, None)
        return listing.list_items(db, f, sort, 1, 0, events=True, markup=markup).total

    def walk(self, db, markup, path=()):
        """Every node of the tree down to the products (depth first)."""
        for node in tree(db, *path, markup=markup).nodes:
            yield node
            if not node.leaf:
                yield from self.walk(db, markup, (*path, node.key))

    def test_negative_count_is_the_items_markup_neg_total_of_the_node_at_every_level(
        self, conn, db, envio_calls
    ) -> None:
        seed_catalog(conn)
        plain = MarkupQuery(db)
        negatives = MarkupQuery(db, MarkupFilter(negative=True))
        seen = 0
        for node in self.walk(db, plain):
            assert node.negative_count == self.items_total(db, node.params, negatives), node.params
            seen += 1
        assert seen >= 10

    def test_with_restar_publicidad_it_still_equals_the_items_markup_neg_total(self, conn, db, envio_calls) -> None:
        seed_catalog(conn)
        # Ads turns MLA1 and MLA6 negative; MLA2 has Ads cost and no sales: its markup has no value at all
        ads = AdsPlan(
            FakeAds({"MLA1": 400000.0, "MLA2": 5000.0, "MLA5": 1000.0, "MLA6": 200000.0}),
            "costo_extra",
            date(2026, 9, 1),
            date(2026, 9, 30),
            units=FakeUnits({"MLA1": 4, "MLA5": 5, "MLA6": 2}),
        )
        plain_total = sum(node.negative_count for node in tree(db, markup=MarkupQuery(db)).nodes)
        plain = MarkupQuery(db, ads=ads)
        negatives = MarkupQuery(db, MarkupFilter(negative=True), ads=ads)
        nodes = list(self.walk(db, plain))
        assert sum(node.negative_count for node in tree(db, markup=plain).nodes) != plain_total  # Ads moved it
        for node in nodes:
            assert node.negative_count == self.items_total(db, node.params, negatives), node.params


def seed_categorized(conn) -> None:
    """`seed_catalog` with categories whose names hold the separators: `,` and `%` (percent-escaped on the wire)
    and `|` (the separator of a `subcategoria_categoria` key). Product 73 has no subcategory."""
    categories = {70: "Camaras, Fotos|Pro", 71: "Camaras, Fotos|Pro", 72: "100% Audio", 73: "100% Audio"}
    for item_id, categoria in categories.items():
        subcategoria = None if item_id == 73 else 3845
        seed.add_product(
            conn, item_id, f"C{item_id}", f"Producto {item_id}", categoria=categoria, subcategoria_id=subcategoria
        )
        seed.add_cost(conn, item_id, COST[item_id])
    for number in range(1, 7):
        seed.add_item(conn, f"MLA{number}", listing_type_id="gold_pro", tags=["9x_campaign"], price=90000)
        seed.add_sale_price(conn, f"MLA{number}", 100000)
    for item_id, product in (("MLA1", 70), ("MLA2", 71), ("MLA5", 72), ("MLA6", 73)):
        seed.add_link(conn, item_id, product)


class TestMarkupByDimension:
    """Under every dimension a node's figures are those of the publications its `params` select in `/items`: the
    markup path maps each publication back to its node by the node's key, which for a category or a subcategory in
    its category is the escaped text (`_members`); a key that failed to map would silently drop publications."""

    def walk(self, db, dimension: str, markup, path=()):
        page = groups.list_groups(db, parse_filter(), list(path), markup=markup, dimension=dimension)
        for node in page.nodes:
            yield node
            if not node.leaf:
                yield from self.walk(db, dimension, markup, (*path, node.key))

    @staticmethod
    def items_figures(db, params: dict) -> tuple:
        sort = listing.parse_sort(None, None)
        page = listing.list_items(db, parse_filter(**params), sort, 50, 0, events=True, markup=MarkupQuery(db))
        blocks = [item["markup"] for item in page.items]
        lows = [b["min"] for b in blocks if b["min"] is not None]
        highs = [b["max"] for b in blocks if b["max"] is not None]
        return sum(b["any_negative"] for b in blocks), min(lows, default=None), max(highs, default=None)

    @pytest.mark.parametrize("dimension", ["categoria", "subcategoria"])
    def test_every_node_has_the_figures_of_its_items_set(self, conn, db, envio_calls, dimension) -> None:
        seed_categorized(conn)
        nodes = list(self.walk(db, dimension, MarkupQuery(db)))
        for node in nodes:
            shown = (
                node.negative_count,
                None if node.markup_min is None else round(node.markup_min, 2),
                None if node.markup_max is None else round(node.markup_max, 2),
            )
            assert shown == self.items_figures(db, node.params), (node.kind, node.key)
        # the escaped keys really carry figures (a publication dropped by the key mapping would leave 0 / None)
        expected_negatives = (
            {"CAMARAS%2C FOTOS|PRO": 1, "100%25 AUDIO": 1}
            if dimension == "categoria"
            else {"3845|CAMARAS%2C FOTOS|PRO": 1, "3845|100%25 AUDIO": 1, f"{NO_GROUP}|100%25 AUDIO": 0}
        )
        roots = {node.key: node for node in nodes if node.kind != "producto"}
        assert {key: roots[key].negative_count for key in expected_negatives} == expected_negatives
        assert all(roots[key].markup_min is not None for key in expected_negatives)


def seed_stores_and_pms(conn) -> None:
    """Products 70 (positive) and 71 (negative) are Alfa/Redes, 72 (negative) Beta/Redes, 73 (positive) Alfa/Video.

    Stores: MLA1 in store 1 and MLA2 in store 3, which share the clave `A,B` (a comma: the key travels escaped);
    MLA5 in store 2, with no row; MLA6 in no store. PMs: Alfa/Redes is listed for PM 7 AND (another spelling) PM 5,
    so the tree gives it to the lowest id (5) only; Beta/Redes is PM 7's; Alfa/Video has no PM.
    """
    brands = {70: ("Alfa", "Redes"), 71: ("Alfa", "Redes"), 72: ("Beta", "Redes"), 73: ("Alfa", "Video")}
    for item_id, (marca, categoria) in brands.items():
        seed.add_product(conn, item_id, f"C{item_id}", f"Producto {item_id}", marca=marca, categoria=categoria)
        seed.add_cost(conn, item_id, COST[item_id])
    stores = {"MLA1": 1, "MLA2": 3, "MLA5": 2}
    for number in range(1, 7):
        item_id = f"MLA{number}"
        seed.add_item(
            conn,
            item_id,
            listing_type_id="gold_pro",
            tags=["9x_campaign"],
            price=90000,
            official_store_id=stores.get(item_id),
        )
        seed.add_sale_price(conn, item_id, 100000)
    for item_id, product in (("MLA1", 70), ("MLA2", 71), ("MLA5", 72), ("MLA6", 73)):
        seed.add_link(conn, item_id, product)
    for store_id, nombre in ((1, "Coma"), (3, "Coma Outlet")):
        conn.execute(
            text("INSERT INTO ml_tiendas_oficiales (store_id, nombre, clave, orden) VALUES (:s, :n, 'A,B', :s)"),
            {"s": store_id, "n": nombre},
        )
    conn.execute(text("CREATE TABLE marcas_pm (id serial PRIMARY KEY, marca text, categoria text, usuario_id integer)"))
    conn.execute(text("CREATE TABLE usuarios (id integer PRIMARY KEY, nombre text)"))
    conn.execute(
        text(
            "INSERT INTO marcas_pm (marca, categoria, usuario_id) VALUES "
            "('Alfa', 'Redes', 7), ('ALFA', 'REDES', 5), ('Beta', 'Redes', 7)"
        )
    )
    conn.execute(text("INSERT INTO usuarios (id, nombre) VALUES (5, 'Ana'), (7, 'Beto')"))


class TestMarkupByStoreAndPm(TestMarkupByDimension):
    """The same contract under `tienda` (a clave node covers several store ids) and `pm` (a pair listed for two PMs
    belongs to one): the figures are those of the node's `/items` set, `tiendas` and `pm_grupo` included."""

    @pytest.mark.parametrize(
        "dimension, expected_negatives",
        [
            ("tienda", {"c:A%2CB": 1, "s:2": 1}),  # MLA2 is negative and MLA1 positive; MLA5 negative
            ("pm", {"5": 1, "7": 1}),  # 5: MLA1 and MLA2 (never 7's too); 7: MLA5
        ],
    )
    def test_every_node_has_the_figures_of_its_items_set(  # type: ignore[override]
        self, conn, db, envio_calls, dimension, expected_negatives
    ) -> None:
        seed_stores_and_pms(conn)
        nodes = list(self.walk(db, dimension, MarkupQuery(db)))
        for node in nodes:
            shown = (
                node.negative_count,
                None if node.markup_min is None else round(node.markup_min, 2),
                None if node.markup_max is None else round(node.markup_max, 2),
            )
            assert shown == self.items_figures(db, node.params), (node.kind, node.key)
        roots = {node.key: node for node in nodes if node.kind == dimension}
        assert {key: roots[key].negative_count for key in expected_negatives} == expected_negatives
        assert all(roots[key].markup_min is not None for key in expected_negatives)
        if dimension == "tienda":
            assert roots["c:A%2CB"].params == {"tiendas": "1,3"} and roots["c:A%2CB"].count == 2
        else:
            assert (roots["5"].count, roots["7"].count) == (2, 1)
