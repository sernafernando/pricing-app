"""
Postgres-only integration tests for the TP-Link metrics aggregation core
(`app.scripts._tplink_metricas_core`).

These are the ONLY tests that exercise `build_aggregation_sql()`'s raw SQL
end-to-end (unit tests cover the Python `fold_order_rows()` fold in
isolation with synthetic rows — see `test_tplink_metricas_core_fold.py`).
SQLite cannot run this query (`::date` casts, correlated subqueries against
real ERP tables), so these tests seed a real Postgres schema and skip
cleanly when no Postgres test DB is configured.

**Execution policy** (mirrors `tests/integration/test_numeracion_concurrencia.py`):

    export TESTING_POSTGRES_URL="postgresql://user:pass@localhost:5432/pricing_test"
    # Run `alembic upgrade head` against that DB BEFORE running these tests.

Without `TESTING_POSTGRES_URL` set, the whole module SKIPS (not fails/errors)
— confirmed by running `pytest tests/` with the default sqlite conftest.

Design references: sdd/tplink-metricas-dual-key-dedup/design (obs 859, D1/D3),
slice-2 apply-progress (obs 864).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Generator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.scripts._tplink_metricas_core import (
    TPLINK_COSLIS_ID,
    TPLINK_STORE_ID,
    build_aggregation_sql,
    fold_order_rows,
)

POSTGRES_URL = os.environ.get("TESTING_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    POSTGRES_URL is None,
    reason=(
        "TESTING_POSTGRES_URL no configurada — estos tests ejercitan el SQL "
        "crudo de build_aggregation_sql() contra un schema Postgres real "
        "(::date casts, subqueries correlacionadas), no soportado en SQLite. "
        "Exportar TESTING_POSTGRES_URL=postgresql://... y correr "
        "`alembic upgrade head` contra esa DB antes de habilitarlos."
    ),
)

COMP_ID = 1
FROM_TS = datetime(2026, 6, 1, 0, 0, 0)
TO_TS = datetime(2026, 6, 30, 0, 0, 0)


@pytest.fixture(scope="module")
def pg_engine() -> Generator[Engine, None, None]:
    engine = create_engine(POSTGRES_URL, pool_size=5, max_overflow=0)
    yield engine
    engine.dispose()


@pytest.fixture()
def pg_session(pg_engine: Engine) -> Generator[Session, None, None]:
    """One transactional session per test — rolled back at teardown so
    seeded rows never leak between tests or pollute the shared test DB."""
    connection = pg_engine.connect()
    txn = connection.begin()
    SessionLocal = sessionmaker(bind=connection)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        txn.rollback()
        connection.close()


def _seed_item(session: Session, item_id: int) -> None:
    """Minimal item + cost list row (coslis_id=8, ARS) — everything else the
    query touches (marca/categoria/subcategoria/productos_erp) is a LEFT
    JOIN that tolerates NULL, so it's intentionally NOT seeded here."""
    session.execute(
        text(
            """
            INSERT INTO tb_item (comp_id, item_id, item_code, item_desc)
            VALUES (:comp_id, :item_id, :code, :desc)
            ON CONFLICT DO NOTHING
            """
        ),
        {"comp_id": COMP_ID, "item_id": item_id, "code": f"SKU-{item_id}", "desc": f"Item {item_id}"},
    )
    session.execute(
        text(
            """
            INSERT INTO tb_item_cost_list (comp_id, coslis_id, item_id, coslis_price, curr_id)
            VALUES (:comp_id, :coslis_id, :item_id, :price, 1)
            ON CONFLICT DO NOTHING
            """
        ),
        {"comp_id": COMP_ID, "coslis_id": TPLINK_COSLIS_ID, "item_id": item_id, "price": 1000},
    )


def _seed_publication(session: Session, mlp_id: int, item_id: int) -> None:
    session.execute(
        text(
            """
            INSERT INTO tb_mercadolibre_items_publicados
                (mlp_id, comp_id, item_id, mlp_official_store_id, mlp_listing_type_id, prli_id)
            VALUES (:mlp_id, :comp_id, :item_id, :store_id, 'gold_special', 4)
            ON CONFLICT DO NOTHING
            """
        ),
        {"mlp_id": mlp_id, "comp_id": COMP_ID, "item_id": item_id, "store_id": TPLINK_STORE_ID},
    )


def _seed_order(
    session: Session,
    mlo_id: int,
    ml_id: str,
    mlo_cd: datetime,
    details: list[tuple[int, int, float, float]],
    # details = [(mlod_id, item_id, mlp_id, unit_price, quantity)] flattened below
) -> None:
    session.execute(
        text(
            """
            INSERT INTO tb_mercadolibre_orders_header
                (comp_id, mlo_id, ml_id, mlo_cd, mlo_status)
            VALUES (:comp_id, :mlo_id, :ml_id, :mlo_cd, 'paid')
            ON CONFLICT (mlo_id) DO NOTHING
            """
        ),
        {"comp_id": COMP_ID, "mlo_id": mlo_id, "ml_id": ml_id, "mlo_cd": mlo_cd},
    )
    for mlod_id, item_id, mlp_id, unit_price, quantity in details:
        _seed_item(session, item_id)
        _seed_publication(session, mlp_id, item_id)
        session.execute(
            text(
                """
                INSERT INTO tb_mercadolibre_orders_detail
                    (comp_id, mlo_id, mlod_id, mlp_id, item_id, mlo_unit_price, mlo_quantity, mlo_cd)
                VALUES (:comp_id, :mlo_id, :mlod_id, :mlp_id, :item_id, :unit_price, :quantity, :mlo_cd)
                ON CONFLICT (mlod_id) DO NOTHING
                """
            ),
            {
                "comp_id": COMP_ID,
                "mlo_id": mlo_id,
                "mlod_id": mlod_id,
                "mlp_id": mlp_id,
                "item_id": item_id,
                "unit_price": unit_price,
                "quantity": quantity,
                "mlo_cd": mlo_cd,
            },
        )


def _run_aggregation(session: Session) -> list:
    rows = session.execute(
        build_aggregation_sql(),
        {
            "from_ts": FROM_TS,
            "to_ts": TO_TS,
            "coslis_id": TPLINK_COSLIS_ID,
            "store_id": TPLINK_STORE_ID,
        },
    ).fetchall()
    return rows


class TestSummedMonetaryValues:
    """A multi-item order must fold to ONE row with SUMMED monto_total,
    costo, comisión, ganancia — and shipping charged once, not per detail
    (design D1)."""

    def test_multi_item_order_sums_monetary_fields(self, pg_session: Session) -> None:
        mlo_id = 900001
        mlo_cd = datetime(2026, 6, 15, 10, 0, 0)
        _seed_order(
            pg_session,
            mlo_id=mlo_id,
            ml_id="MLA900001",
            mlo_cd=mlo_cd,
            details=[
                (9000011, 500001, 700001, 1000.0, 2),
                (9000012, 500002, 700002, 2000.0, 1),
            ],
        )
        pg_session.flush()

        rows = _run_aggregation(pg_session)
        order_rows = [r for r in rows if r.id_operacion == mlo_id]
        assert len(order_rows) == 2, "SQL must return one row PER DETAIL, no collapsing (fold is Python-side)"

        folded = fold_order_rows(order_rows)
        assert mlo_id in folded
        folded_row = folded[mlo_id]

        expected_monto_total = (1000.0 * 2) + (2000.0 * 1)
        assert folded_row["monto_total"] == pytest.approx(expected_monto_total)
        assert folded_row["cantidad"] == pytest.approx(3)

        # costo_total_sin_iva must be the SUM across both details' cost
        # (coslis_id=8, seeded 1000 ARS/unit for both items) — not a single
        # detail's cost.
        assert folded_row["costo_total_sin_iva"] > 0
        assert folded_row["costo_total_sin_iva"] == pytest.approx(1000.0 * 2 + 1000.0 * 1, rel=0.05)

        # comisión y ganancia deben ser sumas > 0 sobre ambos detalles, no el
        # valor de un solo detalle.
        assert folded_row["comision_ml"] > 0
        assert folded_row["ganancia"] != 0

        # Shipping applied EXACTLY ONCE per order — no seller_shipping_cost
        # was seeded here, so costo_envio_ml must be exactly 0, never doubled.
        assert folded_row["costo_envio_ml"] == pytest.approx(0.0)

    def test_shipping_charged_once_not_per_detail(self, pg_session: Session) -> None:
        """Seed seller_shipping_cost on the order's shipping row; a
        2-detail order must NOT double-charge shipping (design D1 hazard)."""
        mlo_id = 900002
        mlo_cd = datetime(2026, 6, 16, 10, 0, 0)
        _seed_order(
            pg_session,
            mlo_id=mlo_id,
            ml_id="MLA900002",
            mlo_cd=mlo_cd,
            details=[
                (9000021, 500003, 700003, 1000.0, 1),
                (9000022, 500004, 700004, 1000.0, 1),
            ],
        )
        pg_session.execute(
            text(
                """
                INSERT INTO tb_mercadolibre_orders_shipping
                    (comp_id, mlm_id, mlo_id, mlshippmentcost4seller)
                VALUES (:comp_id, :mlm_id, :mlo_id, :cost)
                """
            ),
            {"comp_id": COMP_ID, "mlm_id": mlo_id, "mlo_id": mlo_id, "cost": 242.0},
        )
        pg_session.flush()

        rows = _run_aggregation(pg_session)
        order_rows = [r for r in rows if r.id_operacion == mlo_id]
        folded = fold_order_rows(order_rows)
        folded_row = folded[mlo_id]

        # 242 ARS / 1.21 IVA multiplier = 200 sin IVA, charged ONCE.
        # If shipping were double-counted (once per detail) this would be
        # ~400 instead.
        assert folded_row["costo_envio_ml"] == pytest.approx(200.0, rel=0.05)


class TestDateBoundaryHalfOpen:
    """Half-open window `[from_ts, to_ts)` on `mlo_cd` (design D3): an order
    exactly on the `to_date` boundary IS included; one at next-day 00:00 is
    NOT."""

    def test_order_on_to_date_boundary_is_included(self, pg_session: Session) -> None:
        boundary_ts = TO_TS - timedelta(seconds=1)
        mlo_id = 900010
        _seed_order(
            pg_session,
            mlo_id=mlo_id,
            ml_id="MLA900010",
            mlo_cd=boundary_ts,
            details=[(9000101, 500010, 700010, 500.0, 1)],
        )
        pg_session.flush()

        rows = _run_aggregation(pg_session)
        assert any(r.id_operacion == mlo_id for r in rows)

    def test_order_at_next_day_midnight_is_excluded(self, pg_session: Session) -> None:
        mlo_id = 900011
        _seed_order(
            pg_session,
            mlo_id=mlo_id,
            ml_id="MLA900011",
            mlo_cd=TO_TS,  # exactly at to_ts — half-open bound excludes it
            details=[(9000111, 500011, 700011, 500.0, 1)],
        )
        pg_session.flush()

        rows = _run_aggregation(pg_session)
        assert not any(r.id_operacion == mlo_id for r in rows)


class TestCrossJobSqlIdentity:
    """Backfill and incremental jobs both call
    `_tplink_metricas_core.build_aggregation_sql()` — over the SAME seeded
    data, the SAME query object must produce byte-identical rows on repeated
    execution (determinism, design D1)."""

    def test_query_is_deterministic_across_repeated_execution(self, pg_session: Session) -> None:
        mlo_id = 900020
        mlo_cd = datetime(2026, 6, 20, 10, 0, 0)
        _seed_order(
            pg_session,
            mlo_id=mlo_id,
            ml_id="MLA900020",
            mlo_cd=mlo_cd,
            details=[
                (9000201, 500020, 700020, 1500.0, 2),
                (9000202, 500021, 700021, 750.0, 1),
            ],
        )
        pg_session.flush()

        first_run = fold_order_rows(_run_aggregation(pg_session))
        second_run = fold_order_rows(_run_aggregation(pg_session))

        assert first_run[mlo_id] == second_run[mlo_id]

    def test_both_job_modules_import_the_same_sql_builder(self) -> None:
        """Structural dedup guarantee (design v2 header note): both wrapper
        modules must reference the identical `build_aggregation_sql`
        function object — not independent copies that could drift."""
        from app.scripts import _tplink_metricas_core as core
        from app.scripts import agregar_metricas_tplink as backfill
        from app.scripts import agregar_metricas_tplink_incremental as incremental

        assert backfill.build_aggregation_sql is core.build_aggregation_sql
        assert incremental.build_aggregation_sql is core.build_aggregation_sql
