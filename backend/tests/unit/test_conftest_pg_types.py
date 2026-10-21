"""Pins a real incident: `_restore_pristine_pg_types` failed to undo
`_patch_pg_types_for_sqlite`'s BigInteger-PK -> Integer downgrade.

WHY THIS EXISTS. `_patch_pg_types_for_sqlite()` mutates shared `Column`
objects on `Base.metadata` in TWO ways: it remaps PG-only types (JSONB/
UUID/Vector/ARRAY) via `_PG_TYPE_MAP`, AND it separately downgrades any
BigInteger primary-key column to `Integer` (so SQLite's AUTOINCREMENT
kicks in). `_PRISTINE_PG_COLUMN_TYPES` only snapshotted the FIRST kind
(`isinstance(column.type, tuple(_PG_TYPE_MAP.keys()))`), so
`_restore_pristine_pg_types()` was a no-op for every BigInteger PK column
-- including `MlOrdersOps.order_id`.

Concretely: once ANY code path called `_patch_pg_types_for_sqlite()` in a
pytest session (the SQLite `engine` fixture, or a Postgres-only fixture's
own "leave it patched for SQLite" teardown/setup step), `order_id` stayed
`Integer` for the REST of the session -- `_restore_pristine_pg_types`
could not put it back to `BigInteger`. A later Postgres-only fixture then
built `CREATE TABLE ml_orders_ops (order_id SERIAL ...)` instead of
`BIGSERIAL`, and any real ML order id above 2**31-1 (e.g.
`2000018641457084`) blew up with `NumericValueOutOfRange` --
order-dependent, reproducing exactly the
`test_filters_switches_postgres.py` -> `test_accreditation_postgres.py`
failure sequence.
"""

from __future__ import annotations

import pytest
from sqlalchemy import BigInteger, create_engine, text

from app.models.ml_orders_ops import MlOrdersOps
from tests.conftest import _PRISTINE_PG_COLUMN_TYPES, _patch_pg_types_for_sqlite, _restore_pristine_pg_types


def test_restore_pristine_pg_types_undoes_bigint_pk_downgrade() -> None:
    """`order_id` must always come back as `BigInteger` after a restore,
    regardless of how many times `_patch_pg_types_for_sqlite()` already
    ran earlier in the session.

    Deliberately does NOT assert on `column.type`'s value when this test
    starts: this module-level `Column` is process-global and mutable, and
    whether some OTHER test already ran `_patch_pg_types_for_sqlite()`
    first depends on collection order -- exactly the kind of
    order-dependence this test exists to pin down, so asserting on it
    would just relocate the same bug into the test itself. Instead it
    reads the real pristine type from `_PRISTINE_PG_COLUMN_TYPES` (snapshotted
    at import time, before any test could have mutated it) and forces the
    column back to that as ITS OWN starting state.
    """
    column = MlOrdersOps.__table__.c.order_id
    pristine_type = _PRISTINE_PG_COLUMN_TYPES[column]
    assert isinstance(pristine_type, BigInteger), "test precondition: the pristine snapshot must be BigInteger"

    original_type = column.type
    try:
        column.type = pristine_type

        _patch_pg_types_for_sqlite()
        assert isinstance(column.type, BigInteger) is False, (
            "test precondition: the patch must actually have downgraded the column"
        )

        _restore_pristine_pg_types([MlOrdersOps.__table__])

        assert isinstance(column.type, BigInteger), (
            "order_id came back as "
            f"{type(column.type).__name__}, not BigInteger -- "
            "_restore_pristine_pg_types must undo the BigInteger-PK-to-Integer "
            "downgrade too, not just the _PG_TYPE_MAP remaps"
        )
    finally:
        # Never leak a mutated shared Column into the rest of the session,
        # whatever this test's outcome.
        column.type = original_type


@pytest.mark.postgres
def test_pg_payments_engine_builds_bigint_ids_after_the_sqlite_patch(engine, pg_payments_engine) -> None:
    """`pg_payments_engine` must build `ml_payments_ops` with production's
    BIGINT ids even when the SQLite `engine` fixture (requested FIRST here)
    already downgraded the shared BigInteger PK columns to `Integer`.

    The table is session-scoped and other Postgres fixtures (the board's
    `board_pg_engine`) REUSE an existing table instead of creating their own,
    so an INTEGER `payment_id` built here leaked into the board's volume seed
    (`payment_id = order_id * 10 + 1`, ~3.5e16) as `NumericValueOutOfRange`
    -- only on the xdist workers where this fixture happened to run first.
    """
    with pg_payments_engine.connect() as conn:
        types = dict(
            conn.execute(
                text(
                    "SELECT table_name || '.' || column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = current_schema() "
                    "AND (table_name, column_name) IN (('ml_payments_ops', 'payment_id'), "
                    "('ml_payments_ops', 'order_id'), ('ml_payment_charges', 'id'))"
                )
            ).all()
        )
    assert types == {
        "ml_payments_ops.payment_id": "bigint",
        "ml_payments_ops.order_id": "bigint",
        "ml_payment_charges.id": "bigint",
    }


# The four module-scoped `pg_order_metrics*` fixtures drop `ml_payments_ops`,
# `ml_payment_charges` and `ml_orders_ops` unconditionally on teardown, while
# `pg_payments_engine`/`pg_orders_ops_engine` build them ONCE per session. On
# the same xdist worker, a later user of the session engine found them gone.
# These fixtures simulate that teardown: they run AFTER the session engine
# was built (higher scope instantiates first) and BEFORE the function-scoped
# engine the test receives, via a raw engine so they never touch ours.
@pytest.fixture()
def _payments_tables_dropped_by_a_module_teardown():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip("PostgreSQL not reachable")
    eng = create_engine(POSTGRES_TEST_URL)
    with eng.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS ml_payment_charges, ml_payments_ops CASCADE"))
    eng.dispose()


@pytest.fixture()
def _orders_ops_table_dropped_by_a_module_teardown():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip("PostgreSQL not reachable")
    eng = create_engine(POSTGRES_TEST_URL)
    with eng.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS ml_orders_ops CASCADE"))
    eng.dispose()


def _column_types(eng, pairs: str) -> dict[str, str]:
    with eng.connect() as conn:
        return dict(
            conn.execute(
                text(
                    "SELECT table_name || '.' || column_name, data_type FROM information_schema.columns "
                    f"WHERE table_schema = current_schema() AND (table_name, column_name) IN ({pairs})"
                )
            ).all()
        )


@pytest.mark.postgres
def test_pg_payments_engine_recreates_tables_a_module_fixture_dropped(
    engine, _payments_tables_dropped_by_a_module_teardown, pg_payments_engine
) -> None:
    """A module fixture's teardown dropping the session tables must not
    strand the next `pg_payments_engine` user -- and the recreated tables keep
    production's BIGINT ids even though the SQLite `engine` already ran."""
    assert _column_types(
        pg_payments_engine,
        "('ml_payments_ops', 'payment_id'), ('ml_payments_ops', 'order_id'), ('ml_payment_charges', 'id')",
    ) == {
        "ml_payments_ops.payment_id": "bigint",
        "ml_payments_ops.order_id": "bigint",
        "ml_payment_charges.id": "bigint",
    }


@pytest.mark.postgres
def test_pg_orders_ops_engine_recreates_the_table_a_module_fixture_dropped(
    engine, _orders_ops_table_dropped_by_a_module_teardown, pg_orders_ops_engine
) -> None:
    """Same race as above, for `ml_orders_ops` (16-digit ML order ids)."""
    assert _column_types(pg_orders_ops_engine, "('ml_orders_ops', 'order_id')") == {
        "ml_orders_ops.order_id": "bigint",
    }
