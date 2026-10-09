"""Migration `20261016_ct_mlo_soh_indexes`: two partial indexes on `tb_commercial_transactions`.

Production plans (2026-10-09, ~604k rows) showed a Seq Scan of the table for the ML metrics join
(`tct.comp_id = tmlod.comp_id AND tct.mlo_id = tmlod.mlo_id`) and for the `ct_soh_id` lookups of
Seriales/Prearmado. The tests pin the graph, the DDL (columns + predicate) and that the planner uses
each index for the real query shape.
"""

from __future__ import annotations

import importlib.util
import os
import uuid

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261016_ct_mlo_soh_indexes"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")

_MLO_QUERY = (
    "SELECT ct_transaction FROM tb_commercial_transactions tct WHERE tct.comp_id = 1 AND tct.mlo_id = 2000012345"
)
_SOH_QUERY = "SELECT ct_transaction FROM tb_commercial_transactions WHERE comp_id = 1 AND ct_soh_id = 123"
_SOH_ONLY_QUERY = "SELECT ct_transaction FROM tb_commercial_transactions WHERE ct_soh_id = 123"


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _migration():
    spec = importlib.util.spec_from_file_location("ct_mlo_soh_indexes_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigrationGraph:
    def test_single_head_that_contains_this_revision(self) -> None:
        script = _script_directory()
        heads = script.get_heads()
        assert len(heads) == 1, heads
        chain = {r.revision for r in script.walk_revisions(base="base", head=heads[0])}
        assert _REVISION in chain, f"{_REVISION!r} is not an ancestor of the single head {heads[0]!r}"

    def test_has_exactly_one_parent(self) -> None:
        revision = _script_directory().get_revision(_REVISION)
        assert isinstance(revision.down_revision, str)


class TestModelMirror:
    def test_the_model_declares_the_indexes_like_the_migration(self) -> None:
        from app.models.commercial_transaction import CommercialTransaction

        by_name = {i.name: i for i in CommercialTransaction.__table__.indexes}
        mlo = by_name["ix_tct_mlo_id_comp_id"]
        soh = by_name["ix_tct_ct_soh_id_comp_id"]
        assert [c.name for c in mlo.columns] == ["mlo_id", "comp_id"]
        assert [c.name for c in soh.columns] == ["ct_soh_id", "comp_id"]
        assert str(mlo.dialect_options["postgresql"]["where"]) == "mlo_id IS NOT NULL"
        assert str(soh.dialect_options["postgresql"]["where"]) == "ct_soh_id IS NOT NULL"


@pytest.fixture
def ct_pg():
    """Throwaway schema with a minimal `tb_commercial_transactions` (only the columns the indexes use)."""
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"ct_idx_t_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    with eng.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE tb_commercial_transactions ("
                "ct_transaction BIGINT PRIMARY KEY, comp_id INTEGER, mlo_id BIGINT, ct_soh_id INTEGER)"
            )
        )
        conn.commit()
    try:
        yield eng
    finally:
        eng.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def _indexdef(conn, name: str) -> str | None:
    return conn.exec_driver_sql(
        "SELECT indexdef FROM pg_indexes WHERE indexname = %s AND schemaname = current_schema()", (name,)
    ).scalar()


def _valid(conn, name: str) -> bool:
    return bool(
        conn.exec_driver_sql(
            "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relname = %s AND n.nspname = current_schema()",
            (name,),
        ).scalar()
    )


def _plan(conn, sql: str) -> str:
    return "\n".join(r[0] for r in conn.execute(text("EXPLAIN " + sql)))


@pytest.mark.postgres
class TestMigrationDdl:
    def test_upgrade_creates_both_valid_partial_indexes_and_downgrade_drops_them(self, ct_pg) -> None:
        module = _migration()
        with ct_pg.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx), ctx.begin_transaction():
                module.downgrade()
                assert _indexdef(conn, "ix_tct_mlo_id_comp_id") is None
                assert _indexdef(conn, "ix_tct_ct_soh_id_comp_id") is None

                module.upgrade()
                mlo = _indexdef(conn, "ix_tct_mlo_id_comp_id")
                soh = _indexdef(conn, "ix_tct_ct_soh_id_comp_id")
                assert "(mlo_id, comp_id)" in mlo and "WHERE (mlo_id IS NOT NULL)" in mlo, mlo
                assert "(ct_soh_id, comp_id)" in soh and "WHERE (ct_soh_id IS NOT NULL)" in soh, soh
                assert _valid(conn, "ix_tct_mlo_id_comp_id") and _valid(conn, "ix_tct_ct_soh_id_comp_id")

                module.upgrade()  # idempotent
                assert _valid(conn, "ix_tct_mlo_id_comp_id")

                module.downgrade()
                assert _indexdef(conn, "ix_tct_mlo_id_comp_id") is None
                assert _indexdef(conn, "ix_tct_ct_soh_id_comp_id") is None

    def test_an_invalid_leftover_of_a_failed_build_is_rebuilt(self, ct_pg) -> None:
        module = _migration()
        with ct_pg.connect() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx), ctx.begin_transaction():
                module.upgrade()
                conn.exec_driver_sql(
                    "UPDATE pg_index SET indisvalid = false WHERE indexrelid = "
                    "(SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE c.relname = 'ix_tct_mlo_id_comp_id' AND n.nspname = current_schema())"
                )
                assert not _valid(conn, "ix_tct_mlo_id_comp_id")
                module.upgrade()
                assert _valid(conn, "ix_tct_mlo_id_comp_id")

    def test_planner_uses_each_index_instead_of_a_seq_scan(self, ct_pg) -> None:
        module = _migration()
        with ct_pg.begin() as seed:
            seed.execute(
                text(
                    "INSERT INTO tb_commercial_transactions (ct_transaction, comp_id, mlo_id, ct_soh_id) "
                    "SELECT g, 1, CASE WHEN g % 3 = 0 THEN 2000000000 + g END, "
                    "CASE WHEN g % 2 = 0 THEN g / 2 END FROM generate_series(1, 100000) g"
                )
            )
            seed.exec_driver_sql("ANALYZE tb_commercial_transactions")
        with ct_pg.connect() as conn:
            before_mlo = _plan(conn, _MLO_QUERY)
            assert "Seq Scan" in before_mlo, before_mlo
            conn.rollback()
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx), ctx.begin_transaction():
                module.upgrade()
            conn.exec_driver_sql("ANALYZE tb_commercial_transactions")
            conn.commit()
            for sql, name in (
                (_MLO_QUERY, "ix_tct_mlo_id_comp_id"),
                (_SOH_QUERY, "ix_tct_ct_soh_id_comp_id"),
                (_SOH_ONLY_QUERY, "ix_tct_ct_soh_id_comp_id"),
            ):
                plan = _plan(conn, sql)
                assert name in plan and "Seq Scan" not in plan, plan
