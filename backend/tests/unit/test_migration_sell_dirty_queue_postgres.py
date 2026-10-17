"""Migration `20261031_sell_dirty_queue` (sell-in-sell-out T4): graph, frozen
copy of the live trigger SQL, and upgrade/downgrade on a real Postgres."""

from __future__ import annotations

import importlib.util
import os
import uuid
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, inspect, text

from app.models.sell_dirty import SellDirty
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica
from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica
from app.services.sell import queue
from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable, _restore_pristine_pg_types

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261031_sell_dirty_queue"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_SOURCES = [VentaFueraMLMetrica.__table__, VentaTiendaNubeMetrica.__table__]


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _module():
    spec = importlib.util.spec_from_file_location("sell_dirty_queue_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigrationGraph:
    def test_single_head_that_contains_this_revision(self) -> None:
        script = _script_directory()
        heads = script.get_heads()
        assert len(heads) == 1
        chain = {r.revision for r in script.walk_revisions(base="base", head=heads[0])}
        assert _REVISION in chain

    def test_chains_on_the_previous_head(self) -> None:
        assert _script_directory().get_revision(_REVISION).down_revision == "20261030_ml_write_log"

    def test_the_trigger_sql_is_a_frozen_copy_of_the_live_one(self) -> None:
        module = _module()
        assert module._TRIGGERS_UP == queue.UPGRADE_SQL
        assert module._TRIGGERS_DOWN == queue.DOWNGRADE_SQL


@pytest.fixture()
def pg_engine() -> Iterator[Engine]:
    """A throwaway schema (first on `search_path`) holding only the two source
    tables: whatever other tests left in the shared database (a `sell_dirty`
    table, its triggers or function) is invisible here, so the test never skips
    and always runs the real upgrade and downgrade."""
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    _restore_pristine_pg_types(_SOURCES)
    schema = f"sell_dirty_mig_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as conn:
            assert conn.execute(text("SELECT current_schema()")).scalar() == schema
            for table in _SOURCES:
                table.create(bind=conn)
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def _triggers(conn) -> set:
    rows = conn.execute(
        text(
            "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE c.relnamespace = CAST(current_schema() AS regnamespace) AND t.tgname LIKE 'trg_sell_dirty_%'"
        )
    )
    return {row[0] for row in rows}


def _functions(conn) -> int:
    return conn.execute(
        text(
            "SELECT count(*) FROM pg_proc "
            "WHERE pronamespace = CAST(current_schema() AS regnamespace) AND proname LIKE 'sell_dirty_%'"
        )
    ).scalar()


@pytest.mark.postgres
class TestMigrationDdl:
    def test_upgrade_creates_the_queue_and_triggers_and_downgrade_drops_them(self, pg_engine: Engine) -> None:
        module = _module()

        with pg_engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                module.upgrade()
            assert _functions(conn) == 1
            columns = {c["name"] for c in inspect(conn).get_columns("sell_dirty")}
            assert columns == {c.name for c in SellDirty.__table__.columns}
            assert _triggers(conn) == {
                "trg_sell_dirty_fuera_insert_delete",
                "trg_sell_dirty_fuera_update",
                "trg_sell_dirty_tn_insert_delete",
                "trg_sell_dirty_tn_update",
            }

        with pg_engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                module.downgrade()
            assert not inspect(conn).has_table("sell_dirty")
            assert _triggers(conn) == set()
            assert _functions(conn) == 0
