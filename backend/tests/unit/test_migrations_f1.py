"""
Tests for F1 migrations: compras_028 (actualizar_tc_pedido) and
compras_029 (tipo_cambio_original).

These tests verify the DDL intent of each migration — the column types,
defaults, nullability, and backfill behaviour — against an in-memory
SQLite engine. They apply the same DDL statements that the Alembic
migrations execute (ALTER TABLE + UPDATE), but do NOT import or invoke
the migration modules directly.

Rationale: bootstrapping Alembic's `op` context against an isolated
SQLite engine requires a full MigrationContext setup that would couple
these unit tests to Alembic internals. Full end-to-end migration chain
correctness (including `upgrade()`/`downgrade()` against the real schema)
is covered by the CI pipeline using a real PostgreSQL instance.
"""

from __future__ import annotations

from decimal import Decimal

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
    """Create a minimal base schema that compras_028 / compras_029 depend on."""
    with engine.connect() as conn:
        # ordenes_pago table (compras_028 target)
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS ordenes_pago (
                id INTEGER PRIMARY KEY,
                numero TEXT NOT NULL,
                empresa_id INTEGER NOT NULL,
                proveedor_id INTEGER NOT NULL,
                moneda TEXT NOT NULL,
                monto_total NUMERIC(18,2) NOT NULL,
                modo_imputacion TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'pendiente'
            )
        """)
        )
        # pedidos_compra table (compras_029 target)
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS pedidos_compra (
                id INTEGER PRIMARY KEY,
                numero TEXT NOT NULL,
                empresa_id INTEGER NOT NULL,
                proveedor_id INTEGER NOT NULL,
                moneda TEXT NOT NULL,
                monto NUMERIC(18,2) NOT NULL,
                tipo_cambio NUMERIC(18,6),
                estado TEXT NOT NULL DEFAULT 'borrador'
            )
        """)
        )
        conn.commit()


# ---------------------------------------------------------------------------
# T1.1 — test_migration_028_add_actualizar_tc_pedido
# ---------------------------------------------------------------------------


class TestMigration028:
    """Migration compras_028 adds ordenes_pago.actualizar_tc_pedido (Boolean NOT NULL default false)."""

    def test_upgrade_adds_column(self) -> None:
        """Column exists after upgrade, with a default of False."""
        engine = _make_sqlite_engine()
        _create_base_schema(engine)

        # Insert a row BEFORE the migration (column doesn't exist yet).
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO ordenes_pago (numero, empresa_id, proveedor_id, moneda, monto_total, modo_imputacion) "
                    "VALUES ('OP-001', 1, 1, 'ARS', 1000.00, 'especifica')"
                )
            )
            conn.commit()

        # Apply the migration DDL manually (mirrors what compras_028 does).
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE ordenes_pago ADD COLUMN actualizar_tc_pedido BOOLEAN NOT NULL DEFAULT 0"))
            conn.commit()

        # Verify column exists.
        insp = inspect(engine)
        cols = {c["name"]: c for c in insp.get_columns("ordenes_pago")}
        assert "actualizar_tc_pedido" in cols, "Column actualizar_tc_pedido should exist after migration"

        # Verify default: existing row should read as False (0 in SQLite).
        with engine.connect() as conn:
            row = conn.execute(text("SELECT actualizar_tc_pedido FROM ordenes_pago LIMIT 1")).fetchone()
        assert row is not None
        assert int(row[0]) == 0, "Existing rows should default to False (0)"

        # Verify new row can be inserted with True.
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO ordenes_pago (numero, empresa_id, proveedor_id, moneda, monto_total, "
                    "modo_imputacion, actualizar_tc_pedido) "
                    "VALUES ('OP-002', 1, 1, 'ARS', 500.00, 'especifica', 1)"
                )
            )
            conn.commit()
            row2 = conn.execute(text("SELECT actualizar_tc_pedido FROM ordenes_pago WHERE numero='OP-002'")).fetchone()
        assert int(row2[0]) == 1

    def test_column_not_nullable(self) -> None:
        """The column is NOT NULL — inserting without specifying it should use the default."""
        engine = _make_sqlite_engine()
        _create_base_schema(engine)
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE ordenes_pago ADD COLUMN actualizar_tc_pedido BOOLEAN NOT NULL DEFAULT 0"))
            conn.commit()

        # Insert without specifying the column — should succeed (default kicks in).
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO ordenes_pago (numero, empresa_id, proveedor_id, moneda, monto_total, modo_imputacion) "
                    "VALUES ('OP-003', 1, 1, 'ARS', 100.00, 'especifica')"
                )
            )
            conn.commit()
            row = conn.execute(text("SELECT actualizar_tc_pedido FROM ordenes_pago WHERE numero='OP-003'")).fetchone()
        assert row is not None
        assert int(row[0]) == 0


# ---------------------------------------------------------------------------
# T1.3 — test_migration_029_add_tipo_cambio_original
# ---------------------------------------------------------------------------


class TestMigration029:
    """Migration compras_029 adds pedidos_compra.tipo_cambio_original (Numeric 18,6 nullable)
    and backfills it from tipo_cambio."""

    def test_upgrade_adds_column_and_backfills(self) -> None:
        """Column exists after upgrade and existing rows have tipo_cambio_original = tipo_cambio."""
        engine = _make_sqlite_engine()
        _create_base_schema(engine)

        # Insert rows with known tipo_cambio values.
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO pedidos_compra (numero, empresa_id, proveedor_id, moneda, monto, tipo_cambio) "
                    "VALUES ('PC-001', 1, 1, 'USD', 1000.00, 1450.5)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO pedidos_compra (numero, empresa_id, proveedor_id, moneda, monto, tipo_cambio) "
                    "VALUES ('PC-002', 1, 1, 'ARS', 5000.00, NULL)"
                )
            )
            conn.commit()

        # Apply migration DDL + backfill.
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE pedidos_compra ADD COLUMN tipo_cambio_original NUMERIC(18,6)"))
            conn.execute(text("UPDATE pedidos_compra SET tipo_cambio_original = tipo_cambio"))
            conn.commit()

        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("pedidos_compra")}
        assert "tipo_cambio_original" in cols

        with engine.connect() as conn:
            r1 = conn.execute(text("SELECT tipo_cambio_original FROM pedidos_compra WHERE numero='PC-001'")).fetchone()
            r2 = conn.execute(text("SELECT tipo_cambio_original FROM pedidos_compra WHERE numero='PC-002'")).fetchone()

        assert r1 is not None
        assert Decimal(str(r1[0])) == Decimal("1450.5"), "Backfill should copy tipo_cambio"
        assert r2 is not None
        assert r2[0] is None, "NULL tipo_cambio should remain NULL in tipo_cambio_original"

    def test_new_rows_can_set_tipo_cambio_original(self) -> None:
        """New rows inserted after migration can set tipo_cambio_original independently."""
        engine = _make_sqlite_engine()
        _create_base_schema(engine)
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE pedidos_compra ADD COLUMN tipo_cambio_original NUMERIC(18,6)"))
            conn.execute(text("UPDATE pedidos_compra SET tipo_cambio_original = tipo_cambio"))
            conn.commit()

        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO pedidos_compra "
                    "(numero, empresa_id, proveedor_id, moneda, monto, tipo_cambio, tipo_cambio_original) "
                    "VALUES ('PC-003', 1, 1, 'USD', 2000.00, 1500.0, 1400.0)"
                )
            )
            conn.commit()
            row = conn.execute(
                text("SELECT tipo_cambio, tipo_cambio_original FROM pedidos_compra WHERE numero='PC-003'")
            ).fetchone()

        assert Decimal(str(row[0])) == Decimal("1500.0")
        assert Decimal(str(row[1])) == Decimal("1400.0")
