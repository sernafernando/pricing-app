"""Loader helpers for the real ML captures under tests/fixtures/ml_publications/.

Every payload used by the ml_publications tests comes from these files (real
production captures, 2026-10-06). Tests that need a transition mutate a deep
copy of a real payload by exactly one field and say so in their docstring.
"""

from __future__ import annotations

import atexit
import copy
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

from tests._marcas_visibles import MARCAS_VISIBLES_DDL

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "ml_publications"

BULK_CAPTURE = "items_bulk_capture_20261006_015628.json"
ITEM_SAMPLES = "items_bulk_samples_20261006.json"
ITEM_WITH_VARIATIONS = "item_with_variations_MLA1207279308.json"


def load_fixture(name: str) -> Any:
    with (FIXTURES_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def bulk_call(name: str) -> Any:
    """Body of one named call of the `/items/bulk` capture (deep copy)."""
    for call in load_fixture(BULK_CAPTURE)["calls"]:
        if call["name"] == name:
            return copy.deepcopy(call["body"])
    raise KeyError(name)


def sample_item(item_id: str) -> dict:
    """Full item body (the `body` of a 200 `/items/bulk` element) captured for `item_id`."""
    for element in load_fixture(ITEM_SAMPLES)["elements"]:
        if element["id"] == item_id:
            return copy.deepcopy(element["body"])
    raise KeyError(item_id)


def bulk_item(item_id: str) -> dict:
    """Full item body from the first `/items/bulk` capture (MLA935110613, MLA934406852)."""
    for element in bulk_call("bulk_full"):
        if element.get("id") == item_id:
            return copy.deepcopy(element["body"])
    raise KeyError(item_id)


@pytest.fixture
def fixture_loader():
    return load_fixture


KEYED_ARRAYS = "keyed_arrays_promotions_visits_20261006.json"


def keyed_sample(name: str) -> Any:
    """Real promotions list / visits body used to exercise the natural-key overrides."""
    return copy.deepcopy(load_fixture(KEYED_ARRAYS)[name])


def _warm_view_aliases() -> None:
    """Resolve every column of the view's module-level aliases (`filters.T`) once, with the real Postgres types.

    SQLAlchemy keeps the column types an alias saw the first time each column was touched, and
    `_restore_pristine_pg_types` cannot reach that copy. A test that touches `T` while the columns carry the SQLite
    stand-ins (`_patch_pg_types_for_sqlite`, what every Postgres fixture's teardown leaves) would leave `sub_status`
    / `tags` as JSON for the rest of its xdist worker, and every later `= ANY` / `&&` on them fails: CI on #2365, a
    fixture-less `listing.row_columns()` test that happened to be its worker's first touch. Run at import (test
    collection, before any fixture), the types are put back for it and left as they were found."""
    from sqlalchemy import inspect
    from sqlalchemy.orm.util import AliasedClass

    from app.services.ml_publications.view.filters import T
    from tests.conftest import _PRISTINE_PG_COLUMN_TYPES

    aliases = [value for value in vars(T).values() if isinstance(value, AliasedClass)]
    tables = {table for alias in aliases for table in inspect(alias).mapper.tables}
    found = {column: column.type for table in tables for column in table.columns if column in _PRISTINE_PG_COLUMN_TYPES}
    for column in found:
        column.type = _PRISTINE_PG_COLUMN_TYPES[column]
    try:
        for alias in aliases:
            for prop in inspect(alias).mapper.column_attrs:
                getattr(alias, prop.key).__clause_element__()
    finally:
        for column, type_ in found.items():
            column.type = type_


_warm_view_aliases()


# --- Postgres schema for the infrastructure tests (settings store, queue) -----------------


def _create_publication_map(target, connection, **kwargs) -> None:
    """`publicaciones_ml` from its real model, right after `productos_erp` (its foreign key target), and the banlists."""
    from sqlalchemy import text

    from app.models.publicacion_ml import PublicacionML

    PublicacionML.__table__.create(bind=connection)
    # Productos' two banlists, which the Producto view's "Sin MLA" leaves out (`filters.product_conditions`). Their
    # real tables carry a user foreign key, and these schemas have no `usuarios`: same columns, no foreign key.
    for ddl in BANLIST_DDL:
        connection.execute(text(ddl))
    # Every brand option list reads the brands-without-stock exceptions (`app.services.marcas_visibles`).
    connection.execute(text(MARCAS_VISIBLES_DDL))
    # The cost every markup reads is costo SI (`costo_si.lote.actual`), which reads these beside the catalog.
    for ddl in COSTO_SI_READER_DDL:
        connection.execute(text(ddl))


BANLIST_DDL = (
    "CREATE TABLE producto_banlist (id serial PRIMARY KEY, item_id integer UNIQUE, ean varchar(50) UNIQUE, "
    "motivo varchar(500), activo boolean NOT NULL DEFAULT true, usuario_id integer, "
    "fecha_creacion timestamptz DEFAULT now(), fecha_modificacion timestamptz)",
    "CREATE TABLE items_sin_mla_banlist (id serial PRIMARY KEY, item_id integer UNIQUE NOT NULL, motivo text, "
    "usuario_id integer, fecha_creacion timestamptz DEFAULT now())",
)


def _tb_item_ddl() -> str:
    """`tb_item` with EVERY column of the model, all nullable but the key: the tests that build or fill `tb_item`
    themselves (their IF NOT EXISTS / checkfirst then keeps this one) insert whatever columns they need (`raw`,
    `item_weight`, `subcat_id`...), and a subset here broke them."""
    from sqlalchemy.dialects import postgresql

    from app.models.tb_item import TBItem

    columns = ", ".join(f"{c.name} {c.type.compile(dialect=postgresql.dialect())}" for c in TBItem.__table__.columns)
    return f"CREATE TABLE IF NOT EXISTS tb_item ({columns}, PRIMARY KEY (comp_id, item_id))"


_TB_ITEM_DDL = _tb_item_ddl()

# The columns `costo_si.lote` reads (sell-in-costo-si T3 PR 1), same names and types as the real tables.
COSTO_SI_READER_DDL = (
    "CREATE TABLE IF NOT EXISTS costo_si_pasos (id bigserial PRIMARY KEY, item_id integer NOT NULL, orden integer NOT NULL, "
    "fecha date NOT NULL, promedio_usd numeric(18, 5), moneda varchar(3) NOT NULL DEFAULT 'USD', "
    "UNIQUE (item_id, orden))",
    "CREATE TABLE IF NOT EXISTS combo_componentes (combo_item_id integer, componente_item_id integer, cantidad numeric(18, 4) "
    "NOT NULL, PRIMARY KEY (combo_item_id, componente_item_id))",
    _TB_ITEM_DDL,
    "CREATE TABLE IF NOT EXISTS tipo_cambio (id serial PRIMARY KEY, fecha date, moneda varchar(10), "
    "compra double precision, venta double precision, timestamp_actualizacion timestamptz DEFAULT now())",
    # the reader's USD rate falls back to the ERP's rate history (interfaz §7)
    "CREATE TABLE IF NOT EXISTS tb_cur_exch_history (ceh_id bigint PRIMARY KEY, comp_id integer, curr_id_1 integer, "
    "curr_id_2 integer, ceh_cd timestamp, ceh_exchange numeric(18, 6))",
    # a combo component with no `productos_erp` row takes GBP's list cost (#2373)
    "CREATE TABLE IF NOT EXISTS tb_item_cost_list (comp_id integer NOT NULL, coslis_id integer NOT NULL, "
    "item_id integer NOT NULL, coslis_price numeric(18, 6), curr_id integer, coslis_cd timestamp, "
    "PRIMARY KEY (comp_id, coslis_id, item_id))",
)


MLPUB_REVISIONS = (
    "20261006_ml_publications_core",
    "20261006_ml_publications_subresources",
    "20261006_ml_publications_product_links",
    "20261007_ml_publications_quality",
    "20261010_ml_user_product_stock_locations",
    "20261011_ml_user_product_replenishment",
    "20261017_ml_items_installments_campaign",
    "20261102_hay_mejores_ofertas",
    "20261114_hay_mejores_excluido",
    # Auto-aplicación / C2 paths call get_criterios; without this table listar fails in mlpub_pg.
    "20261117_ml_hay_mejores_criterios",
    # Boundaries prefetch_catalog_snapshots + flag_transition audit need these tables.
    "20260731_ml_catalog_competition",
    "20261117_ml_hay_mejores_audit",
)

_MIGRATIONS: list[Any] = []


def _migrations() -> list[Any]:
    """The REAL revision modules of `MLPUB_REVISIONS`, loaded once per process."""
    import importlib.util

    if not _MIGRATIONS:
        versions = Path(__file__).resolve().parents[3] / "alembic" / "versions"
        for revision in MLPUB_REVISIONS:
            module_spec = importlib.util.spec_from_file_location(f"{revision}_for_tests", versions / f"{revision}.py")
            migration = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(migration)
            _MIGRATIONS.append(migration)
    return _MIGRATIONS


def _store_tables() -> list[Any]:
    from app.models import ml_publications as models

    return [
        model.__table__ for model in vars(models).values() if hasattr(model, "__table__") and hasattr(model, "metadata")
    ]


def _build_schema() -> tuple[Any, str]:
    """A new schema migrated with `MLPUB_REVISIONS` plus the reactivation queue; returns (engine, schema). Every
    connection of the engine has the schema first on its `search_path`, so concurrent sessions opened by the code
    under test see the same tables."""
    import uuid

    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine, text

    from app.models.promo_refresh_reactivation import PromoRefreshReactivation
    from tests.conftest import POSTGRES_TEST_URL, _restore_pristine_pg_types

    # The SQLite `engine` fixture rewrites the shared Column types (JSONB/ARRAY -> JSON, BigInteger PK ->
    # Integer) in place; the ORM writes of the store need the real Postgres types back, whatever ran before.
    _restore_pristine_pg_types(_store_tables())
    migrations = _migrations()
    schema = f"mlpub_t_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f"CREATE SCHEMA {schema}"))
    finally:
        admin.dispose()
    eng = create_engine(
        POSTGRES_TEST_URL,
        connect_args={"options": f"-csearch_path={schema}"},
        pool_size=10,
    )
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            for migration in migrations:
                migration.upgrade()
    # The reactivation queue (its own migration, 20261018) that `events_store.write_events` feeds.
    PromoRefreshReactivation.__table__.create(bind=eng)
    return eng, schema


def _drop_schema(eng: Any, schema: str) -> None:
    from sqlalchemy import create_engine, text

    from tests.conftest import POSTGRES_TEST_URL

    eng.dispose()
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text("SET lock_timeout = '10s'"))  # a leaked connection must not hang the teardown
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
    finally:
        admin.dispose()


@contextmanager
def _bound(monkeypatch: pytest.MonkeyPatch, eng: Any) -> Iterator[Any]:
    """`get_background_db()` (what the store's primitives use) pointed at `eng`, and the publication map built
    wherever a test builds `productos_erp`, for as long as the context lives."""
    from sqlalchemy import event
    from sqlalchemy.orm import sessionmaker

    from app.models.producto import ProductoERP
    from tests.conftest import _patch_pg_types_for_sqlite, _restore_pristine_pg_types

    _restore_pristine_pg_types(_store_tables())
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=eng, autocommit=False, autoflush=False))
    # The linking module reads the ERP publication map beside the catalog (links first from the map), so wherever
    # a test builds `productos_erp` in this schema the map table is built with it, as both exist in production.
    event.listen(ProductoERP.__table__, "after_create", _create_publication_map)
    try:
        yield eng
    finally:
        event.remove(ProductoERP.__table__, "after_create", _create_publication_map)
        _patch_pg_types_for_sqlite()  # leave the shared columns as the SQLite fixture expects them


@contextmanager
def mlpub_schema(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Throwaway Postgres schema holding the REAL core, sub-resource and product-link migrations' tables, with
    `get_background_db()` (what the store's primitives use) pointed at it. Built and dropped on every use: the
    volume modules (`module_env`) keep one for a whole module. `mlpub_pg` reuses one per worker instead
    (`SharedSchema`).

    Yields the engine; every connection it hands out has the schema first on
    its `search_path`, so concurrent sessions opened by the code under test
    see the same tables.
    """
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    eng, schema = _build_schema()
    try:
        with _bound(monkeypatch, eng):
            yield eng
    finally:
        _drop_schema(eng, schema)


# What a schema looks like to the code under test: its relations, columns, defaults, constraints, indexes, user
# triggers, functions and types. Two schemas with the same fingerprint are interchangeable for the tests.
_FINGERPRINT_SQL = """
SELECT md5(concat_ws('|',
  (SELECT string_agg(c.relname || ':' || c.relkind::text || ':' || coalesce(pg_get_viewdef(c.oid), ''), ',' ORDER BY c.relname)
     FROM pg_class c WHERE c.relnamespace = to_regnamespace(:schema) AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')),
  (SELECT string_agg(c.relname || '.' || a.attname || ':' || format_type(a.atttypid, a.atttypmod) || ':'
                     || a.attnotnull::text || ':' || a.attgenerated::text || ':' || a.attidentity::text || ':'
                     || coalesce(pg_get_expr(d.adbin, d.adrelid), ''), ',' ORDER BY c.relname, a.attnum)
     FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
     LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
     WHERE c.relnamespace = to_regnamespace(:schema) AND a.attnum > 0 AND NOT a.attisdropped),
  (SELECT string_agg(conrelid::regclass::text || '.' || conname || ':' || pg_get_constraintdef(oid), ','
                     ORDER BY conrelid::regclass::text, conname)
     FROM pg_constraint WHERE connamespace = to_regnamespace(:schema)),
  (SELECT string_agg(pg_get_indexdef(i.indexrelid), ',' ORDER BY pg_get_indexdef(i.indexrelid))
     FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid WHERE c.relnamespace = to_regnamespace(:schema)),
  (SELECT string_agg(pg_get_triggerdef(t.oid), ',' ORDER BY pg_get_triggerdef(t.oid))
     FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
     WHERE c.relnamespace = to_regnamespace(:schema) AND NOT t.tgisinternal),
  (SELECT string_agg(p.proname || '(' || pg_get_function_identity_arguments(p.oid) || '):' || md5(p.prosrc), ','
                     ORDER BY p.proname, pg_get_function_identity_arguments(p.oid))
     FROM pg_proc p WHERE p.pronamespace = to_regnamespace(:schema)),
  (SELECT string_agg(t.typname, ',' ORDER BY t.typname) FROM pg_type t
     WHERE t.typnamespace = to_regnamespace(:schema) AND t.typtype IN ('e', 'd', 'c', 'r', 'm')
       AND NOT EXISTS (SELECT 1 FROM pg_class c WHERE c.reltype = t.oid))
))
"""


class SharedSchema:
    """One migrated `mlpub` schema per worker process, reused by every `mlpub_pg` test.

    Building it runs 12 real revisions (`MLPUB_REVISIONS`) plus the reactivation queue; before it was reused that
    ran before EVERY test (~1,500 tests in `tests/services/ml_publications` alone). The code under test opens its
    own sessions through `SessionLocal` and commits, so a test cannot be isolated by rolling back an outer
    transaction. Isolation is a reset after each test instead:

    1. every pooled connection is closed (their temp tables, `SET`s and locks go with them);
    2. whatever the test created in the schema (tables such as `productos_erp` from `env`, views, sequences,
       functions, types) is dropped;
    3. if the schema still differs from the freshly built one (`_FINGERPRINT_SQL`: a column, index, constraint or
       trigger added or changed by a test), it is DISCARDED and the next test gets a new one;
    4. otherwise every table is truncated with `RESTART IDENTITY` (every sequence of these migrations belongs to a
       serial/identity column) and the rows the migrations seeded are put back.

    Any error during the reset discards the schema too: a test never gets a schema that was not proven clean.
    """

    def __init__(self) -> None:
        self.engine: Any = None
        self.schema: str | None = None
        self.in_use = False
        self.built = 0  # schemas built by this process (pins that reuse happens)
        self._fingerprint: str | None = None
        self._tables: list[str] = []
        self._seeded: list[tuple[str, str]] = []  # (table, column list) restored from the snapshot schema
        self._relations: set[tuple[str, str]] = set()
        self._functions: set[str] = set()
        self._types: set[str] = set()

    @property
    def _snapshot(self) -> str:
        return f"{self.schema}_s"

    def acquire(self) -> Any:
        if self.engine is None:
            self._build()
        self.in_use = True
        return self.engine

    def release(self) -> None:
        self.in_use = False
        try:
            self._reset()
        except Exception:
            self.discard()

    def discard(self) -> None:
        if self.engine is not None:
            try:
                _drop_schema(self.engine, self.schema)
                _drop_schema(self.engine, self._snapshot)
            except Exception:
                pass  # left behind on a broken server; the per-worker database dies with the CI job
        self.engine = None
        self.schema = None

    def _build(self) -> None:
        from sqlalchemy import text

        self.engine, self.schema = _build_schema()
        self.built += 1
        with self.engine.connect() as conn:
            self._tables = list(
                conn.execute(
                    text(
                        "SELECT quote_ident(relname) FROM pg_class WHERE relnamespace = to_regnamespace(:s) "
                        "AND relkind IN ('r', 'p') ORDER BY relname"
                    ),
                    {"s": self.schema},
                ).scalars()
            )
            conn.execute(text(f"CREATE SCHEMA {self._snapshot}"))
            self._seeded = []
            for table in self._tables:
                if conn.execute(text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar():
                    columns = ", ".join(
                        conn.execute(
                            text(
                                "SELECT quote_ident(attname) FROM pg_attribute WHERE attrelid = to_regclass(:t) "
                                "AND attnum > 0 AND NOT attisdropped AND attgenerated = '' ORDER BY attnum"
                            ),
                            {"t": f"{self.schema}.{table}"},
                        ).scalars()
                    )
                    conn.execute(text(f"CREATE TABLE {self._snapshot}.{table} AS SELECT {columns} FROM {table}"))
                    self._seeded.append((table, columns))
            self._relations, self._functions, self._types = self._objects(conn)
            self._fingerprint = conn.execute(text(_FINGERPRINT_SQL), {"schema": self.schema}).scalar()
            conn.commit()

    def _objects(self, conn: Any) -> tuple[set[tuple[str, str]], set[str], set[str]]:
        from sqlalchemy import text

        relations = {
            (row[0], row[1])
            for row in conn.execute(
                text(
                    "SELECT quote_ident(relname), relkind FROM pg_class WHERE relnamespace = to_regnamespace(:s) "
                    "AND relkind IN ('r', 'p', 'v', 'm', 'S', 'f')"
                ),
                {"s": self.schema},
            )
        }
        functions = set(
            conn.execute(
                text(
                    "SELECT p.oid::regprocedure::text FROM pg_proc p WHERE p.pronamespace = to_regnamespace(:s) "
                    "AND p.prokind IN ('f', 'p')"
                ),
                {"s": self.schema},
            ).scalars()
        )
        types = set(
            conn.execute(
                text(
                    "SELECT quote_ident(t.typname) FROM pg_type t WHERE t.typnamespace = to_regnamespace(:s) "
                    "AND t.typtype IN ('e', 'd', 'c', 'r', 'm') "
                    "AND NOT EXISTS (SELECT 1 FROM pg_class c WHERE c.reltype = t.oid)"
                ),
                {"s": self.schema},
            ).scalars()
        )
        return relations, functions, types

    def _reset(self) -> None:
        from sqlalchemy import text

        if self.engine is None:
            return
        self.engine.dispose()
        kinds = {
            "r": "TABLE",
            "p": "TABLE",
            "f": "FOREIGN TABLE",
            "v": "VIEW",
            "m": "MATERIALIZED VIEW",
            "S": "SEQUENCE",
        }
        with self.engine.connect() as conn:
            # A connection a test leaked (checked out, never closed) may still hold locks: fail fast, then discard.
            conn.execute(text("SET lock_timeout = '5s'"))
            relations, functions, types = self._objects(conn)
            # Views first, then tables, then sequences; CASCADE takes dependants along (and a dependant inside the
            # baseline shows up in the fingerprint below).
            order = {"v": 0, "m": 0, "r": 1, "p": 1, "f": 1, "S": 2}
            for name, kind in sorted(relations - self._relations, key=lambda r: (order[r[1]], r[0])):
                conn.execute(text(f"DROP {kinds[kind]} IF EXISTS {name} CASCADE"))
            for function in functions - self._functions:
                conn.execute(text(f"DROP ROUTINE IF EXISTS {function} CASCADE"))
            for type_name in types - self._types:
                conn.execute(text(f"DROP TYPE IF EXISTS {type_name} CASCADE"))
            if conn.execute(text(_FINGERPRINT_SQL), {"schema": self.schema}).scalar() != self._fingerprint:
                conn.rollback()
                raise RuntimeError("the test changed the schema itself")
            conn.execute(text(f"TRUNCATE {', '.join(self._tables)} RESTART IDENTITY CASCADE"))
            for table, columns in self._seeded:
                conn.execute(
                    text(
                        f"INSERT INTO {table} ({columns}) OVERRIDING SYSTEM VALUE "
                        f"SELECT {columns} FROM {self._snapshot}.{table}"
                    )
                )
            conn.commit()


# One per process (each xdist worker is a process). A module-level holder rather than a session fixture: modules
# outside this package import `mlpub_pg` by name, and a fixture it depended on would not be visible there.
SHARED_SCHEMA = SharedSchema()
atexit.register(SHARED_SCHEMA.discard)


def create_env_tables(engine) -> Any:
    """The real link table plus a `productos_erp` table built from the real model, on `engine`'s schema."""
    from app.models.producto import ProductoERP

    ProductoERP.__table__.create(bind=engine)
    return engine


@contextmanager
def module_env() -> Iterator[Any]:
    """`env` for a whole module: the same schema, `SessionLocal` patch and teardown, under a MonkeyPatch that
    lives as long as the module. For the volume seeds (tens of thousands of rows) a module builds once."""
    with pytest.MonkeyPatch.context() as patch, mlpub_schema(patch) as engine:
        yield create_env_tables(engine)


@pytest.fixture()
def mlpub_pg(monkeypatch):
    """The worker's shared `mlpub` schema for one test, reset to its freshly built state afterwards
    (`SharedSchema`)."""
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    shared = SHARED_SCHEMA
    engine = shared.acquire()
    try:
        with _bound(monkeypatch, engine):
            yield engine
    finally:
        shared.release()


@pytest.fixture()
def env(mlpub_pg):
    """`create_env_tables` on the test's `mlpub_pg` schema."""
    return create_env_tables(mlpub_pg)


@pytest.fixture()
def events_on(env):
    from app.services.ml_publications.settings_store import set_setting

    set_setting("events.enabled", True, "test")
    return env


ITEM_404_SINGLE = "item_single_404_MLA1_20261006.json"


def item_404_single() -> dict:
    """Real single-item `GET /items/MLA1` 404 body `{message, error, status, cause}`."""
    return copy.deepcopy(load_fixture(ITEM_404_SINGLE)["body"])


def item_404_bulk_element() -> dict:
    """Real `/items/bulk` not-found element for MLA1 (`{id, status_code: 404, error}`)."""
    return bulk_call("bulk_full")[2]


def item_with_variations() -> dict:
    """Captured MLA1207279308 (closed, 4 variations without `attributes`)."""
    return copy.deepcopy(load_fixture(ITEM_WITH_VARIATIONS))


# --- Sub-resource captures (description, prices, sale price, promotions, user product, stock, family,
# competition, performance, moderation, visits) ---

SUBRESOURCE_FIXTURES = {
    "description": "description_20261006.json",
    "prices": "prices_20261006.json",
    "sale_price": "sale_price_20261006.json",
    "promotions": "seller_promotions_20261006.json",
    "user_product": "user_product_20261006.json",
    "stock": "user_product_stock_20261006.json",
    "family": "family_20261006.json",
    "competition": "price_to_win_20261006.json",
    "performance": "performance_20261006.json",
    "moderation": "moderation_20261006.json",
    "visits": "visits_20261006.json",
    "replenishment": "replenishment_20261008.json",
}


def subresource_call(resource: str, name: str) -> dict:
    """One captured call `{name, path, status, headers, body}` of a sub-resource fixture (deep copy)."""
    for call in load_fixture(SUBRESOURCE_FIXTURES[resource])["calls"]:
        if call["name"] == name:
            return copy.deepcopy(call)
    raise KeyError(f"{resource}:{name}")


def subresource_body(resource: str, name: str) -> Any:
    return subresource_call(resource, name)["body"]


# --- Scan pages (`/users/{seller}/items/search?search_type=scan`, captured 2026-10-06) ------

SCAN_FIXTURES = {
    "active_page1": "scan_active_page1_20261006.json",
    "active_page2": "scan_active_page2_20261006.json",
    "paused_page1": "scan_paused_page1_20261006.json",
    "closed_page1": "scan_closed_page1_20261006.json",
    "pending_page1": "scan_pending_page1_20261006.json",
    "under_review_empty": "scan_under_review_empty_20261006.json",
    "inactive_empty": "scan_inactive_empty_20261006.json",
    "invalid_scroll": "scan_invalid_scroll_20261006.json",
}


def scan_call(name: str) -> dict:
    """One captured scan call `{name, path, status, headers, body}` (deep copy)."""
    return copy.deepcopy(load_fixture(SCAN_FIXTURES[name]))


def scan_body(name: str) -> Any:
    return scan_call(name)["body"]


# --- `/missed_feeds` (captured 2026-10-06) --------------------------------------------------

MISSED_FEEDS_FIXTURES = {
    "items": "missed_feeds_items_20261006.json",
    "empty": "missed_feeds_empty_20261006.json",
    "items_page2": "missed_feeds_items_page2_20261006.json",
}


def missed_call(name: str) -> dict:
    """One captured `/missed_feeds` call `{name, path, status, headers, body}` (deep copy)."""
    return copy.deepcopy(load_fixture(MISSED_FEEDS_FIXTURES[name]))


def missed_body(name: str) -> Any:
    return missed_call(name)["body"]


# --- Bridge `webhook_latest` (captured 2026-10-06) -----------------------------------------

WEBHOOK_SAMPLES = "webhook_latest_samples.json"
# Real `stock-locations` / `user-products-families` rows, captured from the bridge on 2026-10-14.
STOCK_FAMILY_SAMPLES = "webhook_stock_families_20261014.json"
BRIDGE_DDL = "bridge_webhook_latest.sql"


def webhook_row(topic: str, index: int = 0, *, fixture: str = WEBHOOK_SAMPLES, **overrides: Any) -> dict:
    """One real captured `webhook_latest` row of `topic` (deep copy) from `fixture`. `overrides` replace
    top-level columns (real payload, `received_at`/`resource` changed to place it on a test timeline); a
    changed `resource` is mirrored into the payload."""
    rows = [r for r in load_fixture(fixture)["samples"] if r["topic"] == topic]
    row = copy.deepcopy(rows[index])
    row.update(overrides)
    if "resource" in overrides:
        row["payload"]["resource"] = overrides["resource"]
    return row


@pytest.fixture()
def bridge_pg(mlpub_pg):
    """A second throwaway schema standing in for the bridge database, holding the real
    `webhook_latest` DDL (copied from the bridge migration). Yields its engine."""
    import uuid

    from sqlalchemy import create_engine, text

    from tests.conftest import POSTGRES_TEST_URL

    schema = f"mlbridge_t_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"}, pool_size=5)
    with eng.begin() as conn:
        conn.exec_driver_sql((FIXTURES_DIR / BRIDGE_DDL).read_text(encoding="utf-8"))
    try:
        yield eng
    finally:
        eng.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def put_webhook(engine, row: dict) -> None:
    """Upsert one row the way the bridge handler does (one row per (topic, resource), latest wins)."""
    import json

    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO webhook_latest (topic, resource, webhook_id, received_at, payload) "
                "VALUES (:topic, :resource, :webhook_id, CAST(:received_at AS timestamptz), CAST(:payload AS jsonb)) "
                "ON CONFLICT (topic, resource) DO UPDATE SET webhook_id = EXCLUDED.webhook_id, "
                "received_at = EXCLUDED.received_at, payload = EXCLUDED.payload"
            ),
            {
                "topic": row["topic"],
                "resource": row["resource"],
                "webhook_id": row.get("webhook_id"),
                "received_at": str(row["received_at"]),
                "payload": json.dumps(row["payload"]),
            },
        )
