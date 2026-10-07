"""The Flex "Bonificación por envío" as the sale detail serves it
(ventas-ml-bonificacion-envio-flex). Real capture of sale 2000018808335864.

ML pays it for the operation, so it is a line of the NETO section (ventas-ml-
bonificacion-en-neto), not of the Total Gauss chain. The line exposes its three
amounts SEPARATELY -- gross, net and IVA -- so the data can feed an IVA books
report later.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.config import settings
from app.models.ml_order_metrics import MlOrderMetrics
from app.services.order_metrics.store import recompute_order_metrics
from tests.services.ml_ventas_desglose._bonificacion_capture import ORDER_ID, seed_capture

from .test_ml_ventas_ops_router import _grant_ml_ops_ver


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


def _detail(db, client, admin_auth_headers, rol_admin, order_id=ORDER_ID) -> dict:
    _grant_ml_ops_ver(db, rol_admin)
    recompute_order_metrics(db, [order_id])
    db.commit()
    response = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers)
    assert response.status_code == 200
    return response.json()


class TestBonificacionEnvioInTheDetail:
    def test_the_line_is_inside_the_neto_section_with_gross_net_and_iva(
        self, db, client, admin_auth_headers, rol_admin
    ):
        seed_capture(db)

        body = _detail(db, client, admin_auth_headers, rol_admin)

        breakdown = body["breakdown"]
        linea = next(l for l in breakdown["lines"] if l["concepto"] == "Bonificación por envío")
        assert linea["origen"] == "bonificacion"
        # A negative charge: money ML pays, it ADDS to the neto.
        assert linea["monto"] == pytest.approx(-8990.00)
        assert linea["importe"] == {
            "bruto": pytest.approx(8990.00),
            "neto": pytest.approx(7429.75),
            "iva": pytest.approx(1560.25),
        }
        assert breakdown["neto"] == pytest.approx(13081.02 + 8990.00)
        assert breakdown["bonificacion_envio"] == pytest.approx(8990.00)
        assert breakdown["neto_depositado"] == pytest.approx(13024.45)
        assert breakdown["retenciones_recuperables"] == pytest.approx(56.57)

    def test_it_is_no_longer_a_link_of_the_total_gauss_chain(self, db, client, admin_auth_headers, rol_admin):
        """MUTATION: keeping the deduction as well as the neto counts it twice
        and moves Total Gauss off `neto_sin_iva - costo - flete`."""
        seed_capture(db)

        body = _detail(db, client, admin_auth_headers, rol_admin)

        cadena = body["cadena_total_gauss"]
        assert "bonificacion_envio" not in [l["code"] for l in cadena["lineas"]]
        neto_sin_iva = body["iva_decomposicion"]["neto_sin_iva"]
        assert neto_sin_iva == pytest.approx(10677.99 + 7429.75)
        restado = sum(l["monto"] for l in cadena["lineas"] if l["monto"] is not None)
        assert cadena["total_gauss"] == pytest.approx(neto_sin_iva - restado)
        assert cadena["total_gauss"] == pytest.approx(11107.74)  # what main produced

    def test_the_iva_component_is_real_and_the_split_reconciles(self, db, client, admin_auth_headers, rol_admin):
        seed_capture(db)

        body = _detail(db, client, admin_auth_headers, rol_admin)

        iva = body["iva_decomposicion"]
        componente = next(c for c in iva["componentes"] if c["concepto"] == "Bonificación por envío")
        assert componente["informativo"] is False
        assert (componente["bruto"], componente["base"], componente["iva"]) == pytest.approx((8990.0, 7429.75, 1560.25))
        assert iva["reconcilia"] is True
        assert iva["diferencia"] == pytest.approx(0)

    def test_other_lines_carry_no_importe(self, db, client, admin_auth_headers, rol_admin):
        seed_capture(db)

        body = _detail(db, client, admin_auth_headers, rol_admin)

        otras = [l for l in body["breakdown"]["lines"] if l["origen"] != "bonificacion"]
        assert otras and all(l["importe"] is None for l in otras)

    def test_a_non_flex_sale_with_the_same_discounts_shows_no_line(self, db, client, admin_auth_headers, rol_admin):
        seed_capture(db, logistic_type="cross_docking")

        body = _detail(db, client, admin_auth_headers, rol_admin)

        assert "Bonificación por envío" not in [l["concepto"] for l in body["breakdown"]["lines"]]
        assert "Bonificación por envío" not in [c["concepto"] for c in body["iva_decomposicion"]["componentes"]]
        assert body["breakdown"]["bonificacion_envio"] == 0


class TestBonificacionEnvioInTheListing:
    def test_the_row_neto_includes_it_and_the_tooltip_figures_add_up_to_it(
        self, db, client, admin_auth_headers, rol_admin
    ):
        seed_capture(db)
        _grant_ml_ops_ver(db, rol_admin)
        recompute_order_metrics(db, [ORDER_ID])
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()
        sale = next(g for g in body["sales"] if any(o["order_id"] == ORDER_ID for o in g["orders"]))
        order = sale["orders"][0]

        for row in (order, sale):
            assert row["neto"] == pytest.approx(13081.02 + 8990.00)
            assert row["neto_depositado"] == pytest.approx(13024.45)
            assert row["retenciones_recuperables"] == pytest.approx(56.57)
            assert row["bonificacion_envio"] == pytest.approx(8990.00)
            assert row["neto_depositado"] + row["retenciones_recuperables"] + row["bonificacion_envio"] == (
                pytest.approx(row["neto"])
            )
        assert order["total_gauss"] == pytest.approx(11107.74)

    def test_a_negative_remainder_from_a_stale_row_is_unknown_not_negative(
        self, db, client, admin_auth_headers, rol_admin
    ):
        seed_capture(db)
        _grant_ml_ops_ver(db, rol_admin)
        recompute_order_metrics(db, [ORDER_ID])
        stored = db.query(MlOrderMetrics).filter_by(order_id=ORDER_ID).one()
        stored.neto = Decimal("100.00")  # lower than the live payments
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()
        order = next(g for g in body["sales"] if any(o["order_id"] == ORDER_ID for o in g["orders"]))["orders"][0]

        assert order["bonificacion_envio"] is None

    def test_a_row_waiting_for_its_recompute_does_not_explain_its_neto(self, db, client, admin_auth_headers, rol_admin):
        """Only a settled row can say what its neto is made of: a dirty row's
        stored neto may be older than the live payments."""
        from app.models.ml_order_metrics import MlOrderMetricsDirty

        seed_capture(db)
        _grant_ml_ops_ver(db, rol_admin)
        recompute_order_metrics(db, [ORDER_ID])
        db.add(MlOrderMetricsDirty(order_id=ORDER_ID, reason="payment changed", attempts=0))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()
        order = next(g for g in body["sales"] if any(o["order_id"] == ORDER_ID for o in g["orders"]))["orders"][0]

        assert order["metrics_state"] == "recalculating"
        assert order["bonificacion_envio"] is None

    def test_a_settled_sale_without_bonificacion_reports_zero(self, db, client, admin_auth_headers, rol_admin):
        seed_capture(db, logistic_type="cross_docking")
        _grant_ml_ops_ver(db, rol_admin)
        recompute_order_metrics(db, [ORDER_ID])
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()
        sale = next(g for g in body["sales"] if any(o["order_id"] == ORDER_ID for o in g["orders"]))

        assert sale["orders"][0]["bonificacion_envio"] == 0
        assert sale["bonificacion_envio"] == 0

    def test_a_cents_drift_between_the_stored_neto_and_the_payments_is_unknown_not_a_bonificacion(
        self, db, client, admin_auth_headers, rol_admin
    ):
        seed_capture(db, logistic_type="cross_docking")
        _grant_ml_ops_ver(db, rol_admin)
        recompute_order_metrics(db, [ORDER_ID])
        stored = db.query(MlOrderMetrics).filter_by(order_id=ORDER_ID).one()
        stored.neto = stored.neto + Decimal("0.01")
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()
        order = next(g for g in body["sales"] if any(o["order_id"] == ORDER_ID for o in g["orders"]))["orders"][0]

        assert order["bonificacion_envio"] is None

    def test_a_row_stored_before_the_change_does_not_claim_a_bonificacion_its_neto_lacks(
        self, db, client, admin_auth_headers, rol_admin
    ):
        """A Flex row stored under formula 3 has the neto WITHOUT the
        bonificación while the live resolver already finds it."""
        seed_capture(db)
        _grant_ml_ops_ver(db, rol_admin)
        recompute_order_metrics(db, [ORDER_ID])
        stored = db.query(MlOrderMetrics).filter_by(order_id=ORDER_ID).one()
        stored.neto = stored.neto - Decimal("8990")
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()
        order = next(g for g in body["sales"] if any(o["order_id"] == ORDER_ID for o in g["orders"]))["orders"][0]

        assert order["bonificacion_envio"] is None
