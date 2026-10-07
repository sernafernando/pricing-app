"""The "% de varios" base as the sale detail serves it
(ventas-ml-varios-base-envio). Real captures of the buyer's shipping.

The shipping the buyer paid is exposed as gross / net / IVA (the same shape
as the Flex bonificación) so it can feed an IVA books report later; the IVA is
informational and never an expense.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.config import settings
from app.models.varios_venta_pct import VariosVentaPct
from app.services.order_metrics.store import recompute_order_metrics
from tests.services.ml_ventas_desglose._envio_comprador_capture import (
    FULFILLMENT_990,
    SELF_SERVICE_PACK,
    seed_case,
)

from .test_ml_ventas_ops_router import _grant_ml_ops_ver


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


def _detail(db, client, admin_auth_headers, rol_admin, order_id) -> dict:
    _grant_ml_ops_ver(db, rol_admin)
    recompute_order_metrics(db, [order_id])
    db.commit()
    response = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers)
    assert response.status_code == 200
    return response.json()


class TestTheBaseInTheDetail:
    def test_the_buyers_shipping_is_exposed_gross_net_and_iva_next_to_the_base(
        self, db, client, admin_auth_headers, rol_admin
    ):
        seed_case(db, FULFILLMENT_990)

        iva = _detail(db, client, admin_auth_headers, rol_admin, FULFILLMENT_990)["iva_decomposicion"]

        assert iva["envio_comprador"] == {
            "bruto": pytest.approx(990.00),
            "neto": pytest.approx(818.18),
            "iva": pytest.approx(171.82),
        }
        assert iva["base_venta_sin_iva"] == pytest.approx(15165.29)  # the goods, untouched
        assert iva["base_varios"] == pytest.approx(15165.29 + 818.18)

    def test_the_flex_pack_has_no_buyer_shipping_and_the_base_adds_the_599(
        self, db, client, admin_auth_headers, rol_admin
    ):
        seed_case(db, SELF_SERVICE_PACK)

        iva = _detail(db, client, admin_auth_headers, rol_admin, SELF_SERVICE_PACK)["iva_decomposicion"]

        assert iva["envio_comprador"] is None
        assert iva["base_varios"] == pytest.approx(87601.65 + 495.04)

    def test_the_varios_line_is_the_percentage_of_that_base(self, db, client, admin_auth_headers, rol_admin):
        seed_case(db, FULFILLMENT_990)
        db.add(VariosVentaPct(porcentaje=Decimal("2.00"), fecha_desde=date(2026, 1, 1), fecha_hasta=None))
        db.commit()

        body = _detail(db, client, admin_auth_headers, rol_admin, FULFILLMENT_990)

        varios = next(linea for linea in body["cadena_total_gauss"]["lineas"] if linea["code"] == "varios")
        assert varios["monto"] == pytest.approx(319.67)
