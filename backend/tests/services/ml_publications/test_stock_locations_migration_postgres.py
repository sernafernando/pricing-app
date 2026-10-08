"""Migration `20261010_ml_user_product_stock_locations`: typed per-location stock backfilled from `raw`.

Runs inside a throwaway schema of the Postgres test DB over a minimal `ml_user_product_stock` that
already holds rows. The `raw` bodies are the captured `/user-products/{id}/stock` payloads
(`user_product_stock_20261006.json`) or a copy with one field changed (named per row).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from tests.services.ml_publications.conftest import subresource_body

_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_REVISION = "20261010_ml_user_product_stock_locations"
_MIGRATION = _BACKEND_ROOT / "alembic" / "versions" / f"{_REVISION}.py"


def _captured(name: str) -> dict:
    return subresource_body("stock", f"user_product_stock_{name}")


def _rows() -> list[tuple[str, object, int | None]]:
    """(id, raw, total_quantity) - the rows the table holds BEFORE the migration."""
    with_warehouse = copy.deepcopy(_captured("MLAU266459622"))
    with_warehouse["locations"].append({"type": "seller_warehouse", "quantity": 5})  # captured + one entry added
    with_full = copy.deepcopy(_captured("MLAU266459622"))
    with_full["locations"][1]["quantity"] = 7  # captured, meli_facility 0 -> 7
    no_locations = copy.deepcopy(_captured("MLAU245334053"))
    del no_locations["locations"]  # captured, field removed
    not_a_list = copy.deepcopy(_captured("MLAU245334053"))
    not_a_list["locations"] = {"type": "meli_facility", "quantity": 3}  # captured, list -> object
    empty = copy.deepcopy(_captured("MLAU245334053"))
    empty["locations"] = []  # captured, entries removed
    return [
        ("A_captured", _captured("MLAU245334053"), 2),
        ("B_captured", _captured("MLAU266459622"), 26),
        ("C_warehouse", with_warehouse, 31),
        ("D_full", with_full, 33),
        ("E_no_locations", no_locations, None),
        ("F_not_a_list", not_a_list, None),
        ("G_empty", empty, 0),
        ("H_no_raw", None, None),  # a row whose fetch left no body
    ]


@pytest.fixture()
def engine():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"stkloc_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    with eng.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE ml_user_product_stock ("
                "user_product_id text PRIMARY KEY, total_quantity integer, raw jsonb)"
            )
        )
        for key, raw, total in _rows():
            conn.execute(
                text("INSERT INTO ml_user_product_stock VALUES (:k, :t, CAST(:r AS jsonb))"),
                {"k": key, "t": total, "r": None if raw is None else json.dumps(raw)},
            )
    try:
        yield eng
    finally:
        eng.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin_engine.dispose()


def _load_migration():
    spec = importlib.util.spec_from_file_location("ml_user_product_stock_locations_migration", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(engine, step: str, migration=None) -> None:
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    migration = migration or _load_migration()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(migration, step)()


def _split(engine) -> dict[str, tuple[int | None, int | None, int | None]]:
    with engine.connect() as conn:
        return {
            r[0]: (r[1], r[2], r[3])
            for r in conn.execute(
                text(
                    "SELECT user_product_id, full_quantity, own_quantity, total_quantity "
                    "FROM ml_user_product_stock ORDER BY user_product_id"
                )
            )
        }


# (full, own, total) per row after the backfill
EXPECTED = {
    "A_captured": (0, 2, 2),
    "B_captured": (0, 26, 26),
    "C_warehouse": (0, 31, 31),
    "D_full": (7, 26, 33),
    "E_no_locations": (None, None, None),
    "F_not_a_list": (None, None, None),
    "G_empty": (0, 0, 0),
    "H_no_raw": (None, None, None),
}


def test_the_revision_is_in_a_single_head_chain() -> None:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)

    heads = script.get_heads()
    assert len(heads) == 1
    assert _REVISION in {rev.revision for rev in script.walk_revisions(base="base", head=heads[0])}


@pytest.mark.postgres
class TestStockLocationsMigration:
    def test_upgrade_adds_two_nullable_integer_columns(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.connect() as conn:
            cols = {
                r[0]: (r[1], r[2])
                for r in conn.execute(
                    text(
                        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = 'ml_user_product_stock'"
                    )
                )
            }
        assert cols["full_quantity"] == ("integer", "YES")
        assert cols["own_quantity"] == ("integer", "YES")

    def test_backfill_splits_raw_locations_and_leaves_unreadable_rows_null(self, engine) -> None:
        _run(engine, "upgrade")
        got = {k: v for k, v in _split(engine).items()}
        assert {k: got[k] for k in EXPECTED} == EXPECTED

    def test_backfill_spans_several_batches(self, engine, monkeypatch) -> None:
        migration = _load_migration()
        monkeypatch.setattr(migration, "_BATCH", 3)  # 8 rows -> 3 batches
        _run(engine, "upgrade", migration)
        assert _split(engine) == EXPECTED

    def test_the_backfill_agrees_with_the_python_mapper(self, engine) -> None:
        """Same split for every readable row: SQL backfill and `map_user_product_stock` cannot drift."""
        from app.services.ml_publications.parsers.user_product_stock import map_user_product_stock

        _run(engine, "upgrade")
        got = _split(engine)
        for key, raw, _total in _rows():
            if raw is None:
                continue
            typed = map_user_product_stock(raw)
            assert got[key][:2] == (typed["full_quantity"], typed["own_quantity"]), key

    def test_downgrade_drops_both_columns(self, engine) -> None:
        _run(engine, "upgrade")
        _run(engine, "downgrade")
        with engine.connect() as conn:
            cols = {
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = 'ml_user_product_stock'"
                    )
                )
            }
        assert {"full_quantity", "own_quantity"}.isdisjoint(cols)
        assert "total_quantity" in cols

    def test_upgrade_is_safe_to_replay_over_a_filled_table(self, engine) -> None:
        """A second run (a retry after a crash between batches) must not fail or change a filled row."""
        migration = _load_migration()
        _run(engine, "upgrade", migration)
        _run(engine, "_backfill", migration)
        assert _split(engine) == EXPECTED
