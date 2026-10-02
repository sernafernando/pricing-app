"""Seeding helpers for the Métricas ML board tests (ODD `metricas-ml-tablero`,
"Sin tabla resumen"): the board reads the SAME tables Ventas ML reads, so a
test seeds what the ingestion and the metrics worker would have stored --
an order, its items, their frozen costs, its stored metrics, its relevant
payment and its group row (with the accreditation `group_date`). ORM
inserts: SQLite only (the shared metadata's ARRAY column is JSON there).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Optional, Sequence

from app.models.ml_group_metrics import MlGroupMetrics
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_order_metrics import MlOrderMetrics, MlOrderMetricsDirty
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.ml_payments import MlPaymentOps

SELLER = 999


@dataclass(frozen=True)
class Line:
    """One sold item: `product=None` means no frozen cost row."""

    product: Optional[int]
    mla: str
    qty: int
    unit_price: Decimal
    unit_cost: Optional[Decimal] = Decimal("10")
    variation_id: Optional[int] = None


def seed_order(
    db,
    order_id: int,
    accredited: Optional[datetime],
    lines: Sequence[Line],
    *,
    tg: Optional[str] = None,
    costo: Optional[str] = None,
    gauss_status: Optional[str] = "ok",
    status: str = "paid",
    covered: Optional[bool] = None,
    currency: str = "ARS",
    pack_id: Optional[int] = None,
    dirty: bool = False,
) -> None:
    """An order with its items, frozen costs, stored metrics (unless
    `gauss_status is None`: never computed) and an approved payment on
    `accredited` (none when `accredited is None`). No group row: see
    `seed_group` / `seed_sale`. Timestamps are stored in UTC (SQLite keeps
    the wall clock and drops the offset)."""
    accredited = accredited.astimezone(timezone.utc) if accredited is not None else None
    created = accredited or datetime(2026, 1, 1, tzinfo=timezone.utc)
    total = sum((Decimal(line.unit_price) * line.qty for line in lines), Decimal("0"))
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status=status,
            covered_by_marketplace=covered,
            ml_last_updated=created,
            date_created=created,
            seller_id=SELLER,
            currency_id=currency,
            total_amount=total,
            paid_amount=total,
        )
    )
    db.flush()
    for line in lines:
        db.add(
            MlOrderItemOps(
                order_id=order_id,
                item_id=line.mla,
                variation_id=line.variation_id,
                quantity=line.qty,
                unit_price=Decimal(line.unit_price),
            )
        )
        if line.product is not None:
            db.add(
                MlOrderItemCosto(
                    order_id=order_id,
                    item_id=line.mla,
                    variation_id=line.variation_id,
                    costo_origen=line.unit_cost or 0,
                    moneda="ARS",
                    costo_unitario_ars=line.unit_cost,
                    iva_pct=21,
                    precio_unitario=Decimal(line.unit_price),
                    fuente="test",
                    producto_item_id=line.product,
                )
            )
    if accredited is not None:
        db.add(
            MlPaymentOps(payment_id=order_id * 10 + 1, order_id=order_id, status="approved", date_approved=accredited)
        )
    if gauss_status is not None:
        db.add(
            MlOrderMetrics(
                order_id=order_id,
                neto=Decimal("0"),
                total_gauss=Decimal(tg) if tg is not None else None,
                costo_mercaderia=Decimal(costo) if costo is not None else None,
                gauss_status=gauss_status,
                formula_version=2,
                computed_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
            )
        )
    if dirty:
        db.add(MlOrderMetricsDirty(order_id=order_id, version=1, reason="test", attempts=0))
    db.flush()


def seed_group(db, group_key: str, members: Iterable[int], group_date: Optional[datetime]) -> None:
    group_date = group_date.astimezone(timezone.utc) if group_date is not None else None
    db.add(
        MlGroupMetrics(
            group_key=group_key,
            gauss_status="ok",
            member_order_ids=list(members),
            group_date=group_date,
            formula_version=2,
            computed_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
        )
    )
    db.flush()


def seed_sale(db, order_id: int, accredited: Optional[datetime], lines: Sequence[Line], **kwargs) -> None:
    """A lone order AND its group row (`o:<order_id>`)."""
    seed_order(db, order_id, accredited, lines, **kwargs)
    seed_group(db, f"o:{order_id}", [order_id], accredited)
