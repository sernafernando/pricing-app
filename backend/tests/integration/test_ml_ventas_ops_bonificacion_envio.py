"""The Flex "Bonificación por envío" as the sale detail serves it
(ventas-ml-bonificacion-envio-flex). Real capture of sale 2000018808335864.

The line exposes its three amounts SEPARATELY -- gross, net and IVA -- so the
data can feed an IVA books report later. Only the NET enters the Total Gauss;
the IVA is informational and never an expense.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
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
    def test_the_line_exposes_gross_net_and_iva_as_separate_fields(self, db, client, admin_auth_headers, rol_admin):
        seed_capture(db)

        body = _detail(db, client, admin_auth_headers, rol_admin)

        linea = next(l for l in body["cadena_total_gauss"]["lineas"] if l["code"] == "bonificacion_envio")
        assert linea["concepto"] == "Bonificación por envío"
        assert linea["importe"] == {
            "bruto": pytest.approx(8990.00),
            "neto": pytest.approx(7429.75),
            "iva": pytest.approx(1560.25),
        }
        # Only the NET enters the chain (negative: income adds).
        assert linea["monto"] == pytest.approx(-7429.75)

    def test_the_iva_is_informational_and_never_reduces_total_gauss(self, db, client, admin_auth_headers, rol_admin):
        """MUTATION: subtracting `iva` anywhere in the chain moves Total
        Gauss off `neto_sin_iva - costo - flete + 7429,75`."""
        seed_capture(db)

        body = _detail(db, client, admin_auth_headers, rol_admin)

        cadena = body["cadena_total_gauss"]
        neto_sin_iva = body["iva_decomposicion"]["neto_sin_iva"]
        restado = sum(l["monto"] for l in cadena["lineas"] if l["monto"] is not None)
        assert cadena["total_gauss"] == pytest.approx(neto_sin_iva - restado)
        componente = next(
            c for c in body["iva_decomposicion"]["componentes"] if c["concepto"] == "Bonificación por envío"
        )
        assert componente["informativo"] is True
        assert (componente["bruto"], componente["base"], componente["iva"]) == pytest.approx((8990.0, 7429.75, 1560.25))

    def test_lines_without_a_breakdown_carry_no_importe(self, db, client, admin_auth_headers, rol_admin):
        seed_capture(db)

        body = _detail(db, client, admin_auth_headers, rol_admin)

        otras = [l for l in body["cadena_total_gauss"]["lineas"] if l["code"] != "bonificacion_envio"]
        assert otras and all(l["importe"] is None for l in otras)

    def test_a_non_flex_sale_with_the_same_discounts_shows_no_line(self, db, client, admin_auth_headers, rol_admin):
        seed_capture(db, logistic_type="cross_docking")

        body = _detail(db, client, admin_auth_headers, rol_admin)

        assert "bonificacion_envio" not in [l["code"] for l in body["cadena_total_gauss"]["lineas"]]
        assert "Bonificación por envío" not in [c["concepto"] for c in body["iva_decomposicion"]["componentes"]]
