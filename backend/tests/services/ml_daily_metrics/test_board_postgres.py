"""ODD `metricas-ml-tablero`, "Sin tabla resumen", on real Postgres: the board
reads the orders straight (16-digit order and pack ids, a real
`ARRAY(BigInteger)` member list), buckets each sale on its Buenos Aires day
(`timezone()` in SQL), splits a multi-item order by frozen-cost share in
NUMERIC, leaves out a cancellation ML did not cover, and keeps every window
nested: 24h <= 3d <= 7d <= 15d <= 30d."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.services.ml_daily_metrics import board

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 30)
MLA = "MLA8000000001"
OTHER = "MLA8000000002"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


def _order(db, order_id, lines, *, status="paid", covered=None, pack_id=None, tg="10", costo="50") -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status=status,
            covered_by_marketplace=covered,
            ml_last_updated=NOW,
            date_created=NOW,
            seller_id=999,
            currency_id="ARS",
        )
    )
    db.flush()
    for product, mla, qty, unit_cost in lines:
        db.add(MlOrderItemOps(order_id=order_id, item_id=mla, quantity=qty, unit_price=Decimal("100")))
        db.add(
            MlOrderItemCosto(
                order_id=order_id,
                item_id=mla,
                costo_origen=unit_cost,
                moneda="ARS",
                costo_unitario_ars=unit_cost,
                iva_pct=21,
                precio_unitario=100,
                fuente="t",
                producto_item_id=product,
            )
        )
    db.add(
        MlOrderMetrics(
            order_id=order_id,
            total_gauss=Decimal(tg),
            costo_mercaderia=Decimal(costo),
            gauss_status="ok",
            formula_version=2,
            computed_at=NOW,
        )
    )
    db.flush()


def _group(db, key: str, members, group_date: datetime) -> None:
    # Raw SQL: the shared metadata's ARRAY column is patched to JSON for the
    # SQLite suite, so the ORM insert would send a JSON string.
    db.execute(
        text(
            "INSERT INTO ml_group_metrics "
            "(group_key, gauss_status, member_order_ids, group_date, formula_version, computed_at) "
            "VALUES (:gk, 'ok', CAST(:members AS BIGINT[]), :gd, 2, now())"
        ),
        {"gk": key, "members": "{" + ",".join(str(m) for m in members) + "}", "gd": group_date},
    )


def _rows(db, group_by="product"):
    f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY, group_by=group_by)
    with board.Board(db, f) as b:
        return {row.key: row for row in b.page(None)}


@pytest.mark.postgres
def test_the_board_reads_the_orders_on_postgres(board_pg) -> None:
    db = board_pg
    # Lone order 3h ago: in 24h and every window.
    _order(db, 2000012345678911, [(777, MLA, 2, 10)])
    _group(db, "o:2000012345678911", [2000012345678911], NOW - timedelta(hours=3))
    # Cancelled without coverage 1h ago: out of everything.
    _order(db, 2000012345678912, [(777, MLA, 5, 10)], status="cancelled")
    _group(db, "o:2000012345678912", [2000012345678912], NOW - timedelta(hours=1))
    # 02:55 UTC on Sep 28 is still Sep 27 in Buenos Aires: OUT of 3d (28..30).
    _order(db, 2000012345678913, [(777, MLA, 7, 10)])
    _group(db, "o:2000012345678913", [2000012345678913], datetime(2026, 9, 28, 2, 55, tzinfo=timezone.utc))
    # A pack with a 16-digit pack id: two members, one of them multi-item.
    pack = 2000009999999999
    _order(db, 2000012345678914, [(777, MLA, 1, 300), (778, OTHER, 2, 50)], pack_id=pack, tg="80", costo="400")
    _order(db, 2000012345678915, [(778, OTHER, 1, 50)], pack_id=pack, tg="5", costo="50")
    _group(db, f"p:{pack}", [2000012345678914, 2000012345678915], datetime(2026, 9, 20, 15, tzinfo=timezone.utc))

    rows = _rows(db)

    p777, p778 = rows["777"], rows["778"]
    assert (p777.units_24h, p777.windows["3d"], p777.windows["7d"], p777.units) == (2, 2, 9, 10)
    assert p778.units == 3
    # 3/4 of order ...914's Total Gauss/cost goes to 777's item (300 vs 100).
    assert p777.tg == Decimal("10") + Decimal("10") + Decimal("60")
    assert p778.tg == Decimal("20") + Decimal("5")
    assert float(p777.markup) == pytest.approx(80 / 400 * 100)
    for row in rows.values():
        assert row.units_24h <= row.windows["3d"] <= row.windows["7d"] <= row.windows["15d"] <= row.windows["30d"]
    assert set(_rows(db, "publication")) == {MLA, OTHER}
