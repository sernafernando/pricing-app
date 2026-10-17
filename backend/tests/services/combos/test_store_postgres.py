"""Apply a reconcile plan to `combo_componentes` on a real Postgres
(combos-propios C1): the CHECK constraint and `updated_at` are Postgres
behaviour the in-memory SQLite fixture does not prove."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Iterator

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
def pg_session() -> Iterator[Session]:
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
        session = sessionmaker(bind=engine)()
        try:
            yield session
        finally:
            session.close()
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


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
