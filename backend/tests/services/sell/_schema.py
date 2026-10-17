"""A throwaway Postgres schema for the `sell_dirty` tests: whatever other tests
left in the shared database (tables, triggers, functions) is invisible inside
it, and dropping it with CASCADE removes everything the test built."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Callable, Iterator, Optional, Sequence

import pytest
from sqlalchemy import Engine, Table, create_engine, text

from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable, _restore_pristine_pg_types


@contextmanager
def throwaway_schema(
    prefix: str,
    tables: Sequence[Table],
    statements: Sequence[str] = (),
    after: Optional[Callable[[Engine], None]] = None,
) -> Iterator[Engine]:
    """Yields an engine whose `search_path` is a fresh schema holding
    `statements` (run first: stand-ins, functions) and `tables` (created from
    the ORM, with real Postgres types), then runs `after`. The schema is dropped
    with CASCADE on exit, whatever happened."""
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    _restore_pristine_pg_types(tables)
    schema = f"{prefix}_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as conn:
            assert conn.execute(text("SELECT current_schema()")).scalar() == schema
            for statement in statements:
                conn.execute(text(statement))
            for table in tables:
                table.create(bind=conn)
        if after is not None:
            after(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()
