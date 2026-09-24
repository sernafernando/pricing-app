"""RED/GREEN tests for the four doubtful-case toggle switches on
`SalesFilter`/`build_scope` (design D12, spec KPI R9-R11, PR11.T1-T3).

Each switch, when OFF, excludes the WHOLE GROUP (pack or lone order) whose
COLLAPSED status matches the switch's class -- the same collapse rule
`ml_ventas_ops.py`'s response building applies over ALL of a group's
members (`collapse()` in `filters.py`), never a per-order filter. A pack
with one 'paid' order and one 'unknown' order collapses to 'mixed' on that
axis, not 'unknown' -- so it is excluded by the Mixta switch, not the A
revisar switch, which pins the T3 parity requirement below.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrdersOps, MlShipmentOps
from app.services.ml_sales_query import filters as filters_module
from app.services.ml_sales_query.filters import SalesFilter, build_scope, effective_switches


@pytest.fixture(autouse=True)
def _seller(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


def _seed_order(
    db,
    order_id: int,
    *,
    status: str = "paid",
    payment_status: str | None = None,
    shipping_status: str | None = None,
    logistic_type: str | None = None,
    has_no_shipping_tag: bool = False,
    date_created: datetime | None = None,
    pack_id: int | None = None,
    shipping_id: int | None = None,
) -> None:
    if date_created is None:
        date_created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    if shipping_id is None:
        shipping_id = order_id * 10 if shipping_status is not None else None
    order = MlOrdersOps(
        order_id=order_id,
        pack_id=pack_id,
        status=status,
        payment_status=payment_status,
        has_no_shipping_tag=has_no_shipping_tag,
        ml_last_updated=date_created,
        date_created=date_created,
        seller_id=999,
        total_amount=100,
        paid_amount=100,
        currency_id="ARS",
        shipping_id=shipping_id,
    )
    db.add(order)
    if shipping_id is not None and shipping_status is not None:
        db.add(
            MlShipmentOps(
                shipment_id=shipping_id,
                order_id=order_id,
                status=shipping_status,
                logistic_type=logistic_type,
            )
        )
    db.flush()


def _seed_metrics(db, order_id: int, *, gauss_status: str = "ok") -> None:
    db.add(
        MlOrderMetrics(
            order_id=order_id,
            neto=100,
            neto_sin_iva=80,
            iva_reconcilia=True,
            costo_mercaderia=50,
            total_gauss=30,
            markup_pct=60,
            gauss_status=gauss_status,
            formula_version=1,
            computed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    db.flush()


def _group_keys(db, scope):
    return {row.group_key for row in scope.listing_query.with_entities(scope.group_key.label("group_key")).all()}


class TestIncludeUnknown:
    def test_default_excludes_unknown_group(self, db):
        # status='pending_payment' (not in PAID_ORDER_STATUSES, no claim, no
        # shipment) derives operation_status 'unknown' -- collapses to
        # 'unknown' since it is a lone order.
        _seed_order(db, 1, status="pending_payment")
        scope = build_scope(db, SalesFilter(include_unknown=False))
        assert _group_keys(db, scope) == set()

    def test_include_unknown_true_shows_it(self, db):
        _seed_order(db, 1, status="pending_payment")
        scope = build_scope(db, SalesFilter(include_unknown=True))
        assert _group_keys(db, scope) == {"o:1"}

    def test_known_group_unaffected_by_switch_off(self, db):
        # `shipping_status="delivered"` resolves BOTH axes to a known value
        # (operation_status='delivered', goods_status='delivered') -- a bare
        # 'paid' order with no shipment has goods_status='unknown' by
        # definition (no shipment means "unknown", not "never shipped"),
        # which would make this its own positive case, not a negative one.
        _seed_order(db, 2, status="paid", shipping_status="delivered")
        scope = build_scope(db, SalesFilter(include_unknown=False))
        assert _group_keys(db, scope) == {"o:2"}

    def test_no_shipping_tagged_order_shown_by_default_never_unknown(self, db):
        """K0 (user product decision): a real in-person pickup / 'acordar
        con el vendedor' sale is tagged `no_shipping` by ML and has no
        `ml_shipments_ops` row -- it must NOT be classified into the
        doubtful 'A revisar' class just because there is no shipment. With
        the default switches (A revisar OFF), it must still show."""
        _seed_order(db, 50, status="paid", shipping_status=None, has_no_shipping_tag=True)
        scope = build_scope(db, SalesFilter())  # defaults: include_unknown=False
        assert _group_keys(db, scope) == {"o:50"}

    def test_genuinely_unknown_order_still_excluded_by_default(self, db):
        """The counterpart of the fix above: an order with no shipment and
        NO `no_shipping` tag is genuinely doubtful and must stay excluded
        by the default-OFF 'A revisar' switch."""
        _seed_order(db, 51, status="paid", shipping_status=None, has_no_shipping_tag=False)
        scope = build_scope(db, SalesFilter())
        assert _group_keys(db, scope) == set()


class TestIncludeInDispute:
    def test_include_in_dispute_false_excludes_it(self, db):
        _seed_order(db, 3, status="paid", payment_status="in_mediation", shipping_status="delivered")
        scope = build_scope(db, SalesFilter(include_in_dispute=False))
        assert _group_keys(db, scope) == set()

    def test_include_in_dispute_true_shows_it(self, db):
        # `shipping_status="delivered"` keeps goods_status out of 'unknown'
        # so the default-OFF "A revisar" switch does not ALSO exclude this
        # row -- this test isolates "En disputa" alone.
        _seed_order(db, 3, status="paid", payment_status="in_mediation", shipping_status="delivered")
        scope = build_scope(db, SalesFilter(include_in_dispute=True))
        assert _group_keys(db, scope) == {"o:3"}


class TestIncludeMixed:
    def test_pack_with_diverging_operation_status_is_mixed_and_excluded_when_off(self, db):
        # Both members carry `shipping_status="delivered"` so goods_status
        # collapses to a single 'delivered' (never the uniform 'unknown' a
        # shipment-less order would produce, which would make the default
        # -OFF "A revisar" switch exclude this pack for an unrelated
        # reason). `status="cancelled"` on member 10 forces its
        # operation_status to 'cancelled' regardless of the shipment (op
        # status precedence, `_operation_status_expr`), diverging from
        # member 11's 'delivered' -- collapsed operation_status is 'mixed'
        # -- without touching "En disputa" (also default OFF).
        _seed_order(db, 10, pack_id=999, status="cancelled", shipping_status="delivered")
        _seed_order(db, 11, pack_id=999, status="paid", shipping_status="delivered")
        scope = build_scope(db, SalesFilter(include_mixed=False))
        assert _group_keys(db, scope) == set()

    def test_pack_with_diverging_operation_status_shown_when_on(self, db):
        _seed_order(db, 10, pack_id=999, status="cancelled", shipping_status="delivered")
        _seed_order(db, 11, pack_id=999, status="paid", shipping_status="delivered")
        scope = build_scope(db, SalesFilter(include_mixed=True))
        assert _group_keys(db, scope) == {"p:999"}

    def test_modo_logistico_mixed_does_not_count_as_mixed(self, db):
        """PR11.T3: `modo_logistico='mixed'` (a logistics attribute derived
        from shipment type, not from operation/goods status) must NOT
        trigger the Mixta exclusion -- only a collapsed operation_status or
        goods_status of 'mixed' does (design D12 Mixta resolution). Two
        orders in the same pack, both 'delivered'/'delivered' on the two
        status axes (so BOTH collapse to a single value, never 'mixed'),
        with different `logistic_type` (which collapses `modo_logistico` to
        'mixed' in the router's own response-building `_collapse` call --
        proven by `test_ml_ventas_ops_sales_router.py`'s existing coverage
        of that field), must still show when the Mixta switch is OFF."""
        _seed_order(db, 20, pack_id=888, status="paid", shipping_status="delivered", logistic_type="fulfillment")
        _seed_order(db, 21, pack_id=888, status="paid", shipping_status="delivered", logistic_type="cross_docking")
        scope = build_scope(db, SalesFilter(include_mixed=False))
        assert _group_keys(db, scope) == {"p:888"}


class TestIncludeProvisional:
    def test_include_provisional_false_excludes_group_with_a_provisional_member(self, db):
        _seed_order(db, 30, status="paid", shipping_status="delivered")
        _seed_metrics(db, 30, gauss_status="provisional")
        scope = build_scope(db, SalesFilter(include_provisional=False))
        assert _group_keys(db, scope) == set()

    def test_include_provisional_true_shows_it(self, db):
        _seed_order(db, 30, status="paid", shipping_status="delivered")
        _seed_metrics(db, 30, gauss_status="provisional")
        scope = build_scope(db, SalesFilter(include_provisional=True))
        assert _group_keys(db, scope) == {"o:30"}

    def test_ok_group_unaffected(self, db):
        _seed_order(db, 31, status="paid", shipping_status="delivered")
        _seed_metrics(db, 31, gauss_status="ok")
        scope = build_scope(db, SalesFilter(include_provisional=False))
        assert _group_keys(db, scope) == {"o:31"}


class TestDefaults:
    def test_defaults_match_spec_r11(self):
        f = SalesFilter()
        assert f.include_unknown is False
        assert f.include_in_dispute is False
        assert f.include_mixed is True
        assert f.include_provisional is True


class TestExplicitFacetOverridesSwitch:
    """K2 (design D12): "explicit facet selection overrides its switch" --
    a user who explicitly filters `operation_status=unknown` or
    `operation_status=in_dispute` (or `goods_status=unknown`) must see
    those rows even while the corresponding toggle is OFF, otherwise the
    facet filter and the toggle silently fight each other and the user
    sees an empty table with no explanation."""

    def test_explicit_operation_status_unknown_overrides_a_revisar_off(self, db):
        _seed_order(db, 60, status="pending_payment")
        scope = build_scope(db, SalesFilter(operation_status="unknown", include_unknown=False))
        assert _group_keys(db, scope) == {"o:60"}

    def test_explicit_goods_status_unknown_overrides_a_revisar_off(self, db):
        _seed_order(db, 61, status="paid", shipping_status=None)
        scope = build_scope(db, SalesFilter(goods_status="unknown", include_unknown=False))
        assert _group_keys(db, scope) == {"o:61"}

    def test_explicit_operation_status_in_dispute_overrides_en_disputa_off(self, db):
        _seed_order(db, 62, status="paid", payment_status="in_mediation", shipping_status="delivered")
        scope = build_scope(db, SalesFilter(operation_status="in_dispute", include_in_dispute=False))
        assert _group_keys(db, scope) == {"o:62"}

    def test_no_explicit_facet_leaves_switch_in_control(self, db):
        _seed_order(db, 63, status="pending_payment")
        scope = build_scope(db, SalesFilter(include_unknown=False))
        assert _group_keys(db, scope) == set()

    def test_effective_switches_reports_the_override(self):
        f = SalesFilter(operation_status="unknown", include_unknown=False)
        applied = effective_switches(f)
        assert applied.include_unknown is True
        # Untouched switches are not affected by the override.
        assert applied.include_in_dispute is False


class TestUnknownClassificationIsExplicitNotAlphabetical:
    """K4: `is_unknown` must be derived from an EXPLICIT "this axis
    collapsed to exactly 'unknown'" check, not from `MIN()` happening to
    pick 'unknown' out of a genuinely mixed (distinct>1) set of statuses --
    an incidental property of today's status vocabulary (every other name
    sorts before 'unknown') that a new status name sorting after it would
    silently break."""

    def test_mixed_group_with_a_status_name_sorting_after_unknown_is_not_misclassified(self, db, monkeypatch):
        # Patch a shipping-status mapping so one member's goods_status is a
        # value that sorts AFTER 'unknown' -- `MIN('unknown', 'zzz_x')` is
        # 'unknown', which is exactly the incidental behaviour this fix
        # removes.
        patched_map = dict(filters_module.GOODS_STATUS_BY_SHIPPING_STATUS)
        patched_map["not_delivered"] = "zzz_after_unknown"
        monkeypatch.setattr(filters_module, "GOODS_STATUS_BY_SHIPPING_STATUS", patched_map)

        # Member 70: no shipment -> goods_status 'unknown' (real, no tag).
        _seed_order(db, 70, pack_id=444, status="paid", shipping_status=None)
        # Member 71: patched shipping status -> goods_status
        # 'zzz_after_unknown'. Both members are 'paid' on the operation
        # axis (no shipment 'delivered' bump), so op axis stays single.
        _seed_order(db, 71, pack_id=444, status="paid", shipping_status="not_delivered")

        # Mixta ON (the group IS genuinely mixed on goods_status), A
        # revisar OFF -- the group is mixed, not "collapsed to unknown",
        # so it must show.
        scope = build_scope(db, SalesFilter(include_mixed=True, include_unknown=False))
        assert _group_keys(db, scope) == {"p:444"}
