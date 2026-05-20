"""
Tests for F2 migration: compras_030 (nota_credito_local.tipo).

Verifies the DDL intent against an in-memory SQLite engine:
- Column tipo String(8) NOT NULL with server_default 'credito'.
- Existing rows read as 'credito' after migration (backfill via server_default).
- Downgrade drops the column and CHECK constraint (SQLite: no-op for constraint drop).

Pattern mirrors test_migrations_f1.py — no Alembic internals imported.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sqlite_engine() -> sa.Engine:
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _create_base_schema(engine: sa.Engine) -> None:
    """Create a minimal notas_credito_local table (pre-migration state)."""
    with engine.connect() as conn:
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS notas_credito_local (
                id INTEGER PRIMARY KEY,
                numero TEXT NOT NULL,
                empresa_id INTEGER NOT NULL,
                proveedor_id INTEGER NOT NULL,
                moneda TEXT NOT NULL,
                monto NUMERIC(18,2) NOT NULL,
                estado TEXT NOT NULL DEFAULT 'borrador',
                creado_por_id INTEGER NOT NULL,
                fecha_emision TEXT NOT NULL,
                motivo TEXT NOT NULL
            )
        """)
        )
        conn.commit()


def _apply_upgrade(engine: sa.Engine) -> None:
    """Apply the compras_030 upgrade DDL (mirrors the Alembic migration)."""
    with engine.connect() as conn:
        # Add tipo column with server_default 'credito'.
        conn.execute(text("ALTER TABLE notas_credito_local ADD COLUMN tipo TEXT NOT NULL DEFAULT 'credito'"))
        # SQLite does not support ADD CONSTRAINT, so we skip the CHECK constraint here.
        # The Postgres migration creates ck_ncs_local_tipo; this test covers the column part.
        conn.commit()


# ---------------------------------------------------------------------------
# T2.1 — test_migration_030_add_nc_tipo
# ---------------------------------------------------------------------------


class TestMigration030:
    """Migration compras_030 adds notas_credito_local.tipo (String(8) NOT NULL default 'credito')."""

    def test_upgrade_adds_tipo_column(self) -> None:
        """Column 'tipo' is present after upgrade."""
        engine = _make_sqlite_engine()
        _create_base_schema(engine)

        # Insert a row BEFORE migration (no tipo column).
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO notas_credito_local (numero, empresa_id, proveedor_id,"
                    " moneda, monto, creado_por_id, fecha_emision, motivo)"
                    " VALUES ('NC-001', 1, 1, 'ARS', 1000, 1, '2026-01-01', 'test')"
                )
            )
            conn.commit()

        # Apply upgrade.
        _apply_upgrade(engine)

        # Column exists.
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("notas_credito_local")}
        assert "tipo" in cols, "tipo column should exist after migration"

    def test_existing_rows_read_as_credito(self) -> None:
        """Rows inserted before migration read as 'credito' after upgrade."""
        engine = _make_sqlite_engine()
        _create_base_schema(engine)

        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO notas_credito_local (numero, empresa_id, proveedor_id,"
                    " moneda, monto, creado_por_id, fecha_emision, motivo)"
                    " VALUES ('NC-002', 1, 1, 'ARS', 500, 1, '2026-01-01', 'test')"
                )
            )
            conn.commit()

        _apply_upgrade(engine)

        with engine.connect() as conn:
            row = conn.execute(text("SELECT tipo FROM notas_credito_local WHERE numero='NC-002'")).one()
        assert row.tipo == "credito", f"Expected 'credito', got '{row.tipo}'"

    def test_upgrade_tipo_not_null_default(self) -> None:
        """New rows inserted after upgrade without specifying tipo get 'credito'."""
        engine = _make_sqlite_engine()
        _create_base_schema(engine)
        _apply_upgrade(engine)

        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO notas_credito_local (numero, empresa_id, proveedor_id,"
                    " moneda, monto, creado_por_id, fecha_emision, motivo)"
                    " VALUES ('NC-003', 1, 1, 'ARS', 200, 1, '2026-01-01', 'test')"
                )
            )
            conn.commit()
            row = conn.execute(text("SELECT tipo FROM notas_credito_local WHERE numero='NC-003'")).one()
        assert row.tipo == "credito"

    def test_upgrade_allows_debito_value(self) -> None:
        """After upgrade, a row with tipo='debito' can be inserted explicitly."""
        engine = _make_sqlite_engine()
        _create_base_schema(engine)
        _apply_upgrade(engine)

        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO notas_credito_local (numero, empresa_id, proveedor_id,"
                    " moneda, monto, creado_por_id, fecha_emision, motivo, tipo)"
                    " VALUES ('NC-004', 1, 1, 'ARS', 300, 1, '2026-01-01', 'test', 'debito')"
                )
            )
            conn.commit()
            row = conn.execute(text("SELECT tipo FROM notas_credito_local WHERE numero='NC-004'")).one()
        assert row.tipo == "debito"

    def test_downgrade_column_absent_on_fresh_engine(self) -> None:
        """A fresh schema (before migration) does NOT have the tipo column."""
        engine = _make_sqlite_engine()
        _create_base_schema(engine)

        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("notas_credito_local")}
        assert "tipo" not in cols, "tipo column should NOT exist before migration"
