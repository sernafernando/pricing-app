"""
T2.2 — Migration tests for F7/PR#2a: compras_032 (banco_movimientos + BancoEmpresa cols).

Tests DDL intent against in-memory SQLite (mirrors existing test_migration_f2.py pattern).
compras_033 (ordenes_pago banco columns) is included in PR#2a diff but tested via
the model-level tests in test_models_f7_banco.py (column presence on OrdenPago).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool


def _make_engine() -> sa.Engine:
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _create_base_schema(engine: sa.Engine) -> None:
    """Create pre-migration state: bancos_empresa without saldo_actual / empresa_id."""
    with engine.connect() as conn:
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS bancos_empresa (
                id INTEGER PRIMARY KEY,
                banco TEXT NOT NULL,
                tipo_cuenta TEXT,
                cbu TEXT UNIQUE,
                alias TEXT,
                numero_cuenta TEXT,
                sucursal TEXT,
                moneda TEXT NOT NULL DEFAULT 'ARS',
                titular TEXT,
                cuit_titular TEXT,
                saldo_inicial NUMERIC(18,2) NOT NULL DEFAULT 0,
                notas TEXT,
                activo INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT
            )
            """)
        )
        conn.commit()


def _apply_upgrade_032(engine: sa.Engine) -> None:
    """Apply compras_032 upgrade DDL (SQLite-compatible subset)."""
    with engine.connect() as conn:
        # Create banco_movimientos table
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS banco_movimientos (
                id INTEGER PRIMARY KEY,
                banco_id INTEGER NOT NULL,
                fecha TEXT NOT NULL,
                detalle TEXT NOT NULL,
                tipo TEXT NOT NULL,
                monto NUMERIC(18,2) NOT NULL,
                saldo_posterior NUMERIC(18,2) NOT NULL,
                origen TEXT NOT NULL DEFAULT 'manual',
                registrado_por_id INTEGER,
                observaciones TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """)
        )
        # Add saldo_actual to bancos_empresa (NOT NULL with server_default 0)
        conn.execute(text("ALTER TABLE bancos_empresa ADD COLUMN saldo_actual NUMERIC(18,2) NOT NULL DEFAULT 0"))
        # Backfill: saldo_actual = saldo_inicial for existing rows
        conn.execute(text("UPDATE bancos_empresa SET saldo_actual = saldo_inicial"))
        # Add empresa_id NULLABLE (no backfill per AD-13)
        conn.execute(text("ALTER TABLE bancos_empresa ADD COLUMN empresa_id INTEGER"))
        conn.commit()


def _apply_downgrade_032(engine: sa.Engine) -> None:
    """Apply compras_032 downgrade: drop banco_movimientos, drop columns from bancos_empresa."""
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS banco_movimientos"))
        # SQLite doesn't support DROP COLUMN pre-3.35; we skip that part
        # The upgrade/downgrade symmetry is verified at the Postgres level
        conn.commit()


class TestMigration032CreateBancoMovimientos:
    """compras_032 creates banco_movimientos and adds columns to bancos_empresa."""

    def test_upgrade_creates_banco_movimientos_table(self) -> None:
        engine = _make_engine()
        _create_base_schema(engine)
        _apply_upgrade_032(engine)

        tables = inspect(engine).get_table_names()
        assert "banco_movimientos" in tables

    def test_banco_movimientos_has_required_columns(self) -> None:
        engine = _make_engine()
        _create_base_schema(engine)
        _apply_upgrade_032(engine)

        cols = {c["name"] for c in inspect(engine).get_columns("banco_movimientos")}
        required = {
            "id",
            "banco_id",
            "fecha",
            "detalle",
            "tipo",
            "monto",
            "saldo_posterior",
            "origen",
            "registrado_por_id",
            "observaciones",
        }
        assert required <= cols, f"Missing columns: {required - cols}"

    def test_upgrade_adds_saldo_actual_column(self) -> None:
        engine = _make_engine()
        _create_base_schema(engine)
        _apply_upgrade_032(engine)

        cols = {c["name"] for c in inspect(engine).get_columns("bancos_empresa")}
        assert "saldo_actual" in cols

    def test_upgrade_adds_empresa_id_column(self) -> None:
        engine = _make_engine()
        _create_base_schema(engine)
        _apply_upgrade_032(engine)

        cols = {c["name"] for c in inspect(engine).get_columns("bancos_empresa")}
        assert "empresa_id" in cols

    def test_backfill_saldo_actual_equals_saldo_inicial(self) -> None:
        engine = _make_engine()
        _create_base_schema(engine)

        # Insert a banco with known saldo_inicial BEFORE migration
        with engine.connect() as conn:
            conn.execute(
                text("INSERT INTO bancos_empresa (banco, moneda, saldo_inicial) VALUES ('Banco Test', 'ARS', 5000)")
            )
            conn.commit()

        _apply_upgrade_032(engine)

        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT saldo_actual, saldo_inicial FROM bancos_empresa WHERE banco = 'Banco Test'")
            ).fetchone()
        assert row is not None
        assert float(row[0]) == float(row[1]), (
            f"saldo_actual ({row[0]}) should equal saldo_inicial ({row[1]}) after backfill"
        )

    def test_empresa_id_is_nullable_no_backfill(self) -> None:
        """empresa_id must be NULL for existing rows (AD-13 — no backfill)."""
        engine = _make_engine()
        _create_base_schema(engine)

        # Insert a banco BEFORE migration
        with engine.connect() as conn:
            conn.execute(
                text("INSERT INTO bancos_empresa (banco, moneda, saldo_inicial) VALUES ('Banco Test', 'ARS', 0)")
            )
            conn.commit()

        _apply_upgrade_032(engine)

        with engine.connect() as conn:
            row = conn.execute(text("SELECT empresa_id FROM bancos_empresa WHERE banco = 'Banco Test'")).fetchone()
        assert row is not None
        assert row[0] is None, f"empresa_id should be NULL for existing rows, got {row[0]}"

    def test_downgrade_drops_banco_movimientos(self) -> None:
        engine = _make_engine()
        _create_base_schema(engine)
        _apply_upgrade_032(engine)
        _apply_downgrade_032(engine)

        tables = inspect(engine).get_table_names()
        assert "banco_movimientos" not in tables
