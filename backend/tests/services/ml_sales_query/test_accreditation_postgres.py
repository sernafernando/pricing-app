"""The day filter/sort, against Postgres and grouped/ordered/paged exactly
like the endpoint does (T7, mirrors `test_filters_switches_postgres.py`'s
rationale: a SQLite-only test never exercises the GROUP BY/ORDER BY over a
joined subquery, and that is exactly where the `group_by("group_key")`
ambiguity bug lived for three weeks).

T6: reproduces the real production shape, order `2000018641457084` --
created 2026-09-25, 9 payments (8 rejected, 1 approved accrediting
2026-09-30) -- and asserts it lands in the 30th, never the 25th.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, text

from app.models.ml_orders_ops import MlOrdersOps
from app.services.ml_sales_query.filters import SalesFilter, build_scope


def _order(session, order_id: int, pack_id: int | None = None, date_created: datetime | None = None) -> None:
    session.execute(
        text(
            "INSERT INTO ml_orders_ops "
            "(order_id, seller_id, status, ml_last_updated, date_created, pack_id, "
            " total_amount, paid_amount, currency_id) "
            "VALUES (:oid, 999, 'paid', now(), :dc, :pid, 100, 100, 'ARS')"
        ),
        {"oid": order_id, "pid": pack_id, "dc": date_created or datetime(2026, 1, 1, tzinfo=timezone.utc)},
    )


def _payment(session, payment_id: int, order_id: int, status: str, date_approved: datetime | None) -> None:
    session.execute(
        text(
            "INSERT INTO ml_payments_ops (payment_id, order_id, status, date_approved) "
            "VALUES (:pid, :oid, :status, :da)"
        ),
        {"pid": payment_id, "oid": order_id, "status": status, "da": date_approved},
    )


def _key_page(session, scope, date_range=None):
    """Mirrors the router's grouped/ordered/paged query, including the
    `nullslast()` DESC sort over the accreditation subquery column."""
    accred = scope.accreditation_subquery
    q = scope.listing_query.with_entities(
        scope.group_key.label("group_key"),
        func.max(accred.c.accreditation_date).label("group_date"),
    ).group_by(scope.group_key)
    q = q.order_by(func.max(accred.c.accreditation_date).desc().nullslast(), func.max(MlOrdersOps.order_id).desc())
    return q.limit(50).offset(0).all()


@pytest.fixture()
def slate(pg_order_metrics_triggers_db, monkeypatch):
    from app.core.config import settings
    from app.models.ml_order_metrics import MlOrderMetrics
    from app.models.ml_orders_ops import MlOperationLink
    from app.models.rma_claim_ml import RmaClaimML

    monkeypatch.setattr(settings, "ML_USER_ID", "999", raising=False)
    session = pg_order_metrics_triggers_db
    # `_apply_switches`/`_operation_status_expr` (through `build_scope`)
    # outerjoin `ml_order_metrics`/`ml_operation_links`/`rma_claims_ml`,
    # which `pg_order_metrics_triggers_engine` does not create -- same fix
    # `test_filters_switches_postgres.py` applies, for the same reason.
    # `_restore_pristine_pg_types` FIRST: the Postgres fixtures in
    # `conftest.py` call it on their own tables before building DDL, because
    # `_patch_pg_types_for_sqlite()` mutates the SHARED `Column` objects.
    # Creating a table here without it builds DDL from whatever the SQLite
    # fixture last left on those columns, so the same test sees different
    # column types depending on which files ran before it.
    from tests.conftest import _restore_pristine_pg_types

    tablas = (MlOrderMetrics.__table__, MlOperationLink.__table__, RmaClaimML.__table__)
    _restore_pristine_pg_types(tablas)
    for tabla in tablas:
        tabla.create(session.get_bind(), checkfirst=True)
    session.execute(text("DELETE FROM ml_orders_ops WHERE seller_id = 999"))
    session.commit()
    return session


@pytest.mark.postgres
class TestAccreditationDayFilterThroughTheEndpointQuery:
    def test_order_created_25th_accredited_30th_lands_in_30th_not_25th(self, slate) -> None:
        """T6, the production shape: order 2000018641457084, created
        2026-09-25, 8 rejected payments + 1 approved accrediting
        2026-09-30."""
        order_id = 2000018641457084
        _order(slate, order_id, date_created=datetime(2026, 9, 25, 16, 28, tzinfo=timezone.utc))
        for i in range(8):
            _payment(slate, order_id * 100 + i, order_id, "rejected", None)
        _payment(
            slate,
            order_id * 100 + 8,
            order_id,
            "approved",
            datetime(2026, 9, 30, 11, 42, tzinfo=timezone.utc),
        )
        slate.commit()

        day_30_start = datetime(2026, 9, 30, tzinfo=timezone.utc)
        day_30_end = day_30_start + timedelta(days=1)
        day_25_start = datetime(2026, 9, 25, tzinfo=timezone.utc)
        day_25_end = day_25_start + timedelta(days=1)

        scope_30 = build_scope(
            slate, SalesFilter(date_range=(day_30_start, day_30_end), include_unknown=True, include_in_dispute=True)
        )
        assert [r.group_key for r in _key_page(slate, scope_30)] == [f"o:{order_id}"]

        scope_25 = build_scope(
            slate, SalesFilter(date_range=(day_25_start, day_25_end), include_unknown=True, include_in_dispute=True)
        )
        assert _key_page(slate, scope_25) == []

    def test_pack_groups_move_as_one_on_the_later_members_day(self, slate) -> None:
        _order(slate, 900001, pack_id=700, date_created=datetime(2026, 9, 25, tzinfo=timezone.utc))
        _order(slate, 900002, pack_id=700, date_created=datetime(2026, 9, 25, tzinfo=timezone.utc))
        _payment(slate, 9000011, 900001, "approved", datetime(2026, 9, 25, 10, tzinfo=timezone.utc))
        _payment(slate, 9000021, 900002, "approved", datetime(2026, 9, 30, 10, tzinfo=timezone.utc))
        slate.commit()

        day_30_start = datetime(2026, 9, 30, tzinfo=timezone.utc)
        day_30_end = day_30_start + timedelta(days=1)
        scope = build_scope(
            slate, SalesFilter(date_range=(day_30_start, day_30_end), include_unknown=True, include_in_dispute=True)
        )
        assert [r.group_key for r in _key_page(slate, scope)] == ["p:700"]

    def test_group_by_string_alias_never_used_still_pages_fine(self, slate) -> None:
        """Same landmine `test_filters_switches_postgres.py` documents for
        the switches subquery: the accreditation subquery ALSO exposes a
        `group_key` output column now that it is always LEFT-joined, so
        the endpoint's `.group_by(group_key)` (the expression, never the
        string) must keep resolving to the CASE, not the subquery column."""
        _order(slate, 900030, date_created=datetime(2026, 9, 25, tzinfo=timezone.utc))
        slate.commit()
        scope = build_scope(slate, SalesFilter(include_unknown=True, include_in_dispute=True))
        rows = _key_page(slate, scope)
        assert [r.group_key for r in rows] == ["o:900030"]
