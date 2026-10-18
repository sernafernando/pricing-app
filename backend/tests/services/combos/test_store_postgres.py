"""Apply a reconcile plan to `combo_componentes` on a real Postgres
(combos-propios C1): `updated_at`, the advisory lock and the real row counts
are Postgres behaviour the in-memory SQLite fixture does not prove. The CHECK
(cantidad > 0) and the primary key are proven on the migrated table in
`tests/migrations/test_migration_combo_componentes_postgres.py`."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.combo_componente import ComboComponente
from app.services.combos import store
from app.services.combos.reconcile import plan_combo, plan_full
from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable, _restore_pristine_pg_types

D = Decimal
_TABLES = [ComboComponente.__table__]


@pytest.fixture()
def pg_sessions() -> Iterator[sessionmaker]:
    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    _restore_pristine_pg_types(_TABLES)
    schema = f"combo_store_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as conn:
            for table in _TABLES:
                table.create(bind=conn)
        yield sessionmaker(bind=engine)
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


@pytest.fixture()
def pg_session(pg_sessions: sessionmaker) -> Iterator[Session]:
    session = pg_sessions()
    try:
        yield session
    finally:
        session.close()


def _seed(db: Session, rows) -> None:
    for combo, componente, cantidad in rows:
        db.add(ComboComponente(combo_item_id=combo, componente_item_id=componente, cantidad=cantidad))
    db.commit()


@pytest.mark.postgres
class TestApply:
    def test_full_snapshot_round_trip(self, pg_session: Session) -> None:
        _seed(pg_session, [(100, 500, 1), (100, 600, 1), (200, 700, 1)])
        db = pg_session
        before = db.execute(text("SELECT updated_at FROM combo_componentes WHERE componente_item_id = 500")).scalar()

        plan = plan_full({100: {500: D("2"), 601: D("1")}, 200: {700: D("1")}}, store.load_current(db))
        counts = store.apply(db, plan)
        db.commit()

        assert counts == {"inserted": 1, "updated": 1, "deleted": 1}
        assert store.load_current(db) == {100: {500: D("2"), 601: D("1")}, 200: {700: D("1")}}
        after = db.execute(text("SELECT updated_at FROM combo_componentes WHERE componente_item_id = 500")).scalar()
        assert after > before

    def test_a_second_run_with_the_same_snapshot_changes_nothing(self, pg_session: Session) -> None:
        db = pg_session
        snapshot = {100: {500: D("1.5")}}
        store.apply(db, plan_full(snapshot, store.load_current(db)))
        db.commit()
        assert plan_full(snapshot, store.load_current(db)).is_empty

    def test_load_combo_and_per_combo_apply_leave_other_combos_alone(self, pg_session: Session) -> None:
        _seed(pg_session, [(100, 500, 1), (100, 600, 1), (200, 700, 1)])
        db = pg_session

        plan = plan_combo(100, {500: D("1")}, store.load_combo(db, 100))
        store.apply(db, plan)
        db.commit()

        assert store.load_current(db) == {100: {500: D("1")}, 200: {700: D("1")}}

    def test_counts_are_the_rows_actually_written(self, pg_sessions: sessionmaker) -> None:
        # The plan is computed, then an out-of-band writer gets there first: the counts must
        # say what this apply changed, and a pair that is already there must not raise.
        db = pg_sessions()
        other = pg_sessions()
        try:
            _seed(db, [(100, 500, 1), (100, 600, 1), (200, 700, 1)])
            plan = plan_full({100: {500: D("2"), 601: D("1"), 602: D("1")}, 200: {}}, store.load_current(db))
            db.commit()
            assert len(plan.inserts) == 2 and len(plan.updates) == 1 and len(plan.deletes) == 2

            other.execute(
                text("INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES (100, 601, 1)")
            )
            other.execute(text("UPDATE combo_componentes SET cantidad = 2 WHERE componente_item_id = 500"))
            other.execute(text("DELETE FROM combo_componentes WHERE componente_item_id = 700"))
            other.commit()

            counts = store.apply(db, plan)
            db.commit()

            assert counts == {"inserted": 1, "updated": 0, "deleted": 1}
            assert store.load_current(db) == {100: {500: D("2"), 601: D("1"), 602: D("1")}}
        finally:
            db.close()
            other.close()

    def test_load_takes_the_reconcile_lock_until_the_transaction_ends(self, pg_sessions: sessionmaker) -> None:
        # load + apply must be one critical section: a second reconcile waits for the first to commit.
        db = pg_sessions()
        other = pg_sessions()
        try:
            store.load_current(db)
            assert other.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": store.LOCK_KEY}).scalar() is False
            other.rollback()
            db.commit()
            store.load_combo(db, 100)
            assert other.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": store.LOCK_KEY}).scalar() is False
            other.rollback()
            db.rollback()
            assert other.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": store.LOCK_KEY}).scalar() is True
        finally:
            db.close()
            other.close()
