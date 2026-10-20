"""Free-text search of the sell-in list (`q`) on Postgres, the real target.

SQLite's `lower()` only folds ASCII, so the non-ASCII case folding can only be
proven here. Runs in a throwaway schema with the sell-in tables built from the
ORM and bare stand-ins of the tables they reference.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.database import Base
from app.services.sell_in import compras

pytestmark = pytest.mark.postgres

_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE TABLE proveedores (id INTEGER PRIMARY KEY, nombre VARCHAR(255) NOT NULL)",
    "CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY, numero VARCHAR(32) NOT NULL)",
    "CREATE TABLE productos_erp (item_id INTEGER PRIMARY KEY, codigo VARCHAR(100), descripcion VARCHAR(500),"
    " marca VARCHAR(100))",
]
_SELL_IN_TABLES = (
    "sell_in_bonos_marca",
    "sell_in_compras",
    "sell_in_compra_items",
    "sell_in_compra_pedidos",
    "sell_in_consumos",
)

# (supplier name, product description, purchase reference)
_COMPRAS = {
    "nandu": ("ÑANDÚ S.A.", "Switch", "Rebate"),
    "istanbul": ("İSTANBUL TRADING", "Router", "Bonificación"),
    "otra": ("TP-Link", "CÁMARA DOMO", "Acuerdo ÚNICO"),
}


@contextmanager
def _schema():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable, _restore_pristine_pg_types

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"sell_in_q_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    tables = [Base.metadata.tables[name] for name in _SELL_IN_TABLES]
    found = {column: column.type for table in tables for column in table.columns}
    try:
        with eng.begin() as conn:
            for statement in _STUBS:
                conn.execute(text(statement))
        _restore_pristine_pg_types(tables)
        try:
            Base.metadata.create_all(bind=eng, tables=tables)
        finally:
            for column, column_type in found.items():
                column.type = column_type
        yield eng
    finally:
        eng.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


@pytest.fixture(scope="module")
def pg():
    with _schema() as eng:
        ids = {}
        with eng.begin() as conn:
            conn.execute(text("INSERT INTO usuarios VALUES (7)"))
            for n, (key, (proveedor, producto, referencia)) in enumerate(_COMPRAS.items(), start=1):
                conn.execute(text("INSERT INTO proveedores VALUES (:n, :nombre)"), {"n": n, "nombre": proveedor})
                conn.execute(
                    text("INSERT INTO productos_erp VALUES (:n, :codigo, :descripcion, 'X')"),
                    {"n": n, "codigo": f"C-{n}", "descripcion": producto},
                )
                ids[key] = conn.execute(
                    text(
                        "INSERT INTO sell_in_compras (proveedor_id, fecha_compra, moneda, monto_total, descripcion,"
                        " usuario_id) VALUES (:n, DATE '2026-10-01', 'ARS', 100, :ref, 7) RETURNING id"
                    ),
                    {"n": n, "ref": referencia},
                ).scalar_one()
                conn.execute(
                    text(
                        "INSERT INTO sell_in_compra_items (compra_id, item_id, cantidad, costo_base_unit,"
                        " monto_asignado) VALUES (:compra, :n, 1, 100, 100)"
                    ),
                    {"compra": ids[key], "n": n},
                )
        yield eng, ids


@pytest.mark.parametrize(
    "q,expected",
    [
        ("ñandú", {"nandu"}),  # non-ASCII uppercase supplier name, lowercase query
        ("ÑANDÚ", {"nandu"}),
        ("Ñandú s.a.", {"nandu"}),
        ("İstanbul", {"istanbul"}),  # folded by the database on both sides, not by Python on one
        ("cámara domo", {"otra"}),  # product description
        ("único", {"otra"}),  # purchase reference
        ("100%", set()),  # LIKE wildcards stay literal
    ],
)
def test_free_text_folds_case_in_the_database(pg, q, expected):
    eng, ids = pg
    with Session(bind=eng) as db:
        compras_, _ = compras.listar_compras(db, compras.FiltrosCompras(q=q))
    assert {c.id for c in compras_} == {ids[k] for k in expected}


def test_free_text_is_not_accent_insensitive_yet(pg):
    """`unaccent` is not installed in production (it needs a migration), so "nandu" does not find "Ñandú"."""
    eng, _ = pg
    with Session(bind=eng) as db:
        compras_, _ = compras.listar_compras(db, compras.FiltrosCompras(q="nandu"))
    assert compras_ == []
