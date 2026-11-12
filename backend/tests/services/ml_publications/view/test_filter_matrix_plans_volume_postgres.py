"""Every Publicaciones ML filter, alone, with a promo filter, and all of them at once, on the 25k volume seed: no read
of the screen (list page, facets, Agrupado roots and a branch, the Producto view's ids, the KPI strip) may run a
per-row plan over a big table.

Asserted on `EXPLAIN (ANALYZE, FORMAT JSON)` of every statement those reads send (with the view's own
`listing.bound`: `statement_timeout`, JIT off):

- no index scan of `ix_ml_items_last_trigger` looks an `item_id` up (that index leads with
  `last_trigger_received_at`: such a probe walks the whole index once per outer row; the 2026-11-12 incident);
- no sequential scan of a big table runs more than once (a correlated subquery re-scanning a table per row);
- no JIT section.

Timings are printed (`-s`), never asserted (a shared CI box). The plan shape is what regresses loudly.
"""

from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import String, any_, event, false, literal, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session, sessionmaker

from app.services.ml_publications.view import filters, groups, listing, products, stats
from app.services.ml_publications.view.filters import PublicationFilter, parse_filter
from tests.services.ml_publications.view import seed as view_seed
from tests.services.ml_publications.view.test_view_volume_postgres import ITEMS, seeded  # noqa: F401

pytestmark = [pytest.mark.postgres, pytest.mark.volume]

PROMO_SCOPE = frozenset(f"MLA{1000000 + i}" for i in range(1, ITEMS) if i % 3 == 0)
BIG_TABLES = frozenset(
    {
        "ml_items",
        "ml_item_product_links",
        "ml_item_variations",
        "productos_erp",
        "productos_pricing",
        "ml_item_sale_prices",
        "ml_user_product_stock",
        "ml_item_events",
        "ofertas_ml",
        "tienda_nube_productos",
        "auditoria",
        "marcas_pm",
    }
)
# Every filter of the screen with a value that selects part of the seed. `colores` is left out: the router resolves
# it to product / MLA ids first (`colors.resolve_color_filter`), and those ids reach the query as the same
# `= ANY(...)` arrays `producto` and the promo set already exercise.
FILTERS: dict[str, dict[str, Any]] = {
    "q text": dict(q="router"),
    "q product name": dict(q="Producto de volumen 12"),
    "q mla": dict(q="MLA1000040"),
    "q code": dict(q="7790000000012"),
    "estado": dict(estado="active"),
    "estado gone": dict(estado="gone"),
    "estado_excluir": dict(estado_excluir="paused,closed"),
    "tiendas": dict(tiendas="2645"),
    "tiendas none": dict(tiendas="none"),
    "marcas": dict(marcas="TP-Link,Sony"),
    "marcas none": dict(marcas="__none__"),
    "categorias": dict(categorias="Cat0"),
    "subcategorias": dict(subcategorias="1,3"),
    "pms": dict(pms="3"),
    "pm_grupo": dict(pm_grupo="3"),
    "pm_grupo none": dict(pm_grupo="__none__"),
    "familia": dict(familia="5"),
    "producto": dict(producto="800012"),
    "sin_producto": dict(sin_producto=True),
    "tipo premium": dict(tipo="premium"),
    "tipo catalogo": dict(tipo="catalogo"),
    "tipo full": dict(tipo="full"),
    "vinculo": dict(vinculo="auto,manual"),
    "vinculo sku_divergente": dict(vinculo="sku_divergente"),
    "stock sin_stock": dict(stock="sin_stock"),
    "stock full_sin_stock": dict(stock="full_sin_stock"),
    "stock erp": dict(stock="erp_con_stock"),
    "evento": dict(evento="price_changed", evento_desde="7d"),
    "con_rebate": dict(con_rebate=True),
    "sin_rebate": dict(con_rebate=False),
    "con_oferta": dict(con_oferta=True),
    "con_oferta por producto": dict(con_oferta=True, oferta_por_producto=True),
    "sin_oferta": dict(con_oferta=False),
    "con_web_transf": dict(con_web_transf=True),
    "tn_con_descuento": dict(tn_con_descuento=True),
    "tn_no_publicado": dict(tn_no_publicado=True),
    "out_of_cards": dict(out_of_cards=True),
    "con_precio": dict(con_precio=True),
    "nuevos": dict(nuevos_ultimos_7_dias=True),
    "estado_mla activa": dict(estado_mla="activa"),
    "estado_mla pausada": dict(estado_mla="pausada"),
    "markup clasica": dict(markup_clasica_positivo=True),
    "markup oferta negativo": dict(markup_oferta_positivo=False),
    "audit": dict(audit_usuarios="1", audit_fecha_desde="2020-01-01 00:00"),
    "hay_mejores_ofertas": dict(hay_mejores_ofertas=True),
}
# Every filter at once, where they can coexist (one value per axis, the broad ones).
ALL = dict(
    q="Producto",
    estado="active,paused",
    estado_excluir="closed",
    tiendas="2645,57997",
    marcas="TP-Link,Sony,Tenda",
    categorias="Cat0,Cat1",
    subcategorias="1,2,3,4",
    pms="3",
    tipo="premium,clasica",
    vinculo="auto,manual",
    stock="erp_con_stock",
    con_rebate=True,
    con_oferta=False,
    con_web_transf=False,
    out_of_cards=False,
    con_precio=True,
    estado_mla="activa",
    markup_clasica_positivo=True,
    hay_mejores_ofertas=None,
)
TREES = ("marca", "categoria", "subcategoria", "pm", "tienda")
# CI walks one Agrupado tree per filter, in turn, so every tree is walked under every kind of filter; the full matrix
# (every tree for every filter, about 47 min on the test server) runs on demand with PUBML_FILTER_MATRIX_FULL=1.
FULL = pytest.mark.skipif(
    not os.environ.get("PUBML_FILTER_MATRIX_FULL"), reason="the full matrix: run it with PUBML_FILTER_MATRIX_FULL=1"
)
TREE_OF = {name: (TREES[index % len(TREES)],) for index, name in enumerate(FILTERS)}
# (name, filter, promo set on top, Agrupado trees walked)
SCENARIOS = [
    *(pytest.param(name, kwargs, False, TREE_OF[name], id=name) for name, kwargs in FILTERS.items()),
    pytest.param("all", ALL, False, TREES, id="all"),
    pytest.param("all + promo", ALL, True, TREES, id="all + promo"),
    pytest.param("promo", {}, True, TREES, id="promo"),
    pytest.param("none", {}, False, TREES, id="none"),
    *(
        pytest.param(f"{name} every tree", kwargs, False, TREES, marks=FULL, id=f"{name} every tree")
        for name, kwargs in FILTERS.items()
    ),
]
# Each filter with the promo set on top (the #2233 incident's shape), in its own module so CI runs it on another worker.
PROMO_SCENARIOS = [
    pytest.param(f"{name} + promo", kwargs, True, ("marca",), id=f"{name} + promo") for name, kwargs in FILTERS.items()
]
PM_DDL = (
    "CREATE TABLE marcas_pm (id serial PRIMARY KEY, marca varchar(100) NOT NULL, categoria varchar(100) NOT NULL, "
    "usuario_id integer, fecha_asignacion timestamptz, fecha_modificacion timestamptz)",
    "INSERT INTO marcas_pm (marca, categoria, usuario_id) VALUES ('TP-Link', 'Cat0', 3), ('TP-Link', 'Cat1', 3), "
    "('TP-Link', 'Cat2', 3), ('Hikvision', 'Cat0', 3), ('Hikvision', 'Cat2', 3), ('Tenda', 'Cat1', 3), "
    "('Tenda', 'Cat2', 3), ('Epson', 'Cat0', 3), ('Epson', 'Cat1', 3), ('Sony', 'Cat1', 3), ('Sony', 'Cat2', 3), "
    "('Nope', 'Cat0', 3), ('Sony', 'Cat0', 4)",
)


PRODUCTION_INDEXES = (
    "CREATE INDEX ix_ofertas_ml_mla ON ofertas_ml (mla)",
    "CREATE INDEX ix_ofertas_ml_fecha_desde ON ofertas_ml (fecha_desde)",
    "CREATE INDEX ix_ofertas_ml_fecha_hasta ON ofertas_ml (fecha_hasta)",
    "CREATE INDEX ix_tienda_nube_productos_item_id ON tienda_nube_productos (item_id)",
    "CREATE INDEX ix_tienda_nube_productos_product_id ON tienda_nube_productos (product_id)",
    "CREATE INDEX ix_auditoria_item_id ON auditoria (item_id)",
    "CREATE INDEX ix_auditoria_fecha ON auditoria (fecha)",
    "CREATE INDEX ix_auditoria_tipo_accion ON auditoria (tipo_accion)",
    "CREATE INDEX ix_marcas_pm_marca ON marcas_pm (marca)",
    "CREATE INDEX ix_marcas_pm_categoria ON marcas_pm (categoria)",
)


def _presence(conn) -> None:
    """The tables the presence, markup and audit filters read, at the seed's volume."""
    for ddl in (*view_seed.PRESENCE_DDL, view_seed.MARKUP_DDL, *view_seed.AUDIT_DDL, *PM_DDL):
        conn.execute(text(ddl))
    conn.execute(
        text(
            "UPDATE productos_pricing SET participa_rebate = item_id % 3 = 0, participa_web_transferencia = "
            "item_id % 4 = 0, out_of_cards = item_id % 11 = 0, markup_calculado = item_id % 7 - 2, "
            "markup_rebate = item_id % 5 - 1, markup_oferta = item_id % 9 - 3, markup_web_real = item_id % 4 - 1"
        )
    )
    # ERP stock on two products of three (the stock chips and "TN no publicado" read it).
    conn.execute(text("UPDATE productos_erp SET stock = item_id % 3"))
    # One automatic link of ten whose stored suggestion is another product (`vinculo=sku_divergente`).
    conn.execute(
        text(
            "UPDATE ml_item_product_links SET suggestion_status = 'linked', suggested_producto_item_id = "
            "producto_item_id + 1 WHERE source = 'sku_auto' AND substr(item_id, 4)::int % 10 = 0"
        )
    )
    conn.execute(
        text(
            "INSERT INTO ofertas_ml (mla, fecha_desde, fecha_hasta, pvp_seller) SELECT 'MLA' || (1000000 + i), "
            "current_date - 3, current_date + 3, 1000 FROM generate_series(1, :items) AS i WHERE i % 10 = 0"
        ),
        {"items": ITEMS},
    )
    conn.execute(
        text(
            "INSERT INTO tienda_nube_productos (product_id, variant_id, price, promotional_price, item_id, activo) "
            "SELECT i, 1, 1000, CASE WHEN item_id % 8 = 0 THEN 900 END, item_id, true FROM productos_erp, "
            "generate_series(1, 1) AS i WHERE item_id % 4 = 0"
        )
    )
    conn.execute(text("INSERT INTO usuarios (id, nombre, username) VALUES (1, 'Uno', 'uno'), (2, 'Dos', 'dos')"))
    conn.execute(
        text(
            "INSERT INTO auditoria (item_id, usuario_id, tipo_accion, fecha) SELECT 800001 + i % 6000, 1 + i % 2, "
            "'MODIFICAR_PRECIO_CLASICA', now() - (i || ' minutes')::interval FROM generate_series(1, 30000) AS i"
        )
    )
    conn.execute(
        text(
            "INSERT INTO ml_item_seller_promotions (item_id, candidate_count, started_count, hay_mejores_ofertas) "
            "SELECT 'MLA' || (1000000 + i), 1, 0, i % 50 = 5 FROM generate_series(1, :items) AS i WHERE i % 5 = 0"
        ),
        {"items": ITEMS},
    )
    # The indexes production has on them (their models' `index=True`; the seed DDL above declares none).
    for ddl in PRODUCTION_INDEXES:
        conn.execute(text(ddl))
    for table in (
        "productos_erp",
        "ml_item_product_links",
        "productos_pricing",
        "ofertas_ml",
        "tienda_nube_productos",
        "auditoria",
        "marcas_pm",
        "ml_item_seller_promotions",
    ):
        conn.execute(text(f"ANALYZE {table}"))


MIGRATION = (
    Path(__file__).resolve().parents[4]
    / "alembic"
    / "versions"
    / "20261112_productos_erp_normalized_brand_category_index.py"
)


def _apply_migration(engine) -> None:
    """The REAL `productos_erp` normalized brand / category index (and its ANALYZE)."""
    spec = importlib.util.spec_from_file_location("productos_erp_normalized_index_matrix", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx), ctx.begin_transaction():
            migration.upgrade()


@pytest.fixture(scope="module")
def world(seeded):  # noqa: F811
    with seeded.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        _presence(conn)
    _apply_migration(seeded)
    return seeded


@pytest.fixture()
def session(world) -> Iterator[Session]:
    session = sessionmaker(bind=world, autocommit=False, autoflush=False)()
    try:
        listing.bound(session)  # as every read of the router: statement_timeout and jit = off
        yield session
    finally:
        session.rollback()
        session.close()


def build(session: Session, kwargs: dict[str, Any], promo: bool) -> PublicationFilter:
    f = parse_filter(**kwargs)
    if promo:
        f = replace(f, mla_scope=PROMO_SCOPE)
    return listing.resolve_pm_pairs(session, f)


def walks(session: Session, f: PublicationFilter, dimension: str) -> list[list[str]]:
    """The paths a viewer opens in the Agrupado tree grouped by `dimension`: the roots, then down to the products by
    the biggest node of each level, and the "Sin ..." root's children when there is one."""
    paths: list[list[str]] = [[]]
    path: list[str] = []
    for _ in range(len(groups.tree_of(dimension).levels) - 1):
        nodes = groups.list_groups(session, f, path, limit=100, offset=0, dimension=dimension).nodes
        named = [n for n in nodes if n.key != groups.NO_GROUP]
        if any(n.key == groups.NO_GROUP for n in nodes) and not path:
            paths.append([groups.NO_GROUP])
        if not named:
            break
        path = [*path, max(named, key=lambda n: n.count).key]
        paths.append(path)
    return paths


def reads(session: Session, f: PublicationFilter, trees: tuple[str, ...] = ("marca",)) -> list[tuple[str, Callable]]:
    """The reads a filter change triggers: the list page, its facets, the Producto view's ids, the KPI strip, and the
    Agrupado tree of each of `trees`, walked down to its products."""
    found: list[tuple[str, Callable]] = [
        ("items", lambda: listing.list_items(session, f, listing.parse_sort(None, None), 50, 0, events=True)),
        ("facets", lambda: listing.facets(session, f, None)),
        ("product ids", lambda: products.product_ids(session, f)),
        ("kpis", lambda: stats.compute(session, f, markups=True)),
    ]
    for dimension in trees:
        for path in walks(session, f, dimension):
            found.append(
                (
                    f"{dimension} tree {'/'.join(path) or 'roots'}",
                    lambda path=path, dimension=dimension: groups.list_groups(
                        session, f, path, limit=100, offset=0, dimension=dimension
                    ),
                )
            )
    return found


def statements(session: Session, call: Callable[[], Any]) -> list[tuple[str, Any]]:
    sent: list[tuple[str, Any]] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            sent.append((statement, parameters))

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", record)
    try:
        call()
    finally:
        event.remove(bind, "before_cursor_execute", record)
    return sent


def analyzed(session: Session, statement: str, parameters: Any) -> tuple[dict[str, Any], float]:
    cursor = session.connection().connection.cursor()
    try:
        cursor.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + statement, parameters)
        document = cursor.fetchone()[0]
    finally:
        cursor.close()
    document = (json.loads(document) if isinstance(document, str) else document)[0]
    return document, document["Execution Time"]


def nodes(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield node
    for child in node.get("Plans", ()):
        yield from nodes(child)


def per_row_plans(document: dict[str, Any]) -> list[str]:
    """What runs once per outer row over a big table: a whole-index probe of the activity index by `item_id`, or a
    sequential scan executed more than once."""
    found = []
    for node in nodes(document["Plan"]):
        cond = node.get("Index Cond", "")
        if (
            node.get("Index Name") == "ix_ml_items_last_trigger"
            and "item_id" in cond
            and "last_trigger_received_at" not in cond
            and node.get("Actual Loops", 0) > 1
        ):
            found.append(f"activity index probed by item_id x{node['Actual Loops']}")
        if (
            node.get("Node Type") == "Seq Scan"
            and node.get("Relation Name") in BIG_TABLES
            and node.get("Actual Loops", 0) > 1
        ):
            found.append(f"seq scan of {node['Relation Name']} x{node['Actual Loops']}")
    if "JIT" in document:
        found.append("JIT")
    return found


@pytest.mark.parametrize("name, kwargs, promo, trees", SCENARIOS)
def test_no_read_runs_a_per_row_plan(session, name, kwargs, promo, trees) -> None:
    assert_no_per_row_plan(session, name, kwargs, promo, trees)


def assert_no_per_row_plan(session: Session, name: str, kwargs: dict[str, Any], promo: bool, trees: tuple) -> None:
    f = build(session, kwargs, promo)
    found: dict[str, list[str]] = {}
    worst, where = 0.0, ""
    for label, read in reads(session, f, trees):
        for statement, parameters in statements(session, read):
            document, ms = analyzed(session, statement, parameters)
            if ms > worst:
                worst, where = ms, label
            bad = per_row_plans(document)
            if bad:
                found.setdefault(label, []).extend(bad)
    print(f"\nMATRIX {name:34} worst {worst:7.1f} ms ({where}) {found or ''}")
    assert found == {}


def test_the_seed_has_rows_for_every_filter(session) -> None:
    """A filter that selects nothing would prove nothing about its plan."""
    totals = {
        name: listing.list_items(
            session, build(session, kwargs, False), listing.parse_sort(None, None), 50, 0, events=True
        ).total
        for name, kwargs in FILTERS.items()
    }
    empty = [name for name, total in totals.items() if total == 0]
    assert not empty, f"filters with no row in the seed: {empty}"


def comparable(value: Any) -> Any:
    """A read's answer, without what only says how it was computed."""
    if isinstance(value, groups.GroupsPage):
        return [(n.key, n.label, n.count) for n in value.nodes], value.total
    return value


def answers(session: Session, f: PublicationFilter, trees: tuple[str, ...]) -> dict[str, Any]:
    return {label: comparable(read()) for label, read in reads(session, f, trees)}


def previous_shape(monkeypatch) -> None:
    """The query shapes main had: the promo set as a bare `item_id = ANY`, the tree's ancestors compared on their
    CASE key, and `pm_grupo` read from the correlated `pm_pairs` subquery."""
    resolve = listing.resolve_pm_pairs

    def unresolved_group(db, f):
        return replace(resolve(db, f), pm_group_pairs=None)

    def key_is(tree, depth, key):
        keys = [tree.dimensions[name].key for name in tree.group_levels] + [groups.product_key()]
        return keys[depth] == groups._raw_key(tree.levels[depth], key)

    monkeypatch.setattr(
        filters, "_item_in", lambda m: filters.T.i.item_id == any_(literal(sorted(m), ARRAY(String))) if m else false()
    )
    monkeypatch.setattr(groups, "_key_is", key_is)
    for module in (listing, groups, products, stats):
        monkeypatch.setattr(module, "resolve_pm_pairs", unresolved_group)


# The oracle runs in `test_filter_matrix_oracle_volume_postgres.py` (another CI worker). Each filter + promo set
# costs about 6 min there, so it runs with the full matrix only.
ORACLE = [
    *(pytest.param(name, kwargs, False, TREE_OF[name], id=name) for name, kwargs in FILTERS.items()),
    pytest.param("all", ALL, False, TREES, id="all"),
    pytest.param("all + promo", ALL, True, TREES, id="all + promo"),
    *(
        pytest.param(f"{name} + promo", kwargs, True, ("marca",), marks=FULL, id=f"{name} + promo")
        for name, kwargs in FILTERS.items()
    ),
    *(
        pytest.param(f"{name} every tree", kwargs, False, TREES, marks=FULL, id=f"{name} every tree")
        for name, kwargs in FILTERS.items()
    ),
]


def assert_previous_answers(session: Session, monkeypatch, kwargs: dict[str, Any], promo: bool, trees: tuple) -> None:
    """Every read answers what the previous shapes answered."""
    session.execute(text("SET LOCAL statement_timeout = '120s'"))  # the previous shapes are the slow ones
    now = answers(session, build(session, kwargs, promo), trees)
    previous_shape(monkeypatch)
    assert now == answers(session, build(session, kwargs, promo), trees)
