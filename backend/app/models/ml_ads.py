"""Mercado Libre Product Ads facts (ml-billing-balance, PR 1a; design "Schema", D1-D2).

Three tables, all keyed by the ad day in the account's local (Argentina) calendar:

- `ml_ads_day_ledger`: one row per (source, advertiser, day) saying whether that day was fetched. A
  missing ledger row means "not fetched"; a missing fact row on a ledgered day means zero (owner Q4).
- `ml_ads_ad_group_days`: the ad-group grain of a day, with the drill status of its `/ads` pages.
- `ml_ads_item_days`: the (ad group, item) grain, the one the Board joins on.
- `ml_ads_display_campaign_days` and `ml_ads_brand_days`: account-level Display and Brand Ads (PR 3), never MLA-level.

Money is `Numeric(16, 2)` built from `Decimal(str(value))`; payloads are kept in `raw`. No table stores
a sum that this system computed (ADS-4): ML's own reported figures (`summary_cost`, a group's `cost`)
are facts, sums over rows are queries. Nothing reads or writes these tables yet (PR 1b onward).
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base

LEDGER_STATUSES = ("fetching", "refetch", "closed", "mismatch", "error", "unavailable")
DRILL_STATUSES = ("not_needed", "pending", "done", "mismatch")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class MlAdsDayLedger(Base):
    """Cursor and audit of one (source, advertiser, day): 'product_ads' now; 'display' and 'brand_ads' (PR 3)."""

    __tablename__ = "ml_ads_day_ledger"

    source = Column(String(20), primary_key=True)
    advertiser_id = Column(BigInteger, primary_key=True)
    day = Column(Date, primary_key=True)

    status = Column(String(16), nullable=False)
    groups_offset = Column(Integer, nullable=False, server_default="0", default=0)
    summary_cost = Column(Numeric(16, 2), nullable=True)  # ML's reported day total
    summary_raw = Column(JSONB, nullable=True)  # ML's `metrics_summary`, untouched
    attempts = Column(Integer, nullable=False, server_default="0", default=0)
    attempts_day = Column(Date, nullable=True)
    mismatch_laps = Column(Integer, nullable=False, server_default="0", default=0)
    last_error = Column(Text, nullable=True)
    fetch_started_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    final = Column(Boolean, nullable=False, server_default=text("false"), default=False)

    __table_args__ = (
        CheckConstraint(_in_list("status", LEDGER_STATUSES), name="ck_ml_ads_day_ledger_status"),
        Index(
            "ix_ml_ads_day_ledger_open",
            "source",
            "status",
            postgresql_where=text("status <> 'closed'"),
        ),
    )


class MlAdsAdGroupDay(Base):
    """One ad group's metrics for one day. `drill_status='not_needed'` when its cost is 0 (never drilled)."""

    __tablename__ = "ml_ads_ad_group_days"

    advertiser_id = Column(BigInteger, primary_key=True)
    ad_group_id = Column(BigInteger, primary_key=True)
    day = Column(Date, primary_key=True)

    campaign_id = Column(BigInteger, nullable=True)
    ad_group_type = Column(String(20), nullable=True)
    external_id = Column(String(40), nullable=True)
    cost = Column(Numeric(16, 2), nullable=True)
    direct_amount = Column(Numeric(16, 2), nullable=True)
    indirect_amount = Column(Numeric(16, 2), nullable=True)
    clicks = Column(Integer, nullable=True)
    prints = Column(BigInteger, nullable=True)
    units_quantity = Column(Integer, nullable=True)
    drill_status = Column(String(10), nullable=False)
    ads_offset = Column(Integer, nullable=False, server_default="0", default=0)
    raw = Column(JSONB, nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(_in_list("drill_status", DRILL_STATUSES), name="ck_ml_ads_ad_group_days_drill_status"),
        Index("ix_ml_ads_ad_group_days_adv_day_drill", "advertiser_id", "day", "drill_status"),
    )


class MlAdsItemDay(Base):
    """One (ad group, item) pair's metrics for one day. The same MLA on two ad groups is two rows."""

    __tablename__ = "ml_ads_item_days"

    advertiser_id = Column(BigInteger, primary_key=True)
    ad_group_id = Column(BigInteger, primary_key=True)
    item_id = Column(String(30), primary_key=True)
    day = Column(Date, primary_key=True)

    campaign_id = Column(BigInteger, nullable=True)
    cost = Column(Numeric(16, 2), nullable=False, server_default="0", default=0)
    direct_amount = Column(Numeric(16, 2), nullable=False, server_default="0", default=0)
    indirect_amount = Column(Numeric(16, 2), nullable=False, server_default="0", default=0)
    organic_amount = Column(Numeric(16, 2), nullable=False, server_default="0", default=0)
    clicks = Column(Integer, nullable=False, server_default="0", default=0)
    direct_units = Column(Integer, nullable=False, server_default="0", default=0)
    indirect_units = Column(Integer, nullable=False, server_default="0", default=0)
    organic_units = Column(Integer, nullable=False, server_default="0", default=0)
    prints = Column(BigInteger, nullable=False, server_default="0", default=0)
    raw = Column(JSONB, nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_ml_ads_item_days_day_item", "day", "item_id"),)


class MlAdsDisplayCampaignDay(Base):
    """Display spend of one campaign on one day (account-level, ADS-9, D11). Never tied to an MLA."""

    __tablename__ = "ml_ads_display_campaign_days"

    advertiser_id = Column(BigInteger, primary_key=True)
    campaign_id = Column(BigInteger, primary_key=True)
    day = Column(Date, primary_key=True)

    consumed_budget = Column(Numeric(16, 2), nullable=False, server_default="0", default=0)
    prints = Column(BigInteger, nullable=False, server_default="0", default=0)
    clicks = Column(Integer, nullable=False, server_default="0", default=0)
    reach = Column(BigInteger, nullable=False, server_default="0", default=0)
    raw = Column(JSONB, nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MlAdsBrandDay(Base):
    """Brand Ads figures of one advertiser on one day (account-level, informational, ADS-10, D11).

    `cost` is the captured `dashboard.consumed_budget[{x, y}]` value of the day. It is shown, never subtracted.
    """

    __tablename__ = "ml_ads_brand_days"

    advertiser_id = Column(BigInteger, primary_key=True)
    day = Column(Date, primary_key=True)

    cost = Column(Numeric(16, 2), nullable=True)
    prints = Column(BigInteger, nullable=True)
    clicks = Column(Integer, nullable=True)
    raw = Column(JSONB, nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
