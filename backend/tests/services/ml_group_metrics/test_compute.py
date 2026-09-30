"""ventas-ml-rediseno PR20.T7 — `recompute_group_metrics(db, group_keys)`.

Reads each group's CURRENT member order ids from `ml_orders_ops` (by
`pack_id`, never a cached member list -- a member can have changed pack
since the group was last computed), sums `total_gauss`/`costo_mercaderia`/
`neto`/`neto_sin_iva` all-or-nothing (reusing `aggregate_pack_metrics`'s
core), and derives `gauss_status` via `group_gauss_status`. A pack with a
recalculating/pending/missing member returns `gauss_status='unresolved'`
(no resolvable numeric value), NEVER a partial sum (SM R10, KPI R19).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.models.ml_order_metrics import MlOrderMetrics, MlOrderMetricsDirty
from app.models.ml_orders_ops import MlOrdersOps
from app.services.ml_group_metrics.compute import recompute_group_metrics


def _order(
    db,
    order_id: int,
    pack_id=None,
    seller_id: int = 999,
    total_amount=Decimal("1000.00"),
    currency_id: str = "ARS",
    date_created=None,
) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status="paid",
            ml_last_updated=datetime(2026, 9, 20, tzinfo=timezone.utc),
            date_created=date_created or datetime(2026, 9, 15, tzinfo=timezone.utc),
            seller_id=seller_id,
            total_amount=total_amount,
            currency_id=currency_id,
        )
    )


def _stored(
    db,
    order_id: int,
    total_gauss=Decimal("50.00"),
    costo_mercaderia=Decimal("30.00"),
    neto=Decimal("100.00"),
    neto_sin_iva=Decimal("82.64"),
    gauss_status="ok",
) -> None:
    db.add(
        MlOrderMetrics(
            order_id=order_id,
            neto=neto,
            neto_sin_iva=neto_sin_iva,
            iva_reconcilia=True,
            costo_mercaderia=costo_mercaderia,
            total_gauss=total_gauss,
            markup_pct=Decimal("166.67") if total_gauss is not None else None,
            gauss_status=gauss_status,
            formula_version=2,
            computed_at=datetime.now(timezone.utc),
        )
    )


class TestRecomputeGroupMetricsPack:
    def test_two_resolved_members_sum_all_or_nothing(self, db):
        _order(db, 1, pack_id=555)
        _order(db, 2, pack_id=555)
        db.flush()
        _stored(db, 1, total_gauss=Decimal("50.00"), costo_mercaderia=Decimal("30.00"))
        _stored(db, 2, total_gauss=Decimal("20.00"), costo_mercaderia=Decimal("10.00"))
        db.commit()

        result = recompute_group_metrics(db, ["p:555"])

        group = result["p:555"]
        assert group.total_gauss == Decimal("70.00")
        assert group.costo_mercaderia == Decimal("40.00")
        assert group.gauss_status == "ok"
        assert set(group.member_order_ids) == {1, 2}

    def test_one_member_pending_no_row_makes_group_unresolved(self, db):
        _order(db, 1, pack_id=556)
        _order(db, 2, pack_id=556)
        db.flush()
        _stored(db, 1, total_gauss=Decimal("50.00"), costo_mercaderia=Decimal("30.00"))
        # order 2 has NO ml_order_metrics row at all -- pending
        db.commit()

        result = recompute_group_metrics(db, ["p:556"])

        group = result["p:556"]
        assert group.total_gauss is None
        assert group.costo_mercaderia is None
        assert group.markup_pct is None
        assert group.gauss_status == "unresolved"
        assert set(group.member_order_ids) == {1, 2}

    def test_one_member_dirty_recalculating_makes_group_unresolved(self, db):
        _order(db, 1, pack_id=557)
        _order(db, 2, pack_id=557)
        db.flush()
        _stored(db, 1, total_gauss=Decimal("50.00"), costo_mercaderia=Decimal("30.00"))
        _stored(db, 2, total_gauss=Decimal("20.00"), costo_mercaderia=Decimal("10.00"))
        db.add(MlOrderMetricsDirty(order_id=2, version=2, reason="input_write"))
        db.commit()

        result = recompute_group_metrics(db, ["p:557"])

        group = result["p:557"]
        assert group.total_gauss is None
        assert group.gauss_status == "unresolved"

    def test_single_order_pack_no_special_case(self, db):
        _order(db, 10, pack_id=558)
        db.flush()
        _stored(db, 10, total_gauss=Decimal("50.00"), costo_mercaderia=Decimal("30.00"))
        db.commit()

        result = recompute_group_metrics(db, ["p:558"])

        group = result["p:558"]
        assert group.total_gauss == Decimal("50.00")
        assert group.costo_mercaderia == Decimal("30.00")
        assert group.member_order_ids == [10]


class TestRecomputeGroupMetricsStandalone:
    def test_standalone_order_group_key(self, db):
        _order(db, 99, pack_id=None)
        db.flush()
        _stored(db, 99, total_gauss=Decimal("15.00"), costo_mercaderia=Decimal("5.00"))
        db.commit()

        result = recompute_group_metrics(db, ["o:99"])

        group = result["o:99"]
        assert group.total_gauss == Decimal("15.00")
        assert group.member_order_ids == [99]


class TestGroupGrossAmountCurrencyGate:
    """The group record carries its OWN gross billed so KPI aggregation reads
    ONE row per pedido instead of walking members for this single measure.

    The currency gate is not new policy: `listar_ventas` already refuses to
    add ARS to USD on a pack row, and its comment says why better than this
    one could -- a mixed pack rendering a numeric amount next to an honest
    null would read as MORE trustworthy than the null, not less."""

    def test_sums_the_members_amounts_when_they_share_a_currency(self, db):
        _order(db, 810001, pack_id=8100, total_amount=Decimal("1000.00"))
        _order(db, 810002, pack_id=8100, total_amount=Decimal("250.50"))
        db.flush()
        _stored(db, 810001)
        _stored(db, 810002)
        db.commit()

        grupo = recompute_group_metrics(db, ["p:8100"])["p:8100"]

        assert grupo.gross_amount == Decimal("1250.50")
        assert grupo.currency_id == "ARS"

    def test_a_mixed_currency_pack_has_no_gross_amount_at_all(self, db):
        _order(db, 810010, pack_id=8200, total_amount=Decimal("1000.00"), currency_id="ARS")
        _order(db, 810011, pack_id=8200, total_amount=Decimal("10.00"), currency_id="USD")
        db.flush()
        _stored(db, 810010)
        _stored(db, 810011)
        db.commit()

        grupo = recompute_group_metrics(db, ["p:8200"])["p:8200"]

        # BOTH null, not just the currency: a number with no currency is
        # exactly the misleading value this gate exists to avoid.
        assert grupo.gross_amount is None
        assert grupo.currency_id is None
        # And the rest of the group still resolves -- the currency gate is
        # about the AMOUNT, not about the Gauss chain, which is IVA-free and
        # currency-agnostic by then.
        assert grupo.total_gauss is not None

    def test_one_member_without_an_amount_makes_the_group_amount_unknown(self, db):
        _order(db, 810020, pack_id=8300, total_amount=Decimal("1000.00"))
        _order(db, 810021, pack_id=8300, total_amount=None)
        db.flush()
        _stored(db, 810020)
        _stored(db, 810021)
        db.commit()

        grupo = recompute_group_metrics(db, ["p:8300"])["p:8300"]

        assert grupo.gross_amount is None, "nunca una suma parcial"

    def test_a_standalone_order_carries_its_own_amount(self, db):
        _order(db, 810030, pack_id=None, total_amount=Decimal("777.00"))
        db.flush()
        _stored(db, 810030)
        db.commit()

        grupo = recompute_group_metrics(db, ["o:810030"])["o:810030"]

        assert grupo.gross_amount == Decimal("777.00")
        assert grupo.currency_id == "ARS"


class TestGroupDateIgnoresMembersWithoutADate:
    """ODD `ventas-ml-dia-por-acreditacion` (2026-09-30): `group_date` is now
    the MAX accreditation date over the group's members' relevant payments,
    never `date_created`. A member with NO accredited payment (unpaid, or
    only rejected payments) must not hide the real date from the member
    that DOES have one -- same "don't let an absence look like a value"
    discipline the old MIN-over-`date_created` version of this test
    documented, applied to the new basis.

    And it matters beyond tidiness: `group_date` is what the day filter
    (`ml_sales_query/filters.py`) and the KPI date filter read. A silently
    null date there is a sale that vanishes from the filtered range.
    """

    def test_a_member_without_accreditation_does_not_hide_the_real_one(self, db):
        from app.models.ml_payments import MlPaymentOps

        _order(db, 820001, pack_id=8500)
        _order(db, 820002, pack_id=8500)
        db.flush()
        _stored(db, 820001)
        _stored(db, 820002)
        # 820001 has NO relevant payment (e.g. only a rejected one) --
        # must not read as the maximum, nor as `None` for the whole group.
        db.add(MlPaymentOps(payment_id=8200011, order_id=820001, status="rejected", date_approved=None))
        db.add(
            MlPaymentOps(
                payment_id=8200021,
                order_id=820002,
                status="approved",
                date_approved=datetime(2026, 9, 15, tzinfo=timezone.utc),
            )
        )
        db.commit()

        grupo = recompute_group_metrics(db, ["p:8500"])["p:8500"]

        assert grupo.group_date is not None, "el miembro sin acreditación no puede tapar la real"
        # Compared without tzinfo on purpose: SQLite drops it on the way back
        # out, so demanding an aware datetime here would fail for a reason
        # that has nothing to do with what this test is about.
        assert grupo.group_date.replace(tzinfo=None) == datetime(2026, 9, 15)


class TestGroupDateIsAccreditationNotCreation:
    """ODD `ventas-ml-dia-por-acreditacion`: `group_date` must be the
    MAX(date_approved) over the group's members' relevant payments, never
    `date_created`."""

    def test_group_date_is_max_accreditation_across_members(self, db):
        from app.models.ml_payments import MlPaymentOps

        _order(db, 1, pack_id=900, date_created=datetime(2026, 9, 25, tzinfo=timezone.utc))
        _order(db, 2, pack_id=900, date_created=datetime(2026, 9, 25, tzinfo=timezone.utc))
        db.flush()
        _stored(db, 1)
        _stored(db, 2)
        db.add(
            MlPaymentOps(
                payment_id=901,
                order_id=1,
                status="approved",
                date_approved=datetime(2026, 9, 26, tzinfo=timezone.utc),
            )
        )
        db.add(
            MlPaymentOps(
                payment_id=902,
                order_id=2,
                status="approved",
                date_approved=datetime(2026, 9, 30, tzinfo=timezone.utc),
            )
        )
        db.commit()

        result = recompute_group_metrics(db, ["p:900"])

        assert result["p:900"].group_date.replace(tzinfo=None) == datetime(2026, 9, 30)

    def test_group_date_none_when_no_member_has_accredited_payment(self, db):
        _order(db, 3, pack_id=901, date_created=datetime(2026, 9, 25, tzinfo=timezone.utc))
        db.flush()
        _stored(db, 3)
        db.commit()

        result = recompute_group_metrics(db, ["p:901"])

        assert result["p:901"].group_date is None
