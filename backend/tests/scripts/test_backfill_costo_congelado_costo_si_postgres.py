"""The frozen-cost backfill on the real costo SI reader (Postgres): a missing sale cost is filled with the same rule
the live freeze uses (`costeo_service.congelar` -> `lote.en_fechas`), on the sale's ART calendar day -- costo SI
where the product has it; where the reader says 'lista', the dated list history as before, never today's cost.

Prod case behind it (2026-11-22 dry-run): item 319 has costo SI 13.56337 USD from 10-01 but the backfill froze its
list 13.63 USD; and two sales on the night of 17/11 ART (18/11 UTC) took 18/11's rate."""

from __future__ import annotations

import itertools
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.scripts import backfill_costo_congelado as script
from tests.services.costo_si import _world as w
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

ROUTER, SIN_SI = 7201, 7202
_orders = itertools.count(970_000)
_OPS_STUBS = ("CREATE TABLE ml_orders_ops", "CREATE TABLE ml_order_items_ops")


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    tables = [*w.TABLES, MlOrdersOps.__table__, MlOrderItemOps.__table__]
    stubs = [s for s in w.STUBS if not s.startswith(_OPS_STUBS)]
    with throwaway_schema("backfill_csi", tables, stubs, after=w.install) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _mundo(engine: Engine, monkeypatch) -> Iterator[None]:
    """ROUTER (USD, iva 10.5): list 13.63 from 10-13, costo SI 13.56337 from 10-01. SIN_SI (USD): list 40 from
    10-01, no costo SI. BNA 1575 on 11-17, 1580 on 11-18. Sold by numeric SKU (no publication, #2350)."""
    w.producto(engine, ROUTER, costo="13.63")
    w.producto(engine, SIN_SI, costo="40")
    w.run(engine, "UPDATE productos_erp SET iva = 10.5")
    w.costo_lista(engine, ROUTER, datetime(2026, 10, 13, 12), "13.63")
    w.costo_lista(engine, SIN_SI, datetime(2026, 10, 1, 12), "40")
    w.run(
        engine,
        "INSERT INTO costo_si_pasos (item_id, orden, tipo, fecha, cantidad, stock_antes, stock_base, stock_despues,"
        " promedio_usd, moneda) VALUES (:i, 0, 'inicio', '2026-10-01', 0, 0, 0, 0, 13.56337, 'USD')",
        i=ROUTER,
    )
    w.tipo_cambio(engine, date(2026, 11, 17), 1575)
    w.tipo_cambio(engine, date(2026, 11, 18), 1580)
    monkeypatch.setattr(script, "SessionLocal", sessionmaker(bind=engine))
    yield
    w.run(engine, "DELETE FROM ml_order_items_ops")
    w.run(engine, "DELETE FROM ml_orders_ops")
    w.clean(engine)  # keeps the schema's one combo: the backfill refuses an empty bill of materials


def _venta(engine: Engine, sku: str, cuando: datetime, qty: int = 1) -> int:
    order_id = next(_orders)
    w.run(
        engine,
        "INSERT INTO ml_orders_ops (order_id, seller_id, status, date_created, ml_last_updated)"
        " VALUES (:o, 1, 'paid', :c, :c)",
        o=order_id,
        c=cuando,
    )
    w.run(
        engine,
        "INSERT INTO ml_order_items_ops (order_id, item_id, seller_sku, quantity, unit_price)"
        " VALUES (:o, :m, :s, :q, 32999)",
        o=order_id,
        m=f"MLA{sku}",
        s=sku,
        q=qty,
    )
    return order_id


def _fila(engine: Engine, order_id: int):
    filas = w.rows(
        engine,
        "SELECT costo_origen, moneda, tipo_cambio, costo_unitario_ars, fuente, costo_fecha"
        " FROM ml_order_item_costos WHERE order_id = :o",
        o=order_id,
    )
    if not filas:
        return None
    campos = ("costo_origen", "moneda", "tipo_cambio", "costo_unitario_ars", "fuente", "costo_fecha")
    return SimpleNamespace(**dict(zip(campos, filas[0])))


def test_a_product_with_costo_si_is_frozen_at_its_costo_si_not_its_list_cost(engine: Engine) -> None:
    order_id = _venta(engine, str(ROUTER), datetime(2026, 11, 17, 14, 42, tzinfo=timezone.utc))

    result = script.run_backfill(limit=None, dry_run=False)

    assert result.written == 1
    fila = _fila(engine, order_id)
    assert fila.costo_origen == Decimal("13.5634")  # the column keeps 4 decimals, as the re-freeze rounds
    assert fila.moneda == "USD"
    assert fila.tipo_cambio == Decimal("1575")
    assert fila.costo_unitario_ars == Decimal("21362.3078")  # 13.56337 x 1575, not the list's 21467.25
    assert fila.fuente == "costo_si_sku"  # the live freeze's fuente: `recongelar_costo_si` keeps re-freezing it
    assert fila.costo_fecha == date(2026, 11, 17)  # the sale date, as the live freeze and the re-freeze write


def test_a_sale_late_on_an_art_day_takes_that_days_rate(engine: Engine) -> None:
    # 2026-11-18 00:22 UTC is 2026-11-17 21:22 in Buenos Aires: the sale is of the 17th (BNA 1575), not the 18th.
    order_id = _venta(engine, str(SIN_SI), datetime(2026, 11, 18, 0, 22, tzinfo=timezone.utc))

    script.run_backfill(limit=None, dry_run=False)

    fila = _fila(engine, order_id)
    assert fila.tipo_cambio == Decimal("1575")
    assert fila.costo_unitario_ars == Decimal("40") * 1575


def test_a_product_without_costo_si_keeps_its_dated_list_cost_and_backfill_fuente(engine: Engine) -> None:
    order_id = _venta(engine, str(SIN_SI), datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc))

    script.run_backfill(limit=None, dry_run=False)

    fila = _fila(engine, order_id)
    assert (fila.costo_origen, fila.moneda, fila.fuente) == (Decimal("40"), "USD", "hist_sku")
    assert fila.costo_fecha == date(2026, 10, 1)  # the history row used, as before


def test_a_costo_si_with_no_rate_is_skipped_never_the_list_cost(engine: Engine) -> None:
    w.run(engine, "DELETE FROM tipo_cambio")
    order_id = _venta(engine, str(ROUTER), datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc))

    result = script.run_backfill(limit=None, dry_run=False)

    assert _fila(engine, order_id) is None
    assert result.skipped[script.SKIP_NO_FX] == 1


def test_the_dry_run_writes_nothing(engine: Engine) -> None:
    order_id = _venta(engine, str(ROUTER), datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc))

    result = script.run_backfill(limit=None, dry_run=True)

    assert (result.resolved, result.written) == (1, 0)
    assert _fila(engine, order_id) is None
