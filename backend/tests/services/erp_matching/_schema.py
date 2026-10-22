"""Throwaway PostgreSQL schema for the invoiced-lines snapshot tests.

The reconcile SQL reads only a handful of relations, so each test gets its own
schema with minimal tables (the view is a plain table here), like
`tests/services/test_lineas_facturadas_postgres.py`.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator, Optional

import pytest
from sqlalchemy import Engine, create_engine, text

ERP_DDL = """
CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY, ct_transaction_id BIGINT, corregido_desde_id BIGINT);
CREATE TABLE notas_credito_local (id BIGINT PRIMARY KEY, ct_transaction_id BIGINT);
CREATE TABLE imputaciones (
  id BIGINT PRIMARY KEY, origen_tipo TEXT, origen_id BIGINT, destino_tipo TEXT, destino_id BIGINT,
  es_reversal BOOLEAN NOT NULL DEFAULT false, reimputada_desde_id BIGINT
);
CREATE TABLE v_facturas_compra_vigentes (
  ct_transaction BIGINT PRIMARY KEY, sd_plusorminus INTEGER, clasificacion TEXT, curr_id_transaction INTEGER
);
CREATE TABLE tb_item_transactions (
  it_transaction BIGINT PRIMARY KEY, ct_transaction BIGINT, item_id INTEGER, it_qty NUMERIC(18, 4),
  it_price NUMERIC(18, 4), curr_id INTEGER,
  it_isassociation BOOLEAN, it_order INTEGER, it_isassociationgroup BOOLEAN
);
"""

# The snapshot table as 20261104_pedido_lineas_facturadas created it (before importe_neto/moneda).
LINEAS_DDL_V1 = """
CREATE TABLE pedido_compra_lineas_facturadas (
  id BIGSERIAL PRIMARY KEY,
  pedido_id BIGINT NOT NULL REFERENCES pedidos_compra (id) ON DELETE CASCADE,
  item_id INTEGER NOT NULL,
  cantidad INTEGER NOT NULL,
  CONSTRAINT uq_pedido_compra_lineas_facturadas_pedido_item UNIQUE (pedido_id, item_id),
  CONSTRAINT ck_pedido_compra_lineas_facturadas_cantidad_positiva CHECK (cantidad > 0)
);
"""

ADD_IMPORTE_DDL = """
ALTER TABLE pedido_compra_lineas_facturadas
  ADD COLUMN importe_neto NUMERIC(18, 2),
  ADD COLUMN moneda VARCHAR(3),
  ADD CONSTRAINT ck_pedido_compra_lineas_facturadas_importe_no_negativo
    CHECK (importe_neto IS NULL OR importe_neto >= 0),
  ADD CONSTRAINT ck_pedido_compra_lineas_facturadas_moneda CHECK (moneda IN ('ARS', 'USD'));
"""

# The sell-in bonus queue on the snapshot, verbatim from 20261107_sell_in_bonos_marca
# (tables trimmed to the columns the trigger functions read). Only the line
# triggers: they are what a reconcile can fire.
BONO_DDL = """
ALTER TABLE pedidos_compra ADD COLUMN fecha_factura DATE;
CREATE TABLE sell_in_bonos_marca (
  id BIGINT PRIMARY KEY, marca VARCHAR(100) NOT NULL, fecha_desde DATE NOT NULL, fecha_hasta DATE NOT NULL,
  estado VARCHAR(16) NOT NULL DEFAULT 'activa'
);
CREATE TABLE sell_in_bono_dirty (
  tipo VARCHAR(8) NOT NULL, ref BIGINT NOT NULL, enqueued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
  CONSTRAINT ck_sell_in_bono_dirty_tipo CHECK (tipo IN ('bono', 'pedido')),
  PRIMARY KEY (tipo, ref)
);
"""
BONO_FUNCIONES = [
    """
CREATE OR REPLACE FUNCTION sell_in_bono_cubre(p_fecha DATE, p_marca TEXT DEFAULT NULL) RETURNS BOOLEAN AS $fn$
    SELECT p_fecha IS NOT NULL AND EXISTS (
        SELECT 1 FROM sell_in_bonos_marca AS b
        WHERE b.estado = 'activa' AND p_fecha BETWEEN b.fecha_desde AND b.fecha_hasta
          AND (p_marca IS NULL OR b.marca = p_marca)
    )
$fn$ LANGUAGE sql STABLE
""",
    """
CREATE OR REPLACE FUNCTION sell_in_bono_enqueue_linea() RETURNS TRIGGER AS $trg$
DECLARE
    pedidos BIGINT[];
BEGIN
    IF TG_OP = 'INSERT' THEN
        pedidos := ARRAY[NEW.pedido_id];
    ELSIF TG_OP = 'DELETE' THEN
        pedidos := ARRAY[OLD.pedido_id];
    ELSE
        pedidos := ARRAY[OLD.pedido_id, NEW.pedido_id];
    END IF;
    INSERT INTO sell_in_bono_dirty (tipo, ref)
    SELECT DISTINCT 'pedido', p.id FROM pedidos_compra AS p
    WHERE p.id = ANY(pedidos) AND sell_in_bono_cubre(p.fecha_factura)
    ORDER BY 2
    ON CONFLICT (tipo, ref) DO UPDATE SET enqueued_at = now(), attempts = 0, last_error = NULL;
    IF FOUND THEN
        PERFORM pg_notify('sell_in_bono_dirty', '');
    END IF;
    RETURN NULL;
END;
$trg$ LANGUAGE plpgsql
""",
    """
CREATE TRIGGER trg_sell_in_bono_lineas_insert_delete
AFTER INSERT OR DELETE ON pedido_compra_lineas_facturadas
FOR EACH ROW EXECUTE FUNCTION sell_in_bono_enqueue_linea()
""",
    """
CREATE TRIGGER trg_sell_in_bono_lineas_update
AFTER UPDATE OF pedido_id, item_id, cantidad ON pedido_compra_lineas_facturadas
FOR EACH ROW WHEN ((OLD.pedido_id, OLD.item_id, OLD.cantidad) IS DISTINCT FROM (NEW.pedido_id, NEW.item_id, NEW.cantidad))
EXECUTE FUNCTION sell_in_bono_enqueue_linea()
""",
]

ARS, USD = 1, 2


@contextmanager
def lf_schema(*, con_importe: bool = True, con_bono: bool = False) -> Iterator[Engine]:
    """Engine bound (search_path) to a fresh schema; dropped on exit.

    `con_bono` also installs the sell-in bonus queue and its line triggers.
    """
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable  # noqa: PLC0415

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"lfi_{uuid.uuid4().hex[:12]}"
    admin = create_engine(POSTGRES_TEST_URL)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with eng.begin() as conn:
            conn.execute(text(ERP_DDL + LINEAS_DDL_V1 + (ADD_IMPORTE_DDL if con_importe else "")))
            if con_bono:
                conn.execute(text(BONO_DDL))
                for statement in BONO_FUNCIONES:
                    conn.exec_driver_sql(statement)
        yield eng
    finally:
        eng.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def documento(conn, ct: int, *, signo: int = 1, clasificacion: str = "FACTURA", curr: int = ARS) -> None:
    conn.execute(
        text("INSERT INTO v_facturas_compra_vigentes VALUES (:ct, :s, :c, :cur)"),
        {"ct": ct, "s": signo, "c": clasificacion, "cur": curr},
    )


def linea(conn, it: int, ct: int, item: int, qty: str, price: Optional[str], curr: Optional[int]) -> None:
    conn.execute(
        text(
            "INSERT INTO tb_item_transactions (it_transaction, ct_transaction, item_id, it_qty, it_price, curr_id) "
            "VALUES (:it, :ct, :i, :q, :p, :cur)"
        ),
        {"it": it, "ct": ct, "i": item, "q": qty, "p": price, "cur": curr},
    )


def pedido_con_factura(conn, *, pedido_id: int = 1, ct: int = 100, curr: int = ARS) -> None:
    conn.execute(
        text("INSERT INTO pedidos_compra (id, ct_transaction_id) VALUES (:p, :ct)"), {"p": pedido_id, "ct": ct}
    )
    documento(conn, ct, curr=curr)


def nota_credito(conn, *, ct: int = 200, pedido_id: int = 1, imputacion_id: int = 1, curr: int = ARS) -> None:
    documento(conn, ct, signo=-1, clasificacion="NC", curr=curr)
    conn.execute(
        text(
            "INSERT INTO imputaciones (id, origen_tipo, origen_id, destino_tipo, destino_id) "
            "VALUES (:id, 'nota_credito_erp', :ct, 'pedido_compra', :p)"
        ),
        {"id": imputacion_id, "ct": ct, "p": pedido_id},
    )


def filas(eng: Engine) -> list[tuple]:
    """(pedido_id, item_id, cantidad, importe_neto as str or None, moneda)."""
    with eng.connect() as conn:
        return [
            (r[0], r[1], r[2], None if r[3] is None else str(r[3]), r[4])
            for r in conn.execute(
                text(
                    "SELECT pedido_id, item_id, cantidad, importe_neto, moneda "
                    "FROM pedido_compra_lineas_facturadas ORDER BY pedido_id, item_id"
                )
            )
        ]
