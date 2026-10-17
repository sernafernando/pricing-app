"""Migration `20261031_sell_dirty_queue` (sell-in-sell-out T4): graph and
upgrade/downgrade on a real Postgres."""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, inspect, text

from app.models.sell_dirty import SellDirty
from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261031_sell_dirty_queue"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")


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


@pytest.fixture()
def pg_engine() -> Iterator[Engine]:
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    engine = create_engine(POSTGRES_TEST_URL)
    if inspect(engine).has_table("sell_dirty"):
        pytest.skip("sell_dirty already exists in the test database (owned by another fixture)")
    yield engine
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS sell_dirty"))
    engine.dispose()


@pytest.mark.postgres
class TestMigrationDdl:
    def test_upgrade_creates_the_queue_and_downgrade_drops_it(self, pg_engine: Engine) -> None:
        module = _module()

        with pg_engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                module.upgrade()
            columns = {c["name"] for c in inspect(conn).get_columns("sell_dirty")}
            assert columns == {c.name for c in SellDirty.__table__.columns}

        with pg_engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                module.downgrade()
            assert not inspect(conn).has_table("sell_dirty")
