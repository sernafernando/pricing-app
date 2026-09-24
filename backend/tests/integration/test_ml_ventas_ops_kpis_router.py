"""Integration tests for `GET /api/ml-ventas-ops/sales/kpis` (PR11.T6-T9,
design D13, spec `ml-sales-kpi-aggregation` R7-R15).

`TestKpiListingParity` is the load-bearing suite (PR11.T8): for a set of
filter+toggle combinations, `GET /sales/kpis`'s aggregate must equal
summing exactly the rows `GET /sales` would show for the SAME combination,
excluding `recalculating`/`pending` orders, with `listed groups == summed
orders_count + recalculating_count + pending_count` for the lone-order
fixtures used here (one order == one group, so the group/order arithmetic
lines up exactly).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.config import settings
from app.models.ml_order_metrics import MlOrderMetrics, MlOrderMetricsDirty
from app.models.ml_orders_ops import MlOrdersOps, MlShipmentOps
from app.models.permiso import Permiso, RolPermisoBase
from app.models.worker_job_state import WorkerJobState
from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


def _grant_ml_ops_ver(db, rol_admin) -> None:
    permiso = db.query(Permiso).filter(Permiso.codigo == "ml_ops.ver").first()
    if not permiso:
        permiso = Permiso(
            codigo="ml_ops.ver", nombre="Ver operaciones ML", descripcion="", categoria="ml_ops", orden=200
        )
        db.add(permiso)
        db.flush()
    db.add(RolPermisoBase(rol_id=rol_admin.id, permiso_id=permiso.id))
    db.flush()


def _seed_order(
    db,
    order_id: int,
    *,
    status: str = "paid",
    payment_status: str | None = None,
    shipping_status: str | None = "delivered",
    total_amount: float = 100,
    currency_id: str = "ARS",
    date_created=None,
    buyer_nickname: str | None = None,
    has_no_shipping_tag: bool = False,
) -> None:
    if date_created is None:
        date_created = datetime(2026, 9, 1, tzinfo=timezone.utc)
    shipping_id = order_id * 10 if shipping_status is not None else None
    db.add(
        MlOrdersOps(
            order_id=order_id,
            status=status,
            payment_status=payment_status,
            ml_last_updated=date_created,
            date_created=date_created,
            seller_id=999,
            total_amount=total_amount,
            paid_amount=total_amount,
            currency_id=currency_id,
            shipping_id=shipping_id,
            buyer_nickname=buyer_nickname,
            has_no_shipping_tag=has_no_shipping_tag,
        )
    )
    if shipping_id is not None:
        db.add(MlShipmentOps(shipment_id=shipping_id, order_id=order_id, status=shipping_status))
    db.flush()


def _stored_metrics(
    db,
    order_id: int,
    *,
    neto=Decimal("80.00"),
    total_gauss=Decimal("20.00"),
    gauss_status: str = "ok",
    costo_mercaderia=Decimal("50.00"),
    markup_pct=Decimal("40.00"),
) -> None:
    db.add(
        MlOrderMetrics(
            order_id=order_id,
            neto=neto,
            total_gauss=total_gauss,
            gauss_status=gauss_status,
            costo_mercaderia=costo_mercaderia,
            markup_pct=markup_pct,
            formula_version=CURRENT_FORMULA_VERSION,
            computed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
    )
    db.flush()


def _seed_dirty(db, order_id: int, *, attempts: int = 0) -> None:
    db.add(MlOrderMetricsDirty(order_id=order_id, reason="test", attempts=attempts))
    db.flush()


class TestPermissionAndFlagGate:
    def test_no_permission_is_403(self, client, auth_headers):
        resp = client.get("/api/ml-ventas-ops/sales/kpis", headers=auth_headers)
        assert resp.status_code == 403

    def test_flag_off_with_permission_is_503(self, client, admin_auth_headers, db, rol_admin, monkeypatch):
        _grant_ml_ops_ver(db, rol_admin)
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        resp = client.get("/api/ml-ventas-ops/sales/kpis", headers=admin_auth_headers)
        assert resp.status_code == 503


class TestBasicAggregation:
    def test_sums_over_the_stored_metrics(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 1, total_amount=1000)
        _stored_metrics(db, 1, neto=Decimal("800.00"), total_gauss=Decimal("200.00"))
        db.commit()

        body = client.get(
            "/api/ml-ventas-ops/sales/kpis",
            params={"include_unknown": "true"},
            headers=admin_auth_headers,
        ).json()

        assert body["orders_count"] == 1
        assert body["groups_count"] == 1
        assert body["gross_billed_ars"] == pytest.approx(1000.0)
        assert body["neto_sum"] == pytest.approx(800.0)
        assert body["total_gauss_sum"] == pytest.approx(200.0)

    def test_recalculating_and_pending_are_excluded_and_reported(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 1, total_amount=100)
        _stored_metrics(db, 1)
        _seed_dirty(db, 1, attempts=0)  # recalculating
        _seed_order(db, 2, total_amount=100)  # pending: no metrics row
        db.commit()

        body = client.get(
            "/api/ml-ventas-ops/sales/kpis",
            params={"include_unknown": "true"},
            headers=admin_auth_headers,
        ).json()

        assert body["recalculating_count"] == 1
        assert body["pending_count"] == 1
        assert body["orders_count"] == 0
        assert body["gross_billed_ars"] == pytest.approx(0.0)


class TestExcludedByToggle:
    def test_off_toggle_reports_how_many_it_hides(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        # No shipment -> goods_status 'unknown' -> "A revisar" class.
        _seed_order(db, 1, shipping_status=None)
        _stored_metrics(db, 1)
        db.commit()

        body = client.get(
            "/api/ml-ventas-ops/sales/kpis",
            params={"include_unknown": "false"},
            headers=admin_auth_headers,
        ).json()

        assert body["orders_count"] == 0
        assert body["excluded_by_toggle"]["a_revisar"] == 1
        # The other toggles are ON, so they exclude nothing.
        assert body["excluded_by_toggle"]["en_disputa"] == 0
        assert body["excluded_by_toggle"]["mixta"] == 0
        assert body["excluded_by_toggle"]["provisorio"] == 0

    def test_on_toggle_never_reports_an_exclusion(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 1, shipping_status=None)
        _stored_metrics(db, 1)
        db.commit()

        body = client.get(
            "/api/ml-ventas-ops/sales/kpis",
            params={"include_unknown": "true"},
            headers=admin_auth_headers,
        ).json()
        assert body["excluded_by_toggle"]["a_revisar"] == 0


class TestNoShippingTagIncludedByDefault:
    """K0 (product decision): a pickup / 'acordar con el vendedor' sale is
    tagged `no_shipping` by ML and has no `ml_shipments_ops` row. It is a
    REAL sale, not a doubtful one -- it must be included in the KPI sums
    with the DEFAULT switches (no `include_unknown` override), while a
    genuinely unknown order (no shipment, no tag) stays excluded."""

    def test_no_shipping_tagged_sale_included_with_default_switches(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 1, shipping_status=None, total_amount=1234, has_no_shipping_tag=True)
        _stored_metrics(db, 1)
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales/kpis", headers=admin_auth_headers).json()

        assert body["orders_count"] == 1
        assert body["gross_billed_ars"] == pytest.approx(1234.0)
        assert body["excluded_by_toggle"]["a_revisar"] == 0

    def test_genuinely_unknown_sale_still_excluded_with_default_switches(
        self, db, client, admin_auth_headers, rol_admin
    ):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 1, shipping_status=None, total_amount=1234, has_no_shipping_tag=False)
        _stored_metrics(db, 1)
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales/kpis", headers=admin_auth_headers).json()

        assert body["orders_count"] == 0
        assert body["gross_billed_ars"] == pytest.approx(0.0)
        assert body["excluded_by_toggle"]["a_revisar"] == 1


class TestExplicitFacetOverridesSwitch:
    """K2: an explicit `operation_status`/`goods_status` filter must win
    over the toggle that would otherwise hide it, and the response must
    echo the switch it ACTUALLY applied (design D12 "response echoes
    effective switches")."""

    def test_explicit_operation_status_unknown_overrides_a_revisar_off(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 1, status="pending_payment", shipping_status=None, total_amount=500)
        _stored_metrics(db, 1)
        db.commit()

        body = client.get(
            "/api/ml-ventas-ops/sales/kpis",
            params={"operation_status": "unknown", "include_unknown": "false"},
            headers=admin_auth_headers,
        ).json()

        assert body["orders_count"] == 1
        assert body["effective_switches"]["include_unknown"] is True

    def test_explicit_operation_status_in_dispute_overrides_en_disputa_off(
        self, db, client, admin_auth_headers, rol_admin
    ):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 1, status="paid", payment_status="in_mediation", shipping_status="delivered", total_amount=500)
        _stored_metrics(db, 1)
        db.commit()

        body = client.get(
            "/api/ml-ventas-ops/sales/kpis",
            params={"operation_status": "in_dispute", "include_in_dispute": "false"},
            headers=admin_auth_headers,
        ).json()

        assert body["orders_count"] == 1
        assert body["effective_switches"]["include_in_dispute"] is True


class TestExcludedByToggleQueryShape:
    """K3: the per-toggle excluded counts must not re-run the whole scope
    once per toggle -- computed here in a single aggregate query (plus the
    unavoidable `build_scope` call already shared with the main
    aggregation), never one full query execution per OFF toggle."""

    def test_bounded_query_count_regardless_of_how_many_toggles_are_off(
        self, db, client, admin_auth_headers, rol_admin, query_counter
    ):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 1, shipping_status=None, total_amount=100)  # unknown
        _seed_order(db, 2, status="paid", payment_status="in_mediation", shipping_status="delivered")  # in dispute
        _stored_metrics(db, 1)
        _stored_metrics(db, 2)
        db.commit()

        with query_counter() as counter:
            resp = client.get(
                "/api/ml-ventas-ops/sales/kpis",
                # Every switch OFF: worst case for the old N-queries-per-
                # toggle implementation (would have run 5 full scope
                # queries just for the excluded-count computation).
                params={
                    "include_unknown": "false",
                    "include_in_dispute": "false",
                    "include_mixed": "false",
                    "include_provisional": "false",
                },
                headers=admin_auth_headers,
            )
        assert resp.status_code == 200
        # Bounded regardless of toggle state: order rows + metrics state +
        # stored metrics + worker heartbeat + ONE excluded-counts
        # aggregate, never scaling with the number of OFF toggles.
        assert counter.total <= 10, f"Too many queries ({counter.total}): suspected per-toggle scope re-run."


class TestWorkerAlive:
    def test_no_heartbeat_row_is_not_alive(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        db.commit()
        body = client.get(
            "/api/ml-ventas-ops/sales/kpis", params={"include_unknown": "true"}, headers=admin_auth_headers
        ).json()
        assert body["worker_alive"] is False

    def test_fresh_heartbeat_is_alive(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        db.add(WorkerJobState(name="worker", state="running", heartbeat_at=datetime.now(timezone.utc)))
        db.commit()
        body = client.get(
            "/api/ml-ventas-ops/sales/kpis", params={"include_unknown": "true"}, headers=admin_auth_headers
        ).json()
        assert body["worker_alive"] is True


class TestUrlParamRoundTrip:
    """PR11.T9: toggle state round-trips through URL query params (KPI
    R12). Echoed back in `effective_switches` (design D12 "response echoes
    effective switches")."""

    def test_every_switch_combination_is_echoed_back(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        db.commit()
        params = {
            "include_unknown": "true",
            "include_in_dispute": "false",
            "include_mixed": "false",
            "include_provisional": "true",
        }
        body = client.get("/api/ml-ventas-ops/sales/kpis", params=params, headers=admin_auth_headers).json()
        assert body["effective_switches"] == {
            "include_unknown": True,
            "include_in_dispute": False,
            "include_mixed": False,
            "include_provisional": True,
        }

    def test_defaults_match_spec_r11_when_omitted(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        db.commit()
        body = client.get("/api/ml-ventas-ops/sales/kpis", headers=admin_auth_headers).json()
        assert body["effective_switches"] == {
            "include_unknown": False,
            "include_in_dispute": False,
            "include_mixed": True,
            "include_provisional": True,
        }


class TestKpiListingParity:
    """PR11.T8 -- the load-bearing test. Six lone orders (one order == one
    group, so group/order counts line up 1:1), spanning every doubtful
    class plus one recalculating and one pending, checked against several
    switch combinations, a search term, and a product facet."""

    def _seed_fixture_set(self, db):
        # 1: known/ok -- always visible.
        _seed_order(db, 1, shipping_status="delivered", buyer_nickname="comprador_normal")
        _stored_metrics(db, 1, gauss_status="ok")
        # 2: unknown (no shipment) -- "A revisar" class.
        _seed_order(db, 2, shipping_status=None)
        _stored_metrics(db, 2, gauss_status="ok")
        # 3: in dispute.
        _seed_order(db, 3, shipping_status="delivered", payment_status="in_mediation")
        _stored_metrics(db, 3, gauss_status="ok")
        # 4: provisional gauss status.
        _seed_order(db, 4, shipping_status="delivered")
        _stored_metrics(db, 4, gauss_status="provisional")
        # 5: recalculating (dirty row, not parked).
        _seed_order(db, 5, shipping_status="delivered")
        _stored_metrics(db, 5, gauss_status="ok")
        _seed_dirty(db, 5, attempts=0)
        # 6: pending (no metrics row at all).
        _seed_order(db, 6, shipping_status="delivered")
        db.commit()

    def _expected_orders_count(self, include_unknown, include_in_dispute, include_mixed, include_provisional):
        """Independently derives, from the fixture set's KNOWN classes
        above (never from re-reading `build_scope`/`aggregate.py`), which
        of orders 1-4 the given switch combination keeps. Orders 5/6 are
        NEVER counted here -- they are `recalculating`/`pending`, asserted
        separately."""
        count = 1  # order 1 always counts
        if include_unknown:
            count += 1  # order 2
        if include_in_dispute:
            count += 1  # order 3
        if include_provisional:
            count += 1  # order 4
        # No lone order in this fixture set is 'mixed' (that needs a pack);
        # `include_mixed` therefore never changes this count -- included in
        # every call below purely to vary the request shape.
        del include_mixed
        return count

    @pytest.mark.parametrize(
        "include_unknown,include_in_dispute,include_mixed,include_provisional",
        [
            (True, True, True, True),
            (False, False, True, True),
            (False, False, False, False),
            (True, False, True, False),
            (False, True, False, True),
        ],
    )
    def test_kpi_orders_count_matches_listing_total_minus_recalculating_and_pending(
        self,
        db,
        client,
        admin_auth_headers,
        rol_admin,
        include_unknown,
        include_in_dispute,
        include_mixed,
        include_provisional,
    ):
        _grant_ml_ops_ver(db, rol_admin)
        self._seed_fixture_set(db)

        params = {
            "include_unknown": str(include_unknown).lower(),
            "include_in_dispute": str(include_in_dispute).lower(),
            "include_mixed": str(include_mixed).lower(),
            "include_provisional": str(include_provisional).lower(),
        }
        kpi_body = client.get("/api/ml-ventas-ops/sales/kpis", params=params, headers=admin_auth_headers).json()
        listing_body = client.get("/api/ml-ventas-ops/sales", params=params, headers=admin_auth_headers).json()

        expected = self._expected_orders_count(include_unknown, include_in_dispute, include_mixed, include_provisional)
        assert kpi_body["orders_count"] == expected

        # Orders 5 (recalculating) and 6 (pending) match EVERY combination
        # above (none of the four switches touches them), so they are
        # always in the listing's total, on top of `expected`.
        assert listing_body["total"] == expected + 2
        assert (
            listing_body["total"]
            == kpi_body["orders_count"] + kpi_body["recalculating_count"] + kpi_body["pending_count"]
        )
        assert kpi_body["recalculating_count"] == 1
        assert kpi_body["pending_count"] == 1

    def test_parity_holds_with_a_search_term_active(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        self._seed_fixture_set(db)
        params = {
            "include_unknown": "true",
            "include_in_dispute": "true",
            "include_mixed": "true",
            "include_provisional": "true",
            "q": "comprador_normal",
        }
        kpi_body = client.get("/api/ml-ventas-ops/sales/kpis", params=params, headers=admin_auth_headers).json()
        listing_body = client.get("/api/ml-ventas-ops/sales", params=params, headers=admin_auth_headers).json()

        # Only order 1 has that buyer nickname.
        assert kpi_body["orders_count"] == 1
        assert listing_body["total"] == 1
        assert kpi_body["recalculating_count"] == 0
        assert kpi_body["pending_count"] == 0

    def test_parity_holds_with_a_non_empty_queue_and_all_switches_on(self, db, client, admin_auth_headers, rol_admin):
        """Design D9/D10, spec R14 -- a filter combination that shows
        EVERY doubtful case must still reconcile against the listing once
        `recalculating_count`/`pending_count` are added back."""
        _grant_ml_ops_ver(db, rol_admin)
        self._seed_fixture_set(db)
        params = {
            "include_unknown": "true",
            "include_in_dispute": "true",
            "include_mixed": "true",
            "include_provisional": "true",
        }
        kpi_body = client.get("/api/ml-ventas-ops/sales/kpis", params=params, headers=admin_auth_headers).json()
        listing_body = client.get("/api/ml-ventas-ops/sales", params=params, headers=admin_auth_headers).json()

        assert kpi_body["orders_count"] == 4
        assert kpi_body["recalculating_count"] == 1
        assert kpi_body["pending_count"] == 1
        assert listing_body["total"] == 6
        assert (
            listing_body["total"]
            == kpi_body["orders_count"] + kpi_body["recalculating_count"] + kpi_body["pending_count"]
        )
