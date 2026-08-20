"""tn-publisher-module PR-4 — migration `20260818_add_tn_publisher_tables`.

Two layers, mirroring `test_migration_tn_publicacion_permiso.py` and
`test_producto_precio_origen_migration.py`:

1. Dialect-agnostic revision-graph checks (runs on SQLite CI): confirms the
   migration is registered, correctly chained on the current head, and is an
   ancestor of whatever the eventual head is.
2. Source-inspection checks on `upgrade()`/`downgrade()`: table creation
   (3 tables), the 4 seed profiles (MP2), the new permission distinct from
   `admin.gestionar_tn_publicacion` (D10), and a clean downgrade (all 3
   tables dropped). Actual `alembic upgrade/downgrade` against a live DB is
   not re-run here — the full chain up to this revision contains
   Postgres-only raw SQL (NOW(), ON CONFLICT) from earlier migrations, so a
   from-scratch run against SQLite is not viable; this mirrors the existing
   convention (see `test_producto_precio_origen_migration.py`'s docstring).
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import os

from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20260818_add_tn_publisher_tables"
_DOWN_REVISION = "20260813_propuesta_corregida"
_MIGRATION_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_tn_publisher_tables", _MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _extract_bulk_insert_rows(upgrade_src: str) -> list[dict]:
    """Parses `upgrade()`'s source and literal_eval's the `op.bulk_insert(
    profile_table, [...])` call's row list — so the assertions below check
    what the migration ACTUALLY seeds, not a hand-copied literal that could
    silently drift from the real migration (pre-push review finding: a
    fabricated `seed_rows` list disconnected from the source would still
    pass even if the real migration's seed data broke)."""
    tree = ast.parse(upgrade_src)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "bulk_insert"
            and len(node.args) >= 2
        ):
            return ast.literal_eval(node.args[1])
    raise AssertionError("No op.bulk_insert(...) call found in upgrade() source")


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


class TestMigrationSchema:
    def test_upgrade_creates_the_three_tables(self) -> None:
        mod = _load_migration()
        src = inspect.getsource(mod.upgrade)
        assert "tn_measurement_profile" in src
        assert "tn_publish_override" in src
        assert "tn_category_profile_hint" in src

    def test_upgrade_seeds_exactly_four_profiles_with_all_four_fields(self) -> None:
        """MP2 — the migration seeds the four de-facto GBP clusters, each with
        weight/width/height/depth populated."""
        mod = _load_migration()
        src = inspect.getsource(mod.upgrade)

        expected_clusters = ["30x20x20", "30x40x10", "50x40x20", "45x55x25"]
        for cluster in expected_clusters:
            assert cluster in src

        # Parsed straight out of the migration's actual `op.bulk_insert(...)`
        # call (see `_extract_bulk_insert_rows`) — NOT a hand-copied literal,
        # so this fails if the real seed data ever breaks.
        seed_rows = _extract_bulk_insert_rows(src)
        assert len(seed_rows) == 4
        assert {row["name"] for row in seed_rows} == set(expected_clusters)
        for row in seed_rows:
            for field in ("weight", "width", "height", "depth"):
                assert row[field] is not None
                assert row[field] > 0

    def test_upgrade_seeds_the_new_permission_distinct_from_publicacion(self) -> None:
        """D10 — new permission, distinct from admin.gestionar_tn_publicacion,
        seeded in the same migration following the existing pattern."""
        mod = _load_migration()
        src = inspect.getsource(mod.upgrade)
        assert "'admin.gestionar_tn_perfiles'" in src
        assert "'admin.gestionar_tn_publicacion'" not in src

    def test_downgrade_drops_all_three_tables(self) -> None:
        mod = _load_migration()
        src = inspect.getsource(mod.downgrade)
        assert "drop_table" in src
        assert "tn_measurement_profile" in src
        assert "tn_publish_override" in src
        assert "tn_category_profile_hint" in src

    def test_downgrade_removes_the_new_permission_not_the_publish_one(self) -> None:
        mod = _load_migration()
        src = inspect.getsource(mod.downgrade)
        assert "'admin.gestionar_tn_perfiles'" in src
        assert "'admin.gestionar_tn_publicacion'" not in src
