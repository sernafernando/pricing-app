"""
T5.1 — Migration test for F5: compras_031 (pedidos_compra.tipo_cambio_manual).

Verifies the DDL intent against an in-memory SQLite engine:
- Column tipo_cambio_manual Numeric(18,6) nullable is added by upgrade.
- No backfill needed (NULL = no override in effect).
- Downgrade drops the column.

Pattern mirrors test_migration_f2.py — no Alembic internals imported.
"""

from __future__ import annotations

import pytest
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
    """Create a minimal pedidos_compra table (pre-F5 state, already has tipo_cambio_original)."""
    with engine.connect() as conn:
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
                tipo_cambio_original NUMERIC(18,6),
                estado TEXT NOT NULL DEFAULT 'borrador',
                creado_por_id INTEGER NOT NULL
            )
        """)
        )
        conn.commit()


def _apply_upgrade(engine: sa.Engine) -> None:
    """Apply the compras_031 upgrade DDL (mirrors the Alembic migration)."""
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE pedidos_compra ADD COLUMN tipo_cambio_manual NUMERIC(18,6)"))
        conn.commit()


def _apply_downgrade(engine: sa.Engine) -> None:
    """SQLite does not support DROP COLUMN on old versions; we recreate the table."""
    with engine.connect() as conn:
        conn.execute(
            text("""
            CREATE TABLE pedidos_compra_backup AS
            SELECT id, numero, empresa_id, proveedor_id, moneda, monto,
                   tipo_cambio, tipo_cambio_original, estado, creado_por_id
            FROM pedidos_compra
        """)
        )
        conn.execute(text("DROP TABLE pedidos_compra"))
        conn.execute(text("ALTER TABLE pedidos_compra_backup RENAME TO pedidos_compra"))
        conn.commit()


# ---------------------------------------------------------------------------
# T5.1 — test_migration_031_add_tipo_cambio_manual
# ---------------------------------------------------------------------------


class TestMigration031:
    """Migration compras_031 adds pedidos_compra.tipo_cambio_manual (Numeric 18,6 nullable)."""

    def test_upgrade_adds_tipo_cambio_manual_column(self) -> None:
        """Column 'tipo_cambio_manual' is present after upgrade."""
        engine = _make_sqlite_engine()
        _create_base_schema(engine)
        _apply_upgrade(engine)

        inspector = inspect(engine)
        cols = {c["name"] for c in inspector.get_columns("pedidos_compra")}
        assert "tipo_cambio_manual" in cols

    def test_column_is_nullable(self) -> None:
        """tipo_cambio_manual allows NULL (no backfill)."""
        engine = _make_sqlite_engine()
        _create_base_schema(engine)
        _apply_upgrade(engine)

        # Insert a row without providing tipo_cambio_manual (should default to NULL).
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO pedidos_compra (numero, empresa_id, proveedor_id, moneda, monto, "
                    "estado, creado_por_id) VALUES ('PC-001', 1, 1, 'USD', 1000.00, 'aprobado', 1)"
                )
            )
            conn.commit()
            row = conn.execute(text("SELECT tipo_cambio_manual FROM pedidos_compra WHERE numero='PC-001'")).fetchone()
            assert row is not None
            assert row[0] is None  # NULL — no override

    def test_column_stores_decimal_value(self) -> None:
        """tipo_cambio_manual stores a numeric override when set."""
        engine = _make_sqlite_engine()
        _create_base_schema(engine)
        _apply_upgrade(engine)

        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO pedidos_compra (numero, empresa_id, proveedor_id, moneda, monto, "
                    "tipo_cambio_manual, estado, creado_por_id) "
                    "VALUES ('PC-002', 1, 1, 'USD', 1000.00, 1430.500000, 'aprobado', 1)"
                )
            )
            conn.commit()
            row = conn.execute(text("SELECT tipo_cambio_manual FROM pedidos_compra WHERE numero='PC-002'")).fetchone()
            assert row is not None
            assert float(row[0]) == pytest.approx(1430.5)

    def test_downgrade_drops_column(self) -> None:
        """After downgrade, tipo_cambio_manual column is gone."""
        engine = _make_sqlite_engine()
        _create_base_schema(engine)
        _apply_upgrade(engine)
        _apply_downgrade(engine)

        inspector = inspect(engine)
        cols = {c["name"] for c in inspector.get_columns("pedidos_compra")}
        assert "tipo_cambio_manual" not in cols

    def test_existing_rows_remain_null_after_upgrade(self) -> None:
        """Rows inserted before migration have NULL tipo_cambio_manual after upgrade (no backfill)."""
        engine = _make_sqlite_engine()
        _create_base_schema(engine)

        # Insert a row BEFORE migration.
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO pedidos_compra (numero, empresa_id, proveedor_id, moneda, monto, "
                    "estado, creado_por_id) VALUES ('PC-PRE', 1, 1, 'USD', 500.00, 'aprobado', 1)"
                )
            )
            conn.commit()

        _apply_upgrade(engine)

        with engine.connect() as conn:
            row = conn.execute(text("SELECT tipo_cambio_manual FROM pedidos_compra WHERE numero='PC-PRE'")).fetchone()
            assert row is not None
            assert row[0] is None
