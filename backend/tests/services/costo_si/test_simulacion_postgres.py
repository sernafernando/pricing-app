"""The T4 dry-run's read-only stand-ins (sell-in-costo-si T4, plan handoffs/sell-in-costo-si-t4-plan.md §2): the real
reader runs on a database without costo SI, reads the steps computed in memory, and nothing can be written.
Invented data."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Iterator

import psycopg2.errors
import pytest
from sqlalchemy import Engine, text

from app.models.combo_componente import ComboComponente
from app.models.item_cost_list_history import ItemCostListHistory
from app.models.producto import ProductoERP
from app.models.tb_item import TBItem
from app.services.costo_si import lote, simulacion
from tests.conftest import POSTGRES_TEST_URL
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

D = Decimal
P, Q = 7101, 7102

# Prod before the deploy: no costo SI table at all, and `tipo_cambio` from before a migration added `compra`.
STUBS = [
    "CREATE TABLE tipo_cambio (id SERIAL PRIMARY KEY, fecha DATE NOT NULL, moneda VARCHAR(3) NOT NULL,"
    " venta NUMERIC(18, 6), created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ, timestamp_actualizacion TIMESTAMPTZ)",
]
TABLES = [ProductoERP.__table__, TBItem.__table__, ComboComponente.__table__, ItemCostListHistory.__table__]


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("costo_si_sim", TABLES, STUBS) as engine:
        with engine.begin() as conn:
            for item in (P, Q):
                conn.execute(
                    text(
                        "INSERT INTO productos_erp (item_id, codigo, descripcion, moneda_costo, costo)"
                        " VALUES (:i, :c, 'Producto', 'USD', 30)"
                    ),
                    {"i": item, "c": f"C{item}"},
                )
                conn.execute(
                    text("INSERT INTO tb_item (comp_id, item_id, item_code, cat_id) VALUES (1, :i, :c, 3)"),
                    {"i": item, "c": f"C{item}"},
                )
            conn.execute(text("INSERT INTO tipo_cambio (fecha, moneda, venta) VALUES ('2026-09-01', 'USD', 1000)"))
        yield engine


@pytest.fixture()
def motor(engine: Engine) -> Iterator[Engine]:
    with engine.connect() as conn:
        esquema = conn.execute(text("SELECT current_schema()")).scalar()
    motor = simulacion.motor_solo_lectura(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={esquema}"})
    yield motor
    motor.dispose()


def _paso(item_id: int, orden: int, fecha: date, promedio: str, moneda: str = "USD") -> dict:
    return {
        "item_id": item_id,
        "orden": orden,
        "tipo": "compra",
        "fecha": fecha,
        "promedio_usd": D(promedio),
        "moneda": moneda,
        "cantidad": 0,
        "stock_antes": 0,
        "stock_base": 0,
        "stock_despues": 0,
    }


def test_reader_reads_the_steps_computed_in_memory_on_a_database_without_costo_si(motor: Engine) -> None:
    with simulacion.simular(motor) as sim:
        sim.sombra.fijar_pasos([_paso(P, 0, date(2026, 10, 1), "25"), _paso(P, 1, date(2026, 10, 20), "20")])
        costos = lote.en_fechas(
            sim.db, [(P, date(2026, 9, 30)), (P, date(2026, 10, 5)), (P, date(2026, 10, 25)), (Q, date(2026, 10, 5))]
        )
    antes, primero, segundo, otro = (
        costos[k]
        for k in [(P, date(2026, 9, 30)), (P, date(2026, 10, 5)), (P, date(2026, 10, 25)), (Q, date(2026, 10, 5))]
    )
    assert (antes.fuente, antes.costo) == (lote.FUENTE_LISTA, D(30))  # before its first step: list cost
    assert (primero.fuente, primero.costo, primero.costo_ars) == (lote.FUENTE_COSTO_SI, D(25), D(25000))
    assert (segundo.costo, segundo.costo_si_desde) == (D(20), date(2026, 10, 20))
    assert otro.fuente == lote.FUENTE_LISTA  # no steps of its own


def test_the_current_cost_reads_them_too(motor: Engine) -> None:
    with simulacion.simular(motor) as sim:
        sim.sombra.fijar_pasos([_paso(P, 0, date(2026, 10, 1), "25")])
        assert lote.actuales(sim.db, [P])[P].costo == D(25)


def test_missing_tables_and_columns_are_listed_and_read_as_their_stand_ins(motor: Engine) -> None:
    with simulacion.simular(motor, tablas=["tipo_cambio", "costo_si_factura_tc", "productos_erp"]) as sim:
        sombras = {s.nombre: s.motivo for s in sim.sombra.sombras}
        assert sombras == {
            "costo_si_pasos": "pasos",
            "costo_si_factura_tc": "falta tabla",
            "tipo_cambio": "faltan columnas: compra",
        }
        assert sim.db.execute(text("SELECT count(*) FROM costo_si_factura_tc")).scalar() == 0
        assert sim.db.execute(text("SELECT venta, compra FROM tipo_cambio")).one() == (D(1000), None)


def test_a_statement_with_its_own_ctes_keeps_them(motor: Engine) -> None:
    with simulacion.simular(motor) as sim:
        sim.sombra.fijar_pasos([_paso(P, 0, date(2026, 10, 1), "25")])
        fila = sim.db.execute(
            text(
                "WITH x AS (SELECT CAST(:i AS int) AS i) SELECT p.promedio_usd FROM x JOIN costo_si_pasos p ON p.item_id = x.i"
            ),
            {"i": P},
        ).scalar()
    assert fila == D(25)


def test_the_steps_hide_the_ones_the_database_has(engine: Engine, motor: Engine) -> None:
    """After the deploy the table exists: the dry-run still reads what the recompute WILL store, never the stored."""
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE costo_si_pasos (item_id INT, orden INT, fecha DATE, promedio_usd NUMERIC, moneda TEXT)")
        )
        conn.execute(text("INSERT INTO costo_si_pasos VALUES (:i, 0, '2026-10-01', 99, 'USD')"), {"i": P})
    try:
        with simulacion.simular(motor) as sim:
            sim.sombra.fijar_pasos([_paso(P, 0, date(2026, 10, 1), "25")])
            assert lote.actuales(sim.db, [P])[P].costo == D(25)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE costo_si_pasos"))


def test_nothing_can_be_written_and_nothing_is(engine: Engine, motor: Engine) -> None:
    with pytest.raises(simulacion.SentenciaNoPermitida):
        with simulacion.simular(motor) as sim:
            sim.db.execute(text("UPDATE productos_erp SET costo = 1 WHERE item_id = :i"), {"i": P})
    with engine.connect() as conn:
        assert conn.execute(text("SELECT costo FROM productos_erp WHERE item_id = :i"), {"i": P}).scalar() == 30


def test_a_write_that_skipped_the_filter_is_refused_by_the_server(motor: Engine) -> None:
    """The second layer: even a statement sent straight through the driver runs in a READ ONLY transaction."""
    with motor.connect() as conn:
        cursor = conn.connection.dbapi_connection.cursor()
        with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
            cursor.execute("UPDATE productos_erp SET costo = 1")
        conn.rollback()


def test_a_list_cost_on_the_date_still_comes_from_the_history(engine: Engine, motor: Engine) -> None:
    """The stand-in only replaces costo SI: the list-cost fallback reads the real history, as on prod."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tb_item_cost_list_history (iclh_id, coslis_id, item_id, iclh_price, curr_id, iclh_cd)"
                " VALUES (1, 1, :i, 28, 2, :cd)"
            ),
            {"i": Q, "cd": datetime(2026, 9, 15, 10)},
        )
    try:
        with simulacion.simular(motor) as sim:
            assert lote.en_fechas(sim.db, [(Q, date(2026, 10, 1))])[(Q, date(2026, 10, 1))].costo == D(28)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM tb_item_cost_list_history"))


def test_read_only_comes_from_begin_and_never_from_a_session_set(motor: Engine) -> None:
    """psycopg2's `readonly` opens each transaction with BEGIN READ ONLY: the transaction is read-only while the
    session default stays off (a `SET SESSION CHARACTERISTICS` would have turned the default on, and through
    PgBouncer it would leak to the next client)."""
    with motor.connect() as conn:
        assert conn.execute(text("SELECT current_setting('transaction_read_only')")).scalar() == "on"
        assert conn.execute(text("SELECT current_setting('default_transaction_read_only')")).scalar() == "off"
        conn.rollback()


@pytest.mark.parametrize(
    "sentencia",
    [
        "SET statement_timeout = '1s'",
        "set search_path = public",
        "UPDATE productos_erp SET costo = 1",
        "DO $$ BEGIN END $$",
    ],
)
def test_only_reads_reach_the_server(motor: Engine, sentencia: str) -> None:
    with pytest.raises(simulacion.SentenciaNoPermitida):
        with motor.connect() as conn:
            conn.execute(text(sentencia))


def test_comments_in_front_do_not_hide_a_set(motor: Engine) -> None:
    with pytest.raises(simulacion.SentenciaNoPermitida):
        with motor.connect() as conn:
            conn.execute(text("-- harmless\n  SET work_mem = '1GB'"))


def test_a_read_with_comments_in_front_goes_through(motor: Engine) -> None:
    with motor.connect() as conn:
        assert conn.execute(text("-- the reader's note\n  SELECT 1")).scalar() == 1


def test_every_stand_in_is_a_materialized_cte(motor: Engine) -> None:
    """Orchestrator: "stand-ins as MATERIALIZED CTEs, no CREATE/temp tables, no SET" — each stand-in is computed once
    per statement, never inlined into the caller's plan, and lives only inside the statement."""
    with simulacion.simular(motor, tablas=["tipo_cambio", "costo_si_factura_tc"]) as sim:
        sql, _ = sim.sombra.reescribir("SELECT 1 FROM costo_si_pasos, costo_si_factura_tc, tipo_cambio", {})
    for nombre in ("costo_si_pasos", "costo_si_factura_tc", "tipo_cambio"):
        assert f"{nombre} AS MATERIALIZED (" in sql
    assert " AS (" not in sql.replace("AS t(", "")
