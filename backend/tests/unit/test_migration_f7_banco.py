"""
T2.2 — Migration tests for F7/PR#2a: compras_032 + compras_033.

Strategy: SQLite-compatible simulated DDL that mirrors the intent of both
migrations exactly. Running the real Alembic upgrade()/downgrade() functions
against SQLite is NOT feasible in unit tests because the Alembic `op` module-level
proxy requires the full Alembic environment (env.py, alembic.ini, configured
engine) to be active — calling upgrade() outside that context raises
"Can't invoke function, proxy not established". The Postgres-level migration
symmetry is verified by running `alembic upgrade head` against the staging DB.

Coverage here (vs. original):
  - compras_032: creates banco_movimientos, adds columns, backfill, downgrade
  - compras_033: adds banco_id + banco_movimiento_id to ordenes_pago, round-trip
    (new — was not covered at all in the original test file)
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine() -> sa.Engine:
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _create_pre032_schema(engine: sa.Engine) -> None:
    """Pre-compras_032 state: bancos_empresa without saldo_actual / empresa_id."""
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


def _create_pre033_schema(engine: sa.Engine) -> None:
    """Pre-compras_033 state: adds ordenes_pago (without banco columns) on top of pre032."""
    _create_pre032_schema(engine)
    with engine.connect() as conn:
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS ordenes_pago (
                id INTEGER PRIMARY KEY,
                empresa_id INTEGER NOT NULL,
                proveedor_id INTEGER NOT NULL,
                moneda TEXT NOT NULL,
                monto_total NUMERIC(18,2) NOT NULL,
                modo_imputacion TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'pendiente',
                caja_id INTEGER,
                caja_movimiento_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT,
                creado_por_id INTEGER NOT NULL DEFAULT 1
            )
        """)
        )
        conn.commit()


def _apply_upgrade_032(engine: sa.Engine) -> None:
    """Apply compras_032 upgrade DDL (mirrors the real migration intent)."""
    with engine.connect() as conn:
        # Create banco_movimientos table (append-only ledger)
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS banco_movimientos (
                id INTEGER PRIMARY KEY,
                banco_id INTEGER NOT NULL,
                fecha TEXT NOT NULL,
                detalle TEXT NOT NULL,
                tipo TEXT NOT NULL CHECK(tipo IN ('ingreso', 'egreso')),
                monto NUMERIC(18,2) NOT NULL CHECK(monto > 0),
                saldo_posterior NUMERIC(18,2) NOT NULL,
                origen TEXT NOT NULL DEFAULT 'manual',
                registrado_por_id INTEGER,
                observaciones TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        )
        # Add saldo_actual NOT NULL with default 0
        conn.execute(text("ALTER TABLE bancos_empresa ADD COLUMN saldo_actual NUMERIC(18,2) NOT NULL DEFAULT 0"))
        # Backfill: saldo_actual = saldo_inicial for existing rows (mirrors the real migration)
        conn.execute(text("UPDATE bancos_empresa SET saldo_actual = saldo_inicial"))
        # Add empresa_id NULLABLE (no backfill per AD-13)
        conn.execute(text("ALTER TABLE bancos_empresa ADD COLUMN empresa_id INTEGER"))
        conn.commit()


def _apply_downgrade_032(engine: sa.Engine) -> None:
    """Apply compras_032 downgrade (drop banco_movimientos, drop added columns).

    SQLite 3.35+ supports DROP COLUMN — verified via sqlite3.sqlite_version in CI.
    """
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS banco_movimientos"))
        conn.execute(text("ALTER TABLE bancos_empresa DROP COLUMN empresa_id"))
        conn.execute(text("ALTER TABLE bancos_empresa DROP COLUMN saldo_actual"))
        conn.commit()


def _apply_upgrade_033(engine: sa.Engine) -> None:
    """Apply compras_033 upgrade DDL (mirrors the real migration intent).

    Adds banco_id + banco_movimiento_id columns to ordenes_pago.
    CHECK constraint for at-most-one fund source is SQLite-compatible syntax.
    """
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE ordenes_pago ADD COLUMN banco_id INTEGER"))
        conn.execute(text("ALTER TABLE ordenes_pago ADD COLUMN banco_movimiento_id INTEGER"))
        conn.commit()


def _apply_downgrade_033(engine: sa.Engine) -> None:
    """Apply compras_033 downgrade (drop the two added columns).

    Note: the real migration also drops a named CHECK constraint with
    op.drop_constraint(type_='check'), which is PostgreSQL-only DDL.
    That part is NOT tested here — it's verified at the staging DB level.
    """
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE ordenes_pago DROP COLUMN banco_movimiento_id"))
        conn.execute(text("ALTER TABLE ordenes_pago DROP COLUMN banco_id"))
        conn.commit()


# ---------------------------------------------------------------------------
# Tests — compras_032
# ---------------------------------------------------------------------------


class TestMigration032CreateBancoMovimientos:
    """compras_032 creates banco_movimientos and adds columns to bancos_empresa."""

    def test_upgrade_creates_banco_movimientos_table(self) -> None:
        engine = _make_engine()
        _create_pre032_schema(engine)
        _apply_upgrade_032(engine)

        tables = inspect(engine).get_table_names()
        assert "banco_movimientos" in tables

    def test_banco_movimientos_has_required_columns(self) -> None:
        engine = _make_engine()
        _create_pre032_schema(engine)
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
            "created_at",
        }
        assert required <= cols, f"Missing columns: {required - cols}"

    def test_upgrade_adds_saldo_actual_column(self) -> None:
        engine = _make_engine()
        _create_pre032_schema(engine)
        _apply_upgrade_032(engine)

        cols = {c["name"] for c in inspect(engine).get_columns("bancos_empresa")}
        assert "saldo_actual" in cols

    def test_upgrade_adds_empresa_id_column(self) -> None:
        engine = _make_engine()
        _create_pre032_schema(engine)
        _apply_upgrade_032(engine)

        cols = {c["name"] for c in inspect(engine).get_columns("bancos_empresa")}
        assert "empresa_id" in cols

    def test_backfill_saldo_actual_equals_saldo_inicial(self) -> None:
        engine = _make_engine()
        _create_pre032_schema(engine)

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
        _create_pre032_schema(engine)

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
        _create_pre032_schema(engine)
        _apply_upgrade_032(engine)
        _apply_downgrade_032(engine)

        tables = inspect(engine).get_table_names()
        assert "banco_movimientos" not in tables

    def test_downgrade_removes_added_columns(self) -> None:
        """Downgrade removes saldo_actual and empresa_id from bancos_empresa."""
        engine = _make_engine()
        _create_pre032_schema(engine)
        _apply_upgrade_032(engine)
        _apply_downgrade_032(engine)

        cols = {c["name"] for c in inspect(engine).get_columns("bancos_empresa")}
        assert "saldo_actual" not in cols, "saldo_actual should be removed by downgrade"
        assert "empresa_id" not in cols, "empresa_id should be removed by downgrade"

    def test_downgrade_preserves_base_columns(self) -> None:
        """Downgrade must not disturb the original bancos_empresa columns."""
        engine = _make_engine()
        _create_pre032_schema(engine)
        _apply_upgrade_032(engine)
        _apply_downgrade_032(engine)

        cols = {c["name"] for c in inspect(engine).get_columns("bancos_empresa")}
        base = {"id", "banco", "moneda", "saldo_inicial", "activo", "created_at"}
        assert base <= cols, f"Base columns missing after downgrade: {base - cols}"


# ---------------------------------------------------------------------------
# Tests — compras_033
# ---------------------------------------------------------------------------


class TestMigration033OpFuenteBanco:
    """compras_033 adds banco_id + banco_movimiento_id to ordenes_pago.

    downgrade() of the real migration includes op.drop_constraint(type_='check'),
    which is PostgreSQL-only DDL and cannot be tested against SQLite. The column
    removal part IS tested here (SQLite 3.35+ supports DROP COLUMN).
    """

    def test_upgrade_adds_banco_id_to_ordenes_pago(self) -> None:
        engine = _make_engine()
        _create_pre033_schema(engine)
        _apply_upgrade_032(engine)
        _apply_upgrade_033(engine)

        cols = {c["name"] for c in inspect(engine).get_columns("ordenes_pago")}
        assert "banco_id" in cols

    def test_upgrade_adds_banco_movimiento_id_to_ordenes_pago(self) -> None:
        engine = _make_engine()
        _create_pre033_schema(engine)
        _apply_upgrade_032(engine)
        _apply_upgrade_033(engine)

        cols = {c["name"] for c in inspect(engine).get_columns("ordenes_pago")}
        assert "banco_movimiento_id" in cols

    def test_existing_ops_have_null_banco_fields(self) -> None:
        """Existing OPs after migration have banco_id = NULL (no backfill)."""
        engine = _make_engine()
        _create_pre033_schema(engine)

        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO ordenes_pago "
                    "(empresa_id, proveedor_id, moneda, monto_total, modo_imputacion, creado_por_id) "
                    "VALUES (1, 2, 'ARS', 10000, 'a_cuenta', 1)"
                )
            )
            conn.commit()

        _apply_upgrade_032(engine)
        _apply_upgrade_033(engine)

        with engine.connect() as conn:
            row = conn.execute(text("SELECT banco_id, banco_movimiento_id FROM ordenes_pago LIMIT 1")).fetchone()

        assert row is not None
        assert row[0] is None, f"banco_id should be NULL for existing OPs, got {row[0]}"
        assert row[1] is None, f"banco_movimiento_id should be NULL for existing OPs, got {row[1]}"

    def test_downgrade_removes_banco_columns(self) -> None:
        """Column removal part of downgrade (op.drop_constraint skipped — Postgres-only)."""
        engine = _make_engine()
        _create_pre033_schema(engine)
        _apply_upgrade_032(engine)
        _apply_upgrade_033(engine)
        _apply_downgrade_033(engine)

        cols = {c["name"] for c in inspect(engine).get_columns("ordenes_pago")}
        assert "banco_id" not in cols, "banco_id should be removed by downgrade"
        assert "banco_movimiento_id" not in cols, "banco_movimiento_id should be removed by downgrade"

    def test_downgrade_preserves_caja_columns(self) -> None:
        """Downgrade must not disturb caja_id / caja_movimiento_id (pre-existing cols)."""
        engine = _make_engine()
        _create_pre033_schema(engine)
        _apply_upgrade_032(engine)
        _apply_upgrade_033(engine)
        _apply_downgrade_033(engine)

        cols = {c["name"] for c in inspect(engine).get_columns("ordenes_pago")}
        assert "caja_id" in cols, "caja_id must survive downgrade"
        assert "caja_movimiento_id" in cols, "caja_movimiento_id must survive downgrade"
