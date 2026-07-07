"""
T-A3/T-A4/T-A5 — migration 20260706_ml_bot (ml_bot_questions/config/answer_examples
+ ml_bot.* permission seed).

Follows the project convention (see test_migrations_f1.py): DDL intent is
verified against an in-memory SQLite mirror rather than invoking the real
Alembic module (which uses Postgres-only `ON CONFLICT` / `postgresql_where`).
Seed *data* (config defaults, few-shot examples, permission codes) is verified
by importing the migration module directly and asserting on its constants —
this exercises the actual values that ship, not a re-typed copy.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

# The migration filename starts with a digit (`20260706_ml_bot_questions.py`),
# so it isn't importable as a normal dotted module — load it by file path.
_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260706_ml_bot_questions.py"
)
_spec = importlib.util.spec_from_file_location("ml_bot_questions_migration", _MIGRATION_PATH)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


def _make_sqlite_engine() -> sa.Engine:
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _apply_upgrade_ddl(engine: sa.Engine) -> None:
    """Mirrors the table-creation DDL of the real migration (SQLite-safe subset)."""
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE ml_bot_questions (
                    id INTEGER PRIMARY KEY,
                    ml_question_id BIGINT NOT NULL UNIQUE,
                    item_id VARCHAR(32) NOT NULL,
                    buyer_id BIGINT,
                    buyer_nickname VARCHAR(255),
                    question_text TEXT NOT NULL,
                    question_date TIMESTAMP NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'received',
                    drafted_answer TEXT,
                    answer_source VARCHAR(10),
                    confidence NUMERIC(4,3),
                    category VARCHAR(40),
                    injection_flag BOOLEAN NOT NULL DEFAULT 0,
                    fallback_used BOOLEAN NOT NULL DEFAULT 0,
                    wait_until TIMESTAMP,
                    published_at TIMESTAMP,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    taken_over_by INTEGER
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE ml_bot_config (
                    clave VARCHAR(100) PRIMARY KEY,
                    valor TEXT NOT NULL,
                    descripcion TEXT,
                    tipo VARCHAR(50) DEFAULT 'string'
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE ml_bot_answer_examples (
                    id INTEGER PRIMARY KEY,
                    question_example TEXT NOT NULL,
                    answer_example TEXT NOT NULL,
                    category VARCHAR(40),
                    active BOOLEAN NOT NULL DEFAULT 1,
                    orden INTEGER DEFAULT 0
                )
                """
            )
        )
        conn.commit()


class TestMigrationTableShape:
    def test_upgrade_creates_all_three_tables(self) -> None:
        engine = _make_sqlite_engine()
        _apply_upgrade_ddl(engine)

        insp = inspect(engine)
        tables = set(insp.get_table_names())
        assert {"ml_bot_questions", "ml_bot_config", "ml_bot_answer_examples"} <= tables

    def test_ml_bot_questions_default_status_received(self) -> None:
        engine = _make_sqlite_engine()
        _apply_upgrade_ddl(engine)
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO ml_bot_questions (ml_question_id, item_id, question_text, question_date) "
                    "VALUES (1, 'MLA1', 'q?', '2026-07-06 20:00:00')"
                )
            )
            conn.commit()
            row = conn.execute(text("SELECT status, injection_flag, attempts FROM ml_bot_questions")).one()
        assert row.status == "received"
        assert int(row.injection_flag) == 0
        assert row.attempts == 0


class TestMigrationSeedData:
    """Assert on the real migration module's constants (not a re-typed copy)."""

    def test_config_defaults_include_required_keys(self) -> None:
        keys = {row["clave"] for row in migration._CONFIG_DEFAULTS}
        expected = {
            "bot_enabled",
            "operating_mode",
            "business_hours_start",
            "business_hours_end",
            "business_days",
            "timezone",
            "wait_minutes",
            "wait_minutes_business_hours",
            "approx_address",
            "warm_fallback_template",
            "min_confidence",
            "llm_model",
            "poll_interval_seconds",
            "ingest_cursor_ts",
        }
        assert expected <= keys

    def test_bot_disabled_and_off_hours_only_by_default(self) -> None:
        by_key = {row["clave"]: row["valor"] for row in migration._CONFIG_DEFAULTS}
        assert by_key["bot_enabled"] == "false"
        assert by_key["operating_mode"] == "off_hours_only"
        assert by_key["wait_minutes"] == "5"

    def test_few_shot_examples_seed_has_minimum_five_rows(self) -> None:
        assert len(migration._ANSWER_EXAMPLES) >= 5
        categories = {row["category"] for row in migration._ANSWER_EXAMPLES}
        assert "stock" in categories
        assert "fallback" in categories

    def test_permission_codes_match_spec_r1001(self) -> None:
        codes = {row["codigo"] for row in migration._PERMISOS_NUEVOS}
        assert codes == {"ml_bot.ver", "ml_bot.responder", "ml_bot.config", "ml_bot.on_off"}

    def test_config_and_on_off_permissions_are_critical(self) -> None:
        by_code = {row["codigo"]: row["es_critico"] for row in migration._PERMISOS_NUEVOS}
        assert by_code["ml_bot.config"] is True
        assert by_code["ml_bot.on_off"] is True

    def test_permissions_granted_only_to_admin_role(self) -> None:
        assert migration._ADMIN_ROL_CODIGO == "ADMIN"
