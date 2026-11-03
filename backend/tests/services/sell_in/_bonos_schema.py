"""A throwaway Postgres schema with the bonus tables built from the ORM and bare stand-ins of what they reference
(shared by the bonus-list filter tests), read through `autoflush=False` sessions like production's."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator, Sequence

import pytest
from sqlalchemy import Engine, create_engine, text

from app.core.database import Base


@contextmanager
def bonos_schema(prefix: str, tablas: Sequence[str], stubs: Sequence[str]) -> Iterator[Engine]:
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable, _restore_pristine_pg_types

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"{prefix}_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    tables = [Base.metadata.tables[nombre] for nombre in tablas]
    found = {column: column.type for table in tables for column in table.columns}
    try:
        with eng.begin() as conn:
            for statement in stubs:
                conn.execute(text(statement))
        _restore_pristine_pg_types(tables)
        try:
            Base.metadata.create_all(bind=eng, tables=tables)
        finally:
            for column, column_type in found.items():
                column.type = column_type
        yield eng
    finally:
        eng.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()
