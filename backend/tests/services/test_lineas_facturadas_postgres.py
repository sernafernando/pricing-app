"""PostgreSQL behaviour of the `pedido_compra_lineas_facturadas` snapshot.

Two things SQLite cannot prove:

* Concurrency: under READ COMMITTED two reconciles of the same pedido can both
  decide an item is missing; the second INSERT must upsert, not raise
  UniqueViolation (a user's link request runs `asignar_factura_erp`, which does
  not swallow it).
* Rounding: `CAST(numeric AS INTEGER)` rounds on PostgreSQL but truncates on
  SQLite, so a fractional net must be floored explicitly to behave the same.

The reconcile SQL only reads a handful of relations, so each test gets a
throwaway schema with minimal tables (the view is a plain table here) instead
of the full metadata.
"""

from __future__ import annotations

import importlib.util
import threading
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.erp_matching_service import reconciliar_lineas_facturadas

pytestmark = pytest.mark.postgres

_DDL = """
CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY, ct_transaction_id BIGINT, corregido_desde_id BIGINT);
CREATE TABLE notas_credito_local (id BIGINT PRIMARY KEY, ct_transaction_id BIGINT);
CREATE TABLE imputaciones (
  id BIGINT PRIMARY KEY, origen_tipo TEXT, origen_id BIGINT, destino_tipo TEXT, destino_id BIGINT,
  es_reversal BOOLEAN NOT NULL DEFAULT false, reimputada_desde_id BIGINT
);
CREATE TABLE v_facturas_compra_vigentes (ct_transaction BIGINT PRIMARY KEY, sd_plusorminus INTEGER, clasificacion TEXT);
CREATE TABLE tb_item_transactions (
  it_transaction BIGINT PRIMARY KEY, ct_transaction BIGINT, item_id INTEGER, it_qty NUMERIC(18, 4),
  it_isassociation BOOLEAN, it_order INTEGER, it_isassociationgroup BOOLEAN
);
CREATE TABLE pedido_compra_lineas_facturadas (
  id BIGSERIAL PRIMARY KEY,
  pedido_id BIGINT NOT NULL REFERENCES pedidos_compra (id) ON DELETE CASCADE,
  item_id INTEGER NOT NULL,
  cantidad INTEGER NOT NULL,
  CONSTRAINT uq_pedido_compra_lineas_facturadas_pedido_item UNIQUE (pedido_id, item_id),
  CONSTRAINT ck_pedido_compra_lineas_facturadas_cantidad_positiva CHECK (cantidad > 0)
);
"""


@pytest.fixture
def pg_lf_engine():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable  # noqa: PLC0415

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"lf_{uuid.uuid4().hex[:12]}"
    admin = create_engine(POSTGRES_TEST_URL)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with eng.begin() as conn:
            conn.execute(text(_DDL))
        yield eng
    finally:
        eng.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def _seed(conn, *, lineas: list[tuple[int, int, str]], nc_lineas: list[tuple[int, int, str]] = ()) -> None:
    """Pedido 1 linked to invoice 100; optional credit note 200 imputed to it."""
    conn.execute(text("INSERT INTO pedidos_compra (id, ct_transaction_id) VALUES (1, 100)"))
    conn.execute(text("INSERT INTO v_facturas_compra_vigentes VALUES (100, 1, 'FACTURA')"))
    for it, item, qty in lineas:
        conn.execute(
            text(
                "INSERT INTO tb_item_transactions (it_transaction, ct_transaction, item_id, it_qty) VALUES (:it, 100, :i, :q)"
            ),
            {"it": it, "i": item, "q": qty},
        )
    if nc_lineas:
        conn.execute(text("INSERT INTO v_facturas_compra_vigentes VALUES (200, -1, 'NC')"))
        conn.execute(
            text(
                "INSERT INTO imputaciones (id, origen_tipo, origen_id, destino_tipo, destino_id) "
                "VALUES (1, 'nota_credito_erp', 200, 'pedido_compra', 1)"
            )
        )
        for it, item, qty in nc_lineas:
            conn.execute(
                text(
                    "INSERT INTO tb_item_transactions (it_transaction, ct_transaction, item_id, it_qty) "
                    "VALUES (:it, 200, :i, :q)"
                ),
                {"it": it, "i": item, "q": qty},
            )


def _lineas(eng) -> list[tuple[int, int]]:
    with eng.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                text("SELECT item_id, cantidad FROM pedido_compra_lineas_facturadas ORDER BY item_id")
            )
        ]


def test_concurrent_reconcile_upserts_the_row_the_other_transaction_inserted(pg_lf_engine):
    with pg_lf_engine.begin() as conn:
        _seed(conn, lineas=[(1, 501, "5")])

    # Transaction A: a concurrent reconcile already inserted the item, not committed yet.
    conn_a = pg_lf_engine.connect()
    tx_a = conn_a.begin()
    conn_a.execute(
        text("INSERT INTO pedido_compra_lineas_facturadas (pedido_id, item_id, cantidad) VALUES (1, 501, 3)")
    )

    resultado: dict = {}
    pid_listo = threading.Event()

    def reconcile_b() -> None:
        with Session(pg_lf_engine) as session:
            try:
                resultado["pid"] = session.execute(text("SELECT pg_backend_pid()")).scalar()
                pid_listo.set()
                reconciliar_lineas_facturadas(session, 1)
                session.commit()
                resultado["ok"] = True
            except Exception as exc:  # noqa: BLE001 - the assertion reports it
                resultado["error"] = exc
                pid_listo.set()

    hilo = threading.Thread(target=reconcile_b)
    hilo.start()
    try:
        assert pid_listo.wait(10)
        # Wait until B is blocked on A's uncommitted unique key, so the race is real.
        limite = time.monotonic() + 10
        bloqueado = False
        while time.monotonic() < limite and "error" not in resultado:
            with pg_lf_engine.connect() as probe:
                bloqueado = bool(
                    probe.execute(
                        text("SELECT 1 FROM pg_stat_activity WHERE pid = :pid AND wait_event_type = 'Lock'"),
                        {"pid": resultado["pid"]},
                    ).scalar()
                )
            if bloqueado:
                break
            time.sleep(0.05)
        assert bloqueado, f"reconcile B never waited on A's row: {resultado}"
        tx_a.commit()
        hilo.join(10)
    finally:
        if tx_a.is_active:
            tx_a.rollback()
        conn_a.close()
        hilo.join(10)

    assert "error" not in resultado, f"reconcile B failed instead of upserting: {resultado.get('error')!r}"
    assert resultado.get("ok") is True
    assert _lineas(pg_lf_engine) == [(501, 5)]


def test_fractional_net_is_floored_not_rounded(pg_lf_engine):
    # Invoice 1.5 + 2.4 = 3.9, credit note 1.2 → net 2.7. Rounding would pay 3 units.
    with pg_lf_engine.begin() as conn:
        _seed(conn, lineas=[(1, 501, "1.5"), (2, 501, "2.4"), (3, 502, "4")], nc_lineas=[(4, 501, "1.2")])

    with Session(pg_lf_engine) as session:
        reconciliar_lineas_facturadas(session, 1)
        session.commit()

    assert _lineas(pg_lf_engine) == [(501, 2), (502, 4)]


def test_migration_backfill_floors_a_fractional_net(pg_lf_engine):
    migration = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20261104_pedido_lineas_facturadas.py"
    spec = importlib.util.spec_from_file_location("pedido_lineas_facturadas_pg", migration)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pg_lf_engine.begin() as conn:
        _seed(conn, lineas=[(1, 501, "1.5"), (2, 501, "2.4"), (3, 502, "4")], nc_lineas=[(4, 501, "1.2")])
        conn.execute(text(module.BACKFILL))

    assert _lineas(pg_lf_engine) == [(501, 2), (502, 4)]


def test_clone_subtracts_a_credit_note_frozen_on_its_corrected_from_pedido(pg_lf_engine):
    # Pedido 1 still holds the credit note; corregir_pedido moved the invoice
    # link to clone 2, and 2 was later corrected into 3: a two-hop chain.
    with pg_lf_engine.begin() as conn:
        _seed(conn, lineas=[(1, 501, "10")], nc_lineas=[(2, 501, "1")])
        conn.execute(text("INSERT INTO pedidos_compra VALUES (2, NULL, 1), (3, 100, 2)"))
        conn.execute(text("UPDATE pedidos_compra SET ct_transaction_id = NULL WHERE id = 1"))

    with Session(pg_lf_engine) as session:
        reconciliar_lineas_facturadas(session)
        session.commit()

    with pg_lf_engine.connect() as conn:
        filas = conn.execute(text("SELECT pedido_id, item_id, cantidad FROM pedido_compra_lineas_facturadas")).all()
    assert [tuple(f) for f in filas] == [(3, 501, 9)]
