"""Defect fix migration `20260820_fix_tn_category_profile_hint_nulls`.

Same two-layer pattern as `test_migration_tn_publisher_tables.py`:

1. Dialect-agnostic revision-graph checks (SQLite-safe).
2. Source-inspection checks on `upgrade()`/`downgrade()` — the migration
   contains Postgres-only raw SQL (window functions, `NULLS NOT DISTINCT`),
   so a from-scratch run against SQLite is not viable here either; the raw
   SQL's actual dedupe/constraint behavior was verified manually against
   this deployment's live Postgres 18 before writing this migration (see
   its docstring).
"""

from __future__ import annotations

import importlib.util
import inspect
import os

from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20260820_fix_tn_category_profile_hint_nulls"
_DOWN_REVISION = "20260818_add_tn_publisher_tables"
_MIGRATION_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_fix_tn_category_profile_hint_nulls", _MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigrationGraph:
    def test_revision_is_registered_and_linked(self) -> None:
        script = _script_directory()
        revision = script.get_revision(_REVISION)
        assert revision is not None
        assert revision.down_revision == _DOWN_REVISION

    def test_is_ancestor_of_current_head(self) -> None:
        script = _script_directory()
        (head,) = script.get_heads()
        ancestor_revisions = {rev.revision for rev in script.walk_revisions(base="base", head=head)}
        assert _REVISION in ancestor_revisions

    def test_the_graph_has_exactly_one_head(self) -> None:
        """Guards against the multiple-heads incident this repo already
        had once (see `20260813_propuesta_corregida`'s merge-migration
        history): `alembic upgrade head` fails outright with two heads.

        Deliberately does NOT assert WHICH revision is the head — this
        migration was the head when it was written, and a later merge
        migration legitimately took over when the tn-publisher branch met
        main. What must stay true forever is that there is exactly one,
        and that this revision is still reachable from it (asserted by
        `test_is_ancestor_of_current_head` above)."""
        script = _script_directory()
        heads = script.get_heads()
        assert len(heads) == 1, f"grafo con {len(heads)} heads: {heads}"


class TestMigrationDedupeBeforeConstraint:
    def test_upgrade_dedupes_before_touching_the_constraint(self) -> None:
        mod = _load_migration()
        src = inspect.getsource(mod.upgrade)
        # The dedup DELETE must run before the constraint is dropped/recreated,
        # otherwise a table with pre-existing duplicates would fail to add the
        # new (stricter) constraint.
        delete_pos = src.index("DELETE FROM tn_category_profile_hint")
        drop_constraint_pos = src.index('op.drop_constraint("uq_tn_category_profile_hint"')
        assert delete_pos < drop_constraint_pos

    def test_upgrade_sums_uso_count_of_removed_duplicates_into_survivor(self) -> None:
        mod = _load_migration()
        src = inspect.getsource(mod.upgrade)
        assert "SUM(r.uso_count)" in src
        assert "SET uso_count = t.uso_count + losers_sum.extra_uso_count" in src

    def test_upgrade_keeps_highest_uso_count_tie_broken_by_lowest_id(self) -> None:
        mod = _load_migration()
        src = inspect.getsource(mod.upgrade)
        assert "ORDER BY uso_count DESC, id ASC" in src


class TestMigrationConstraintFix:
    def test_upgrade_recreates_constraint_with_nulls_not_distinct(self) -> None:
        mod = _load_migration()
        src = inspect.getsource(mod.upgrade)
        assert 'op.drop_constraint("uq_tn_category_profile_hint"' in src
        assert "postgresql_nulls_not_distinct=True" in src
        assert '"categoria", "subcategoria", "profile_id"' in src

    def test_downgrade_recreates_the_original_constraint_without_nulls_not_distinct(self) -> None:
        mod = _load_migration()
        src = inspect.getsource(mod.downgrade)
        assert 'op.drop_constraint("uq_tn_category_profile_hint"' in src
        assert "postgresql_nulls_not_distinct" not in src
        assert "uq_tn_category_profile_hint" in src
