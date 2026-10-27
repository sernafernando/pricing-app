"""Migration `20261201_ml_venta_impuesto_tratamiento`, executed against Postgres.

Runs the real upgrade()/downgrade() inside a throwaway schema holding minimal copies of the tables its trigger
joins, with a stub `order_metrics_enqueue` that records what it is handed.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _BACKEND_ROOT / "alembic" / "versions" / "20261201_ml_venta_impuesto_tratamiento.py"

SCHEMA_DDL = [
    "CREATE TABLE usuarios (id SERIAL PRIMARY KEY)",
    "CREATE TABLE ml_orders_ops (order_id BIGINT PRIMARY KEY, date_created TIMESTAMPTZ)",
    "CREATE TABLE ml_payments_ops (payment_id BIGINT PRIMARY KEY, order_id BIGINT NOT NULL)",
    "CREATE TABLE ml_payment_charges (id BIGSERIAL PRIMARY KEY, payment_id BIGINT NOT NULL, name VARCHAR(120))",
    "CREATE TABLE enqueued (ids BIGINT[], reason TEXT)",
    """
    CREATE FUNCTION order_metrics_enqueue(ids BIGINT[], reason TEXT) RETURNS VOID AS $f$
        INSERT INTO enqueued VALUES (ids, reason)
    $f$ LANGUAGE sql
    """,
    "INSERT INTO ml_orders_ops VALUES (1, '2026-09-10 15:00+00'), (2, '2026-08-10 15:00+00')",
    "INSERT INTO ml_payments_ops VALUES (10, 1), (20, 2)",
    """
    INSERT INTO ml_payment_charges (payment_id, name) VALUES
        (10, 'tax_withholding_sirtac_sobretasa-jujuy'), (20, 'tax_withholding_sirtac_sobretasa-jujuy')
    """,
]


def _load_migration():
    spec = importlib.util.spec_from_file_location("impuesto_tratamiento_migration", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def engine():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"impuesto_trat_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    with eng.begin() as conn:
        for ddl in SCHEMA_DDL:
            conn.execute(text(ddl))
    try:
        yield eng
    finally:
        eng.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin_engine.dispose()


def _run(engine, step: str) -> None:
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    migration = _load_migration()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(migration, step)()


def _scalar(engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar()


@pytest.mark.postgres
class TestImpuestoTratamientoMigration:
    def test_upgrade_creates_the_table_and_its_enqueue_trigger(self, engine) -> None:
        _run(engine, "upgrade")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO ml_venta_impuesto_tratamiento (charge_name, informativo, fecha_desde) "
                    "VALUES ('tax_withholding_sirtac_sobretasa-jujuy', true, '2026-09-01')"
                )
            )
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT ids, reason FROM enqueued")).all()
        assert [(list(r.ids), r.reason) for r in rows] == [([1], "impuesto_tratamiento_insert")]

    def test_a_reversed_range_is_rejected(self, engine) -> None:
        _run(engine, "upgrade")
        with pytest.raises(Exception, match="ck_ml_venta_impuesto_tratamiento_fecha_rango"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO ml_venta_impuesto_tratamiento (charge_name, informativo, fecha_desde, fecha_hasta) "
                        "VALUES ('x', true, '2026-09-01', '2026-08-01')"
                    )
                )

    def test_downgrade_removes_the_table_and_the_function(self, engine) -> None:
        _run(engine, "upgrade")
        _run(engine, "downgrade")
        assert _scalar(engine, "SELECT to_regclass('ml_venta_impuesto_tratamiento')") is None
        assert (
            _scalar(engine, "SELECT count(*) FROM pg_proc WHERE proname = 'order_metrics_enqueue_impuesto_tratamiento'")
            == 0
        )


def _normalized(statements) -> list:
    return [" ".join(statement.split()) for statement in statements]


def test_the_frozen_trigger_copy_matches_the_live_module_it_was_taken_from() -> None:
    """At creation time the migration's frozen DDL and `triggers_tax_treatment.py` (what the fixtures apply) must
    match. A later trigger change gets its own migration and moves this comparison to it."""
    from app.services.order_metrics import triggers_tax_treatment

    migration = _load_migration()
    assert _normalized(migration._TRIGGER_STATEMENTS) == _normalized(triggers_tax_treatment._CREATE_STATEMENTS)
    assert _normalized(migration._DROP_TRIGGER_STATEMENTS) == _normalized(triggers_tax_treatment._DROP_STATEMENTS)
