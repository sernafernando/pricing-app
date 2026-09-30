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

from sqlalchemy import BigInteger

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
