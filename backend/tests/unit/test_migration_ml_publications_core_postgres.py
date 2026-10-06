"""Migration `20261006_ml_publications_core`: the ML publications store tables.

Runs inside a throwaway schema of the Postgres test DB. New tables only; the
store must not reference any GBP/ERP table (data only from MercadoLibre).
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _BACKEND_ROOT / "alembic" / "versions" / "20261006_ml_publications_core.py"

TABLES = {
    "ml_items",
    "ml_item_variations",
    "ml_change_log",
    "ml_item_events",
    "ml_pub_settings",
    "ml_pub_refresh_queue",
    "ml_pub_intake_cursors",
    "ml_pub_scan_state",
    "ml_pub_job_runs",
}
FORBIDDEN_REFS = {"productos_erp", "tb_mercadolibre_items_publicados", "publicaciones_ml"}
FAMILY_ID = 7695306917964170  # > 2**52, must survive a round trip as bigint


def _load_migration():
    spec = importlib.util.spec_from_file_location("ml_publications_core_migration", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def engine():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"mlpub_mig_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield eng
    finally:
        eng.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin_engine.dispose()


def _run(engine, step: str) -> None:
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    migration = _load_migration()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(migration, step)()


def _tables(engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")).all()
    return {r[0] for r in rows}


def _indexdefs(engine) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema()")
        ).all()
    return {r[0]: r[1] for r in rows}


def _defs_for(engine, table: str) -> list[str]:
    return [d.lower() for d in _indexdefs(engine).values() if f" on {_schema(engine)}.{table} " in d.lower()]


def _schema(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT current_schema()")).scalar()


def _has(defs: list[str], *fragments: str) -> bool:
    return any(all(f in d for f in fragments) for d in defs)


@pytest.mark.postgres
class TestMlPublicationsCoreMigration:
    def test_upgrade_creates_exactly_the_core_tables(self, engine) -> None:
        _run(engine, "upgrade")
        assert _tables(engine) == TABLES

    def test_item_indexes(self, engine) -> None:
        _run(engine, "upgrade")
        defs = _defs_for(engine, "ml_items")
        for col in (
            "status",
            "official_store_id",
            "brand",
            "user_product_id",
            "family_id",
            "catalog_product_id",
            "seller_custom_field",
            "seller_sku",
        ):
            assert _has(defs, f"({col})"), col
        assert _has(defs, "(gone_at)", "where (gone_at is not null)")

    def test_change_log_indexes(self, engine) -> None:
        _run(engine, "upgrade")
        defs = _defs_for(engine, "ml_change_log")
        assert _has(defs, "(item_id, observed_at desc, id desc)")
        assert _has(defs, "(resource_type, entity_id, observed_at desc)")
        assert _has(defs, "using gin (changed_paths)")
        assert _has(defs, "using brin (observed_at)")

    def test_event_indexes_and_unique_dedupe_key(self, engine) -> None:
        _run(engine, "upgrade")
        defs = _defs_for(engine, "ml_item_events")
        assert _has(defs, "(item_id, observed_at desc, id desc)")
        assert _has(defs, "(event_type, observed_at desc, id desc)")
        assert _has(defs, "(official_store_id, event_type, observed_at desc)")
        assert _has(defs, "(change_log_id)")
        assert _has(defs, "unique", "(dedupe_key)")

    def test_queue_partial_indexes_and_pk(self, engine) -> None:
        _run(engine, "upgrade")
        defs = _defs_for(engine, "ml_pub_refresh_queue")
        assert _has(defs, "(kind, entity_id)", "unique")
        assert _has(defs, "(lane, not_before, first_enqueued_at)", "claimed_at is null", "parked_at is null")
        assert _has(defs, "(claimed_at)", "claimed_at is not null")
        assert _has(defs, "(parked_at)", "parked_at is not null")

    def test_state_tables_use_fillfactor_85(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT relname, reloptions FROM pg_class "
                    "WHERE relname IN ('ml_items', 'ml_item_variations') AND relnamespace = current_schema()::regnamespace"
                )
            ).all()
        assert {r[0]: list(r[1] or []) for r in rows} == {
            "ml_items": ["fillfactor=85"],
            "ml_item_variations": ["fillfactor=85"],
        }

    def test_family_id_is_bigint_and_round_trips(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.begin() as conn:
            dtype = conn.execute(
                text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'ml_items' AND column_name = 'family_id'"
                )
            ).scalar()
            assert dtype == "bigint"
            conn.execute(
                text("INSERT INTO ml_items (item_id, family_id) VALUES ('MLA1', :f)"),
                {"f": FAMILY_ID},
            )
            assert conn.execute(text("SELECT family_id FROM ml_items WHERE item_id = 'MLA1'")).scalar() == FAMILY_ID

    def test_event_dedupe_key_rejects_duplicates(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ml_change_log (id, resource_type, entity_id, observed_at, changed_paths, changes) "
                    "VALUES (1, 'item', 'MLA1', now(), ARRAY['price'], '[]')"
                )
            )
            ins = (
                "INSERT INTO ml_item_events (event_type, item_id, observed_at, change_log_id, dedupe_key) "
                "VALUES ('price_changed', 'MLA1', now(), 1, decode('aa', 'hex'))"
            )
            conn.execute(text(ins))
        with pytest.raises(Exception):
            with engine.begin() as conn:
                conn.execute(text(ins))

    def test_no_foreign_keys_or_link_columns_to_gbp_erp_tables(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.connect() as conn:
            fks = conn.execute(
                text(
                    "SELECT conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint "
                    "WHERE contype = 'f' AND connamespace = current_schema()::regnamespace"
                )
            ).all()
            cols = conn.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema()"
                )
            ).all()
        for _, referenced in fks:
            assert referenced.split(".")[-1] not in FORBIDDEN_REFS
        assert {(t, c) for t, c in cols if "producto" in c and c != "user_product_id" and "catalog" not in c} == set()
        assert not [c for _, c in cols if c in {"producto_id", "item_id_erp", "cod_item", "publicacion_ml_id"}]

    def test_downgrade_removes_exactly_these_tables(self, engine) -> None:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE unrelated (id int)"))
        _run(engine, "upgrade")
        _run(engine, "downgrade")
        assert _tables(engine) == {"unrelated"}


def test_alembic_has_a_single_head() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1
