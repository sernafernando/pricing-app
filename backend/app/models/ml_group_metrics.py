"""Per-GROUP stored Gauss metrics (ventas-ml-rediseno PR20, design D3/D7,
spec `ml-order-stored-metrics` R9-R14).

`MlGroupMetrics` is the group-scoped counterpart of `MlOrderMetrics`: ONE
row per group (a pack, or a standalone order treated as a group of one --
R9's "group of one is not a special case"), keyed by `group_key` in the
SAME format `_group_key_expr()` produces
(`app/services/ml_sales_query/filters.py`): `"p:<pack_id>"` for a pack,
`"o:<order_id>"` for a standalone order.

Same NULL/status discipline as `MlOrderMetrics` (R1/R2), applied at group
level: `gauss_status='unresolved'` forces `total_gauss`/`markup_pct` NULL,
never a fabricated or partial value.

`member_order_ids` is the group's CURRENT membership as of the last
recompute (`app/services/ml_group_metrics/compute.py::recompute_group_metrics`
re-derives it from `ml_orders_ops` every time, never trusts a stale cached
list) -- a GIN index backs the fanout lookups that need to find "which
group(s) did this order used to belong to" (R14 orphan cleanup).

`group_date` is the group-level date `GET /sales` and `GET /sales/kpis`
filter grouped rows by (KPI R20): a pack that straddles an active date
filter is included/excluded as ONE whole pack, never split by member.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.postgresql import ARRAY

from app.core.database import Base


class MlGroupMetrics(Base):
    """The last-computed Gauss metrics for one GROUP (pack, or a standalone
    order as a group of one). See module docstring for the design context."""

    __tablename__ = "ml_group_metrics"
    __table_args__ = (
        CheckConstraint("gauss_status IN ('ok', 'provisional', 'unresolved')", name="ck_ml_group_metrics_status"),
        Index("ix_ml_group_metrics_status", "gauss_status"),
        Index("ix_ml_group_metrics_member_order_ids", "member_order_ids", postgresql_using="gin"),
    )

    group_key = Column(String(32), primary_key=True)

    neto = Column(Numeric(14, 2), nullable=True)
    neto_sin_iva = Column(Numeric(14, 2), nullable=True)
    costo_mercaderia = Column(Numeric(14, 2), nullable=True)
    # NULL iff gauss_status='unresolved' (design D2 rule, applied at group
    # level) -- never a fabricated 0 or a partial sum.
    total_gauss = Column(Numeric(14, 2), nullable=True)
    markup_pct = Column(Numeric(9, 2), nullable=True)
    gauss_status = Column(String(16), nullable=False)
    member_order_ids = Column(ARRAY(BigInteger), nullable=False)
    # Gross billed for the whole group: the SUM of its members'
    # `ml_orders_ops.total_amount`, with `currency_id` the single currency
    # they all share. BOTH are NULL when the members do not share one
    # currency, or when any member's amount is unknown -- the same rule
    # `listar_ventas` already applies to a pack row, and for the reason its
    # own comment gives: "adding ARS to USD produces a number that means
    # nothing", and a mixed pack rendering a numeric amount beside an honest
    # null would read as MORE trustworthy than the null, not less.
    #
    # Stored here rather than summed at read time so the group record is
    # self-sufficient: KPI aggregation reads ONE row per pedido and never
    # falls back to walking its members for a single measure (KPI R18).
    gross_amount = Column(Numeric(14, 2), nullable=True)
    currency_id = Column(String(8), nullable=True)
    # The group-level date `GET /sales` / `GET /sales/kpis` filter by
    # (KPI R20) -- never split a pack across a date-range boundary.
    group_date = Column(DateTime(timezone=True), nullable=True)
    formula_version = Column(SmallInteger, nullable=False)
    computed_at = Column(DateTime(timezone=True), nullable=False)
