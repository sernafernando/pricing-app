"""The worker's shared `mlpub` schema (`SharedSchema`, behind `mlpub_pg`): one migrated schema reused by every test,
and a reset that hands the next test exactly what a freshly built schema would."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.services.ml_publications.settings_store import get_setting, set_setting
from tests.services.ml_publications.conftest import SHARED_SCHEMA, SharedSchema, _bound

pytestmark = pytest.mark.postgres


@pytest.fixture()
def shared():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    holder = SharedSchema()
    try:
        yield holder
    finally:
        holder.discard()


def schema_exists(engine, name: str) -> bool:
    with engine.connect() as conn:
        return conn.execute(text("SELECT to_regnamespace(:n) IS NOT NULL"), {"n": name}).scalar()


def test_a_committed_write_is_gone_and_the_schema_is_reused(shared, monkeypatch) -> None:
    engine = shared.acquire()
    schema = shared.schema
    with _bound(monkeypatch, engine):
        set_setting("scan.next_mode", "full", updated_by="tester")  # commits through `SessionLocal`
        assert get_setting("scan.next_mode").value == "full"
    shared.release()

    engine = shared.acquire()
    assert shared.schema == schema and shared.built == 1
    with _bound(monkeypatch, engine):
        assert get_setting("scan.next_mode").value != "full"
    with engine.connect() as conn:
        for table in shared._tables:
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table
    shared.release()


def test_what_a_test_creates_is_dropped_and_sequences_start_over(shared) -> None:
    engine = shared.acquire()
    with engine.connect() as conn:
        sequences = conn.execute(
            text("SELECT relname FROM pg_class WHERE relnamespace = to_regnamespace(:s) AND relkind = 'S'"),
            {"s": shared.schema},
        ).scalars()
        before = {name: conn.execute(text(f"SELECT last_value, is_called FROM {name}")).one() for name in sequences}
        assert before
        for name in before:
            conn.execute(text(f"SELECT nextval('{name}')"))
        conn.execute(text("CREATE TABLE a_test_table (id int)"))
        conn.execute(text("CREATE VIEW a_test_view AS SELECT 1 AS x"))
        conn.execute(text("CREATE SEQUENCE a_test_seq"))
        conn.execute(text("CREATE FUNCTION a_test_fn() RETURNS int LANGUAGE sql AS 'SELECT 1'"))
        conn.execute(text("CREATE TYPE a_test_enum AS ENUM ('a')"))
        conn.commit()
    shared.release()

    engine = shared.acquire()
    assert shared.built == 1
    with engine.connect() as conn:
        for name in ("a_test_table", "a_test_view", "a_test_seq"):
            assert conn.execute(text("SELECT to_regclass(:n)"), {"n": name}).scalar() is None, name
        assert conn.execute(text("SELECT to_regproc('a_test_fn')")).scalar() is None
        assert conn.execute(text("SELECT to_regtype('a_test_enum')")).scalar() is None
        after = {name: conn.execute(text(f"SELECT last_value, is_called FROM {name}")).one() for name in before}
    assert after == before
    shared.release()


def test_a_test_that_changes_a_table_gets_the_schema_discarded(shared) -> None:
    engine = shared.acquire()
    schema = shared.schema
    table = shared._tables[0]
    with engine.connect() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN a_test_column int"))
        conn.commit()
    shared.release()
    assert shared.engine is None
    assert not schema_exists(engine, schema)

    engine = shared.acquire()
    assert shared.schema != schema and shared.built == 2
    with engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM pg_attribute WHERE attrelid = to_regclass(:t) AND attname = 'a_test_column'"
                ),
                {"t": table},
            ).scalar()
            == 0
        )
    shared.release()


def test_mlpub_pg_hands_out_the_shared_schema(mlpub_pg) -> None:
    assert SHARED_SCHEMA.in_use and mlpub_pg is SHARED_SCHEMA.engine
