"""
Integration-specific conftest: creates ERP stub tables in the SQLite test DB
so that raw-SQL endpoints (like consultas/ranking) can execute without
needing a real PostgreSQL ERP instance.

These tables mirror only the columns used by the ranking query.
They are created ONCE per test session by extending the shared `engine` fixture.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text


@pytest.fixture(scope="session", autouse=True)
def erp_stub_tables(engine) -> None:
    """Create minimal ERP table stubs in the test SQLite DB.

    Only the columns referenced by the ranking endpoint are created.
    SQLite does not support LATERAL JOIN or JSONB — those SQL fragments are
    handled by patching db.execute in tests. This fixture just ensures the
    tables exist so that schema-level errors don't occur during app startup
    model imports.
    """
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS tb_commercial_transactions (
                    ct_transaction INTEGER PRIMARY KEY,
                    ct_date        DATETIME,
                    sd_id          INTEGER,
                    df_id          INTEGER,
                    puco_id        INTEGER
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS tb_item_transactions (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    ct_transaction INTEGER,
                    item_id        INTEGER,
                    it_cd          DATETIME,
                    it_qty         INTEGER
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS tb_item_storage (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id   INTEGER,
                    stor_id   INTEGER,
                    itst_cant INTEGER
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS tb_price_list_items (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id    INTEGER,
                    prli_id    INTEGER,
                    prli_price REAL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS marcas_pm (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    marca      TEXT,
                    categoria  TEXT,
                    usuario_id INTEGER
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS stock_por_deposito (
                    item_id    INTEGER NOT NULL,
                    stor_id    INTEGER NOT NULL,
                    stock      INTEGER NOT NULL DEFAULT 0,
                    updated_at DATETIME,
                    PRIMARY KEY (item_id, stor_id)
                )
                """
            )
        )
        conn.commit()
