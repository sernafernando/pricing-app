"""`seller_sku_anterior`: the SKU an item was sold with, exposed ONLY when it differs from the current one.

Ventas ML always shows the current SKU (`seller_sku`); when MercadoLibre changed it after the sale
the old one is shown as "ex <SKU>". Null when equal or unknown.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps

from .test_ml_ventas_ops_router import _grant_ml_ops_ver
from .test_ml_ventas_ops_sales_router import _group_holding, _seed_order


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


def _item(db, order_id: int, *, item_id="MLA1", sku="1215", vendido="1214") -> None:
    db.add(
        MlOrderItemOps(
            order_id=order_id,
            item_id=item_id,
            seller_sku=sku,
            seller_sku_vendido=vendido,
            quantity=1,
            unit_price=100,
        )
    )


CASES = [
    pytest.param("1215", "1214", "1214", id="changed-after-the-sale"),
    pytest.param("1215", "1215", None, id="unchanged"),
    pytest.param("1215", None, None, id="unknown-sold-sku"),
    pytest.param(None, "1214", "1214", id="current-sku-removed"),
]


class TestOrderDetail:
    @pytest.mark.parametrize(("sku", "vendido", "expected"), CASES)
    def test_items_and_breakdown_lines_expose_the_old_sku_only_when_it_differs(
        self, db, client, admin_auth_headers, rol_admin, sku, vendido, expected
    ) -> None:
        order_id = 96001
        db.add(
            MlOrdersOps(
                order_id=order_id,
                status="paid",
                ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
                seller_id=999,
            )
        )
        _item(db, order_id, sku=sku, vendido=vendido)
        db.commit()
        _grant_ml_ops_ver(db, rol_admin)

        body = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers).json()

        assert body["items"][0]["seller_sku"] == sku
        assert body["items"][0]["seller_sku_anterior"] == expected
        assert "seller_sku_vendido" not in body["items"][0]
        assert body["breakdown"]["item_lines"][0]["seller_sku"] == sku
        assert body["breakdown"]["item_lines"][0]["seller_sku_anterior"] == expected


class TestSalesListing:
    def test_listing_items_expose_the_old_sku(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 96002
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _item(db, order_id)
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        item = _group_holding(body, order_id)["orders"][0]["items"][0]
        assert (item["seller_sku"], item["seller_sku_anterior"]) == ("1215", "1214")


class TestPack:
    def test_pack_item_lines_expose_the_old_sku(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 96003
        _seed_order(db, order_id, pack_id=96100, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _item(db, order_id)
        db.commit()

        body = client.get("/api/ml-ventas-ops/packs/96100", headers=admin_auth_headers).json()

        line = body["item_lines"][0]
        assert (line["seller_sku"], line["seller_sku_anterior"]) == ("1215", "1214")
