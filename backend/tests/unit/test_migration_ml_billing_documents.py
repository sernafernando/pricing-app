"""ml-billing-balance PR 2b -- migration `20261011_ml_billing_documents`.

Graph layer (always runs): the migration is a single-head continuation of the
chain and its revision stays reachable from whatever the head becomes (the
head is never pinned: a rebase onto a main that added migrations moves it).

Model layer (always runs): `ml_billing_documents` stores ONLY ML's own values.
BD-1 / BS-3 forbid cached aggregates, so there is no stored count, stored sum,
complete flag or checked-at column -- completeness is a query.

Round trip (`@pytest.mark.postgres`): upgrade adds the table and the four
charge columns (existing rows backfilled `document_type='BILL'`, new
`billing_source` defaults to 'general'), downgrade removes all of it.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261011_ml_billing_documents"

_NEW_CHARGE_COLUMNS = {"document_type", "billing_source", "legal_document_number", "legal_document_status"}


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _load_migration():
    path = Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{_REVISION}.py"
    spec = importlib.util.spec_from_file_location("ml_billing_documents_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigrationGraph:
    def test_revision_is_registered_and_linked(self) -> None:
        script = _script_directory()
        revision = script.get_revision(_REVISION)
        assert revision is not None
        assert isinstance(revision.down_revision, str), "exactly one parent, never a branch point"
        assert script.get_revision(revision.down_revision) is not None

    def test_is_single_head_and_revision_is_its_ancestor(self) -> None:
        script = _script_directory()
        heads = script.get_heads()
        assert len(heads) == 1
        chain = {r.revision for r in script.walk_revisions(base="base", head=heads[0])}
        assert _REVISION in chain, f"{_REVISION!r} is not an ancestor of the single head {heads[0]!r}"


class TestModels:
    def test_documents_table_has_no_cached_aggregate_columns(self) -> None:
        from app.models.ml_billing import MlBillingDocument

        columns = set(MlBillingDocument.__table__.columns.keys())
        assert columns.isdisjoint({"stored_count", "stored_sum", "complete", "checked_at"})
        # ML's own values, as the design lists them.
        assert {
            "document_id",
            "group",
            "document_type",
            "period_key",
            "user_id",
            "amount",
            "unpaid_amount",
            "document_status",
            "associated_document_id",
            "count_details",
            "expiration_date",
            "currency_id",
            "site_id",
            "reference_number",
            "legal_point_of_sale",
            "legal_letter",
            "legal_number",
            "files",
            "raw",
            "fetched_at",
        } <= columns

    def test_document_id_is_the_primary_key(self) -> None:
        from app.models.ml_billing import MlBillingDocument

        assert [c.name for c in MlBillingDocument.__table__.primary_key.columns] == ["document_id"]

    def test_charges_gain_the_document_and_legal_columns(self) -> None:
        from app.models.ml_billing import MlBillingCharge

        columns = MlBillingCharge.__table__.columns
        assert _NEW_CHARGE_COLUMNS <= set(columns.keys())
        assert columns["billing_source"].nullable is False
        assert str(columns["billing_source"].server_default.arg).strip("'") == "general"

    def test_charges_have_the_lookup_indexes(self) -> None:
        from app.models.ml_billing import MlBillingCharge

        indexes = {tuple(c.name for c in i.columns) for i in MlBillingCharge.__table__.indexes}
        assert ("period_key", "document_type") in indexes
        assert ("document_id",) in indexes


def _create_pre_2b_charges_table(conn) -> None:
    """`ml_billing_charges` as it exists BEFORE this migration (corte 1)."""
    conn.execute(sa.text("DROP TABLE IF EXISTS ml_billing_documents CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS ml_billing_charges CASCADE"))
    conn.execute(
        sa.text(
            "CREATE TABLE ml_billing_charges ("
            "detail_id VARCHAR(60) PRIMARY KEY, period_key VARCHAR(10), detail_type VARCHAR(60), "
            "detail_sub_type VARCHAR(60), amount NUMERIC(14, 2), document_id VARCHAR(60), "
            "raw_detail JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
    )
    conn.execute(sa.text("CREATE INDEX ix_ml_billing_charges_period_key ON ml_billing_charges (period_key)"))
    conn.execute(sa.text("INSERT INTO ml_billing_charges (detail_id, period_key) VALUES ('1', '2026-09-01')"))


@pytest.mark.postgres
class TestMigrationPostgresRoundTrip:
    def test_upgrade_adds_everything_then_downgrade_removes_it(self, pg_engine) -> None:
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext

        migration = _load_migration()

        with pg_engine.begin() as conn:
            _create_pre_2b_charges_table(conn)

        try:
            with pg_engine.connect() as conn:
                ctx = MigrationContext.configure(conn)
                op_obj = Operations(ctx)
                op_obj._install_proxy()
                try:
                    migration.upgrade()
                    conn.commit()

                    inspector = sa.inspect(conn)
                    assert "ml_billing_documents" in inspector.get_table_names()
                    document_columns = {c["name"] for c in inspector.get_columns("ml_billing_documents")}
                    assert document_columns.isdisjoint({"stored_count", "stored_sum", "complete", "checked_at"})
                    assert {"document_id", "count_details", "amount", "reference_number", "raw"} <= document_columns

                    charge_columns = {c["name"] for c in inspector.get_columns("ml_billing_charges")}
                    assert _NEW_CHARGE_COLUMNS <= charge_columns
                    charge_indexes = {i["name"] for i in inspector.get_indexes("ml_billing_charges")}
                    assert "ix_ml_billing_charges_period_document_type" in charge_indexes
                    assert "ix_ml_billing_charges_document_id" in charge_indexes

                    row = conn.execute(
                        sa.text("SELECT document_type, billing_source FROM ml_billing_charges WHERE detail_id = '1'")
                    ).one()
                    assert tuple(row) == ("BILL", "general")

                    migration.downgrade()
                    conn.commit()

                    inspector = sa.inspect(conn)
                    assert "ml_billing_documents" not in inspector.get_table_names()
                    charge_columns = {c["name"] for c in inspector.get_columns("ml_billing_charges")}
                    assert charge_columns.isdisjoint(_NEW_CHARGE_COLUMNS)
                    charge_indexes = {i["name"] for i in inspector.get_indexes("ml_billing_charges")}
                    assert "ix_ml_billing_charges_document_id" not in charge_indexes
                finally:
                    op_obj._remove_proxy()
        finally:
            with pg_engine.begin() as conn:
                conn.execute(sa.text("DROP TABLE IF EXISTS ml_billing_documents CASCADE"))
                conn.execute(sa.text("DROP TABLE IF EXISTS ml_billing_charges CASCADE"))
