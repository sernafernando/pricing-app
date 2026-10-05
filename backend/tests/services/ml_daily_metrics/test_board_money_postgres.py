"""Review findings on the order-based board, on real Postgres: its money
equals Ventas ML's KPI aggregate (`ml_sales_query/aggregate.py`) TO THE
CENT, as `Decimal`, never a float.

- Shares that are not representable (three equal weights of 100.00 ->
  33.33...; 1/3 and 2/3 by quantity) are NUMERIC end to end: a float branch
  in the share CASE made Postgres resolve every money sum to double
  precision. Totals are rounded to cents once, at the end, like Ventas ML's
  sums of 2-decimal values.
- `gauss_status='unresolved'`: Ventas ML counts the order's gross but it
  carries no Total Gauss -- its reader (`order_metrics.read`, `OrderMetrics`)
  enforces "unresolved => total_gauss is NULL" and REFUSES a stored row that
  breaks it (ValueError, the KPI endpoint 500s). So for Ventas ML an
  unresolved order never adds Total Gauss and is never a markup candidate,
  whatever its cost says. The board mirrors that by status (only `ok` and
  `provisional` carry money for Total Gauss and markup, like the old
  rollup), so a row breaking the invariant cannot leak into the sums.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.ml_payments import MlPaymentOps
from app.services.ml_daily_metrics import board
from app.services.ml_daily_metrics.sales import group_key_expr
from app.services.ml_sales_query.aggregate import aggregate_order_metrics

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 30)
SOLD = datetime(2026, 9, 20, 15, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


def _order(db, order_id, lines, *, tg, costo, status="ok", pack_id=None) -> None:
    """`lines`: (product or None, mla, qty, unit_price, unit_cost or None)."""
    total = sum(Decimal(price) * qty for _p, _m, qty, price, _c in lines)
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status="paid",
            ml_last_updated=NOW,
            date_created=SOLD,
            seller_id=999,
            currency_id="ARS",
            total_amount=total,
            paid_amount=total,
        )
    )
    db.flush()
    for product, mla, qty, price, unit_cost in lines:
        db.add(MlOrderItemOps(order_id=order_id, item_id=mla, quantity=qty, unit_price=Decimal(price)))
        if product is not None:
            db.add(
                MlOrderItemCosto(
                    order_id=order_id,
                    item_id=mla,
                    costo_origen=Decimal(unit_cost),
                    moneda="ARS",
                    costo_unitario_ars=Decimal(unit_cost),
                    iva_pct=21,
                    precio_unitario=Decimal(price),
                    fuente="t",
                    producto_item_id=product,
                )
            )
    db.add(MlPaymentOps(payment_id=order_id * 10, order_id=order_id, status="approved", date_approved=SOLD))
    db.add(
        MlOrderMetrics(
            order_id=order_id,
            neto=Decimal("0"),
            total_gauss=Decimal(tg) if tg is not None else None,
            costo_mercaderia=Decimal(costo) if costo is not None else None,
            gauss_status=status,
            formula_version=2,
            computed_at=NOW,
        )
    )
    db.flush()


def _group(db, key: str, members) -> None:
    db.execute(
        text(
            "INSERT INTO ml_group_metrics "
            "(group_key, gauss_status, member_order_ids, group_date, formula_version, computed_at) "
            "VALUES (:gk, 'ok', CAST(:members AS BIGINT[]), :gd, 2, now())"
        ),
        {"gk": key, "members": "{" + ",".join(str(m) for m in members) + "}", "gd": SOLD},
    )


def _seed(db) -> list:
    # Three equal weights on 100.00: 33.33... each.
    _order(
        db,
        2000060000000001,
        [
            (31, "MLA9000000031", 1, "40", "10"),
            (32, "MLA9000000032", 1, "40", "10"),
            (33, "MLA9000000033", 1, "40", "10"),
        ],
        tg="100.00",
        costo="30.00",
    )
    _group(db, "o:2000060000000001", [2000060000000001])
    # A pack: weights 1 and 2 on 10.01, plus a lone-item sibling.
    _order(
        db,
        2000060000000002,
        [(31, "MLA9000000031", 1, "10", "3"), (34, "MLA9000000034", 2, "10", "3")],
        tg="10.01",
        costo="7.00",
        pack_id=2000069999999999,
    )
    _order(
        db, 2000060000000003, [(35, "MLA9000000035", 1, "5", "1")], tg="0.05", costo="0.10", pack_id=2000069999999999
    )
    _group(db, "p:2000069999999999", [2000060000000002, 2000060000000003])
    # Unknown weight (no frozen cost on one item): split 1/3 - 2/3 by quantity.
    _order(
        db,
        2000060000000004,
        [(36, "MLA9000000036", 1, "7", "2"), (None, "MLA9000000037", 2, "7", None)],
        tg="1.00",
        costo="0.70",
    )
    _group(db, "o:2000060000000004", [2000060000000004])
    # Unresolved, cost known: gross yes; Total Gauss and markup no.
    _order(db, 2000060000000005, [(38, "MLA9000000038", 1, "99", "40")], tg=None, costo="50.00", status="unresolved")
    _group(db, "o:2000060000000005", [2000060000000005])
    return [2000060000000001, 2000060000000002, 2000060000000003, 2000060000000004, 2000060000000005]


def _ventas_ml(db, order_ids):
    gk = group_key_expr()
    listing = db.query(MlOrdersOps).filter(MlOrdersOps.order_id.in_(order_ids))
    return aggregate_order_metrics(db, listing, db.query(MlOrdersOps), gk)


@pytest.mark.postgres
def test_board_money_equals_ventas_ml_to_the_cent(board_pg) -> None:
    db = board_pg
    order_ids = _seed(db)
    f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY)

    with board.Board(db, f) as b:
        kpis = b.kpis()
        line_types = set(
            db.execute(
                text(f"SELECT DISTINCT pg_typeof(tg)::text || '/' || pg_typeof(mtg)::text FROM {board.LINES_TABLE}")
            ).scalars()
        )
    ventas = _ventas_ml(db, order_ids)

    assert line_types == {"numeric/numeric"}
    assert kpis.gross == ventas.gross_billed_ars
    assert kpis.tg == ventas.total_gauss_sum == Decimal("111.06")
    assert board.markup_of(kpis.mtg, kpis.costo) == ventas.markup_weighted_pct


@pytest.mark.postgres
def test_an_unresolved_row_carrying_total_gauss_never_reaches_the_money(board_pg) -> None:
    """A stored row that breaks the invariant ("unresolved but with Total
    Gauss"): Ventas ML refuses to read it; the board counts its units and
    gross (it sold) and keeps it out of Total Gauss and markup -- what an
    unresolved order means everywhere else."""
    db = board_pg
    _order(db, 2000060000000006, [(39, "MLA9000000039", 1, "99", "40")], tg="12.34", costo="50.00", status="unresolved")
    _group(db, "o:2000060000000006", [2000060000000006])
    f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY)

    with board.Board(db, f) as b:
        row = {r.key: r for r in b.page(None)}["39"]

    with pytest.raises(ValueError, match="unresolved requires total_gauss=None"):
        _ventas_ml(db, [2000060000000006])
    assert (row.units, row.gross) == (1, Decimal("99.00"))
    assert row.tg == 0 and row.markup is None


@pytest.mark.postgres
def test_series_points_are_exact_cents(board_pg) -> None:
    """The KPI daily series carries money too: each point is the day's sum
    rounded to the cent like every other money value, never a NUMERIC tail
    (111.0599...) or a float."""
    db = board_pg
    order_ids = _seed(db)
    f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY)

    with board.Board(db, f) as b:
        kpis = b.kpis()
    ventas = _ventas_ml(db, order_ids)
    day = (SOLD.date() - f.date_from).days

    assert kpis.series_tg[day] == ventas.total_gauss_sum == Decimal("111.06")
    assert kpis.series_gross[day] == ventas.gross_billed_ars
    assert kpis.series_markup[day] == round(float(ventas.markup_weighted_pct), 1)
