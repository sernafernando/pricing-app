"""RED/GREEN — Alembic migration for producto_precio_origen.

Verifies the migration file: single-head chain (down_revision points to the
pre-slice-2 head), creates the expected table + unique constraint + index,
and reverses cleanly on downgrade. Actual `alembic upgrade/downgrade` against
a live DB is exercised manually per SDD apply verification (not re-run here
to keep the unit suite DB-independent).
"""

import importlib.util
import os


MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "alembic", "versions", "20260715_add_producto_precio_origen.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_producto_precio_origen", MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigrationChain:
    def test_down_revision_is_the_pre_slice2_head(self):
        mod = _load_migration()
        assert mod.down_revision == "20260713_merge_heads"

    def test_revision_id_matches_filename(self):
        mod = _load_migration()
        assert mod.revision == "20260715_add_producto_precio_origen"


class TestMigrationSchema:
    def test_upgrade_creates_table_with_unique_constraint(self):
        import inspect

        mod = _load_migration()
        src = inspect.getsource(mod.upgrade)

        assert "producto_precio_origen" in src
        assert "item_id" in src
        assert "column_key" in src
        assert "origen" in src
        assert "promo_id" in src
        assert "mla" in src
        assert "fecha" in src
        assert "UniqueConstraint" in src
        assert "uq_producto_precio_origen_item_column" in src

    def test_downgrade_drops_table(self):
        import inspect

        mod = _load_migration()
        src = inspect.getsource(mod.downgrade)
        assert "drop_table" in src
        assert "producto_precio_origen" in src
