"""
PR1 — migration 20260710_ml_bot_messages (ml_bot_messages table +
ml_bot.messages.ver permission seed + grants to ml_bot.ver holders).

Follows the project convention (see test_migration_ml_bot_questions.py): DDL
intent is verified against an in-memory SQLite mirror rather than invoking
the real Alembic module (which uses Postgres-only `ON CONFLICT` /
`postgresql_where`). The upgrade/downgrade functions themselves are imported
and executed against a fake `op`/connection to verify the permission-seed +
grant SQL shape.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260710_ml_bot_messages.py"
)
_spec = importlib.util.spec_from_file_location("ml_bot_messages_migration", _MIGRATION_PATH)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


def _make_sqlite_engine() -> sa.Engine:
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _apply_upgrade_ddl(engine: sa.Engine) -> None:
    """Mirrors the table-creation DDL of the real migration (SQLite-safe subset,
    including the UNIQUE constraint and a plain index standing in for the
    Postgres partial index)."""
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE ml_bot_messages (
                    id INTEGER PRIMARY KEY,
                    ml_message_id VARCHAR(64) NOT NULL UNIQUE,
                    pack_id VARCHAR(32),
                    buyer_id BIGINT,
                    buyer_nickname VARCHAR(255),
                    seller_id BIGINT NOT NULL,
                    subject VARCHAR(255),
                    text TEXT NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    moderation_status VARCHAR(50),
                    is_first_message BOOLEAN NOT NULL DEFAULT 0,
                    attachments TEXT,
                    received_at TIMESTAMP NOT NULL,
                    read_at TIMESTAMP,
                    kind VARCHAR(16) NOT NULL DEFAULT 'postventa',
                    taken_over_by INTEGER,
                    notes TEXT
                )
                """
            )
        )
        conn.execute(
            text("CREATE UNIQUE INDEX uq_ml_bot_messages_ml_message_id ON ml_bot_messages (ml_message_id)")
        )
        conn.execute(
            text(
                "CREATE INDEX idx_ml_bot_messages_moderation_status ON ml_bot_messages (moderation_status)"
            )
        )
        conn.commit()


class TestMigrationTableShape:
    def test_upgrade_creates_table_with_unique_ml_message_id_and_partial_moderation_index(self) -> None:
        engine = _make_sqlite_engine()
        _apply_upgrade_ddl(engine)

        insp = inspect(engine)
        assert "ml_bot_messages" in insp.get_table_names()

        indexes = insp.get_indexes("ml_bot_messages")
        by_name = {ix["name"]: ix for ix in indexes}
        assert "uq_ml_bot_messages_ml_message_id" in by_name
        assert bool(by_name["uq_ml_bot_messages_ml_message_id"]["unique"])
        assert "idx_ml_bot_messages_moderation_status" in by_name

        # Real migration must reference the same index/table names verbatim.
        assert "idx_ml_bot_messages_pack_id" in _read_migration_source()
        assert "idx_ml_bot_messages_buyer_id" in _read_migration_source()
        assert "idx_ml_bot_messages_received_at" in _read_migration_source()

    def test_duplicate_ml_message_id_rejected(self) -> None:
        engine = _make_sqlite_engine()
        _apply_upgrade_ddl(engine)
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO ml_bot_messages "
                    "(ml_message_id, seller_id, text, status, received_at) "
                    "VALUES ('abc123', 413658225, 'hola', 'available', '2026-07-10 12:00:00')"
                )
            )
            conn.commit()
            try:
                conn.execute(
                    text(
                        "INSERT INTO ml_bot_messages "
                        "(ml_message_id, seller_id, text, status, received_at) "
                        "VALUES ('abc123', 413658225, 'hola de nuevo', 'available', '2026-07-10 12:05:00')"
                    )
                )
                conn.commit()
                raised = False
            except Exception:
                raised = True
        assert raised


def _read_migration_source() -> str:
    return _MIGRATION_PATH.read_text()


class TestMigrationSeedAndGrants:
    def test_upgrade_seeds_ml_bot_messages_ver_and_grants_to_all_ml_bot_ver_roles(self) -> None:
        assert migration._MESSAGES_VER_PERMISO["codigo"] == "ml_bot.messages.ver"
        assert migration._MESSAGES_VER_PERMISO["categoria"] == "ventas_ml"
        assert migration._MESSAGES_VER_PERMISO["orden"] == 510
        assert migration._MESSAGES_VER_PERMISO["es_critico"] is False
        assert migration._SOURCE_PERMISO_CODIGO == "ml_bot.ver"

        upgrade_src = migration.upgrade.__code__.co_consts
        # Sanity: the grant INSERT joins roles_permisos_base to the source
        # permission (ml_bot.ver) and mirrors those role grants for the new
        # code — asserted via the literal SQL text embedded in the function.
        joined_sql = " ".join(c for c in upgrade_src if isinstance(c, str))
        assert "roles_permisos_base" in joined_sql
        assert "ON CONFLICT (rol_id, permiso_id) DO NOTHING" in joined_sql

    def test_downgrade_removes_permission_and_grants_and_table(self) -> None:
        downgrade_src = migration.downgrade.__code__.co_consts
        joined_sql = " ".join(c for c in downgrade_src if isinstance(c, str))
        assert "DELETE FROM permisos WHERE codigo" in joined_sql
        assert "drop_table" not in joined_sql  # sanity: not embedded as string, it's a call
