"""Migration `20261021_ml_pub_queue_unpark_items`: one-off recovery of the item entries parked in production.

Postgres only: the queue uses `text[]` and `gen_random_uuid()`.
"""

from __future__ import annotations

import importlib.util
import os

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text

from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261021_ml_pub_queue_unpark_items"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _migration():
    spec = importlib.util.spec_from_file_location("ml_pub_queue_unpark_items_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigrationGraph:
    def test_single_head_that_contains_this_revision(self) -> None:
        script = _script_directory()
        heads = script.get_heads()
        assert len(heads) == 1
        chain = {r.revision for r in script.walk_revisions(base="base", head=heads[0])}
        assert _REVISION in chain, f"{_REVISION!r} is not an ancestor of the single head {heads[0]!r}"

    def test_has_exactly_one_parent(self) -> None:
        assert isinstance(_script_directory().get_revision(_REVISION).down_revision, str)


_ROWS = [
    # (entity_id, kind, resources, lane, attempts, parked, claimed)
    ("MLA1", "item", "{moderation,performance}", 1, 8, True, False),
    ("MLA2", "item", "{core,promotions}", 4, 8, True, False),
    ("MLA3", "item", "{performance}", 0, 8, True, False),
    ("MLA4", "item", "{performance}", 3, 3, False, False),  # backing off, not parked: left alone
    ("MLA5", "item", "{performance}", 2, 8, True, True),  # held by a worker: its fenced complete settles it
    ("UP1", "user_product", "{stock}", 1, 8, True, False),  # not an item entry
]


def _seed(conn) -> None:
    for entity_id, kind, resources, lane, attempts, parked, claimed in _ROWS:
        conn.execute(
            text(
                "INSERT INTO ml_pub_refresh_queue (kind, entity_id, resources, lane, attempts, last_error, not_before, "
                "parked_at, claimed_at, claimed_by, claim_token) VALUES (:k, :e, CAST(:r AS text[]), :l, :a, "
                "'performance: HTTP 400', now() + interval '6 hours', CASE WHEN :p THEN now() END, "
                "CASE WHEN :c THEN now() END, CASE WHEN :c THEN 'w1' END, CASE WHEN :c THEN gen_random_uuid() END)"
            ),
            {"k": kind, "e": entity_id, "r": resources, "l": lane, "a": attempts, "p": parked, "c": claimed},
        )


def _state(conn) -> dict:
    rows = conn.execute(
        text(
            "SELECT entity_id, resources, lane, attempts, parked_at IS NOT NULL AS parked, "
            "not_before <= now() AS due, last_error FROM ml_pub_refresh_queue"
        )
    ).mappings()
    return {r["entity_id"]: dict(r) for r in rows}


@pytest.mark.postgres
class TestMigrationData:
    def test_unparks_every_parked_unclaimed_item_entry_as_a_fresh_bundle_refresh(self, mlpub_pg) -> None:  # noqa: F811
        module = _migration()
        with mlpub_pg.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx), ctx.begin_transaction():
                _seed(conn)
                before = _state(conn)
                module.upgrade()
                after = _state(conn)
                module.upgrade()  # idempotent
                assert _state(conn) == after

        # Backlog lane (3) so 8.5k recoveries never delay live notifications; a manual entry keeps lane 0.
        for entity_id, lane in (("MLA1", 3), ("MLA2", 3), ("MLA3", 0)):
            assert after[entity_id] == {
                "entity_id": entity_id,
                "resources": ["bundle"],
                "lane": lane,
                "attempts": 0,
                "parked": False,
                "due": True,
                "last_error": "performance: HTTP 400",  # kept: it records why the entry was parked
            }
        for untouched in ("MLA4", "MLA5", "UP1"):
            assert after[untouched] == before[untouched]

    def test_downgrade_changes_nothing(self, mlpub_pg) -> None:  # noqa: F811
        module = _migration()
        with mlpub_pg.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx), ctx.begin_transaction():
                _seed(conn)
                before = _state(conn)
                module.downgrade()
                assert _state(conn) == before
