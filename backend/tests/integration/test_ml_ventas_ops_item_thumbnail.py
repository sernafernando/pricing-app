"""`thumbnail_url`: the first stored photo of the MLA an item sold, for Ventas ML's row and panels.

The sale's `item_id` IS the MLA: the photo is read from what the publication store keeps for it (`ml_items`), the
first picture's secure URL, else its URL, else the store's `thumbnail`. Null when the MLA has no stored photo (or the
store never read it), so the UI keeps its placeholder. Never downloaded: the stored URL as is.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest
from sqlalchemy import event

from app.core.config import settings
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.ml_publications import MlItem

from .test_ml_ventas_ops_router import _grant_ml_ops_ver
from .test_ml_ventas_ops_sales_router import _group_holding, _seed_order

PHOTO = "https://http2.mlstatic.com/D_NQ_NP_1-O.jpg"


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


def _item(db, order_id: int, item_id: str) -> None:
    db.add(MlOrderItemOps(order_id=order_id, item_id=item_id, seller_sku="1215", quantity=1, unit_price=100))


def _publication(db, item_id: str, *, pictures=None, thumbnail=None) -> None:
    raw = {"id": item_id} if pictures is None else {"id": item_id, "pictures": pictures}
    db.add(MlItem(item_id=item_id, raw=raw, thumbnail=thumbnail))


PHOTO_CASES = [
    pytest.param(
        {"pictures": [{"secure_url": PHOTO, "url": "http://x/1.jpg"}, {"secure_url": "https://x/2.jpg"}]},
        PHOTO,
        id="first-secure-url",
    ),
    pytest.param({"pictures": [{"url": PHOTO}]}, PHOTO, id="plain-url-without-a-secure-one"),
    pytest.param({"pictures": [], "thumbnail": PHOTO}, PHOTO, id="no-pictures-the-store-thumbnail"),
    pytest.param({"pictures": [{"secure_url": "", "url": PHOTO}]}, PHOTO, id="empty-secure-url-falls-back"),
    pytest.param(
        {"pictures": [{"secure_url": "", "url": ""}], "thumbnail": PHOTO}, PHOTO, id="empty-urls-the-thumbnail"
    ),
    pytest.param({"pictures": None, "thumbnail": None}, None, id="no-stored-photo"),
]


class TestSalesListing:
    @pytest.mark.parametrize(("stored", "expected"), PHOTO_CASES)
    def test_each_item_carries_the_first_stored_photo_of_its_mla(
        self, db, client, admin_auth_headers, rol_admin, stored, expected
    ) -> None:
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 97001
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _item(db, order_id, "MLA970001")
        _publication(db, "MLA970001", **stored)
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        assert _group_holding(body, order_id)["orders"][0]["items"][0]["thumbnail_url"] == expected

    def test_an_mla_the_store_never_read_has_no_photo(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 97002
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _item(db, order_id, "MLA970002")
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        assert _group_holding(body, order_id)["orders"][0]["items"][0]["thumbnail_url"] is None

    def test_the_photos_of_a_whole_page_are_read_in_one_query(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant_ml_ops_ver(db, rol_admin)
        for n in range(3):
            order_id = 97010 + n
            _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
            _item(db, order_id, f"MLA97001{n}")
            _publication(db, f"MLA97001{n}", pictures=[{"secure_url": f"https://x/{n}.jpg"}])
        db.commit()
        statements = []

        def count(_conn, _cursor, statement, *_args):
            if re.search(r"\bFROM ml_items\b", statement):
                statements.append(statement)

        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", count)
        try:
            body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()
        finally:
            event.remove(engine, "before_cursor_execute", count)

        photos = {o["items"][0]["thumbnail_url"] for g in body["sales"] for o in g["orders"] if o["items"]}
        assert {"https://x/0.jpg", "https://x/1.jpg", "https://x/2.jpg"} <= photos
        assert len(statements) == 1


class TestOrderDetail:
    def test_the_panel_items_carry_the_photo_and_an_mla_without_one_none(
        self, db, client, admin_auth_headers, rol_admin
    ) -> None:
        order_id = 97020
        db.add(
            MlOrdersOps(
                order_id=order_id,
                status="paid",
                ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
                seller_id=999,
            )
        )
        _item(db, order_id, "MLA970201")
        _item(db, order_id, "MLA970202")
        _publication(db, "MLA970201", pictures=[{"secure_url": PHOTO}])
        db.commit()
        _grant_ml_ops_ver(db, rol_admin)

        body = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers).json()

        assert [i["thumbnail_url"] for i in body["items"]] == [PHOTO, None]

    def test_the_breakdown_lines_carry_the_same_photos(self, db, client, admin_auth_headers, rol_admin) -> None:
        # One line model for every breakdown: its `thumbnail_url` means the same in the order's breakdown as in a pack's.
        order_id = 97021
        db.add(
            MlOrdersOps(
                order_id=order_id,
                status="paid",
                ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
                seller_id=999,
            )
        )
        _item(db, order_id, "MLA970211")
        _item(db, order_id, "MLA970212")
        _publication(db, "MLA970211", pictures=[{"secure_url": PHOTO}])
        db.commit()
        _grant_ml_ops_ver(db, rol_admin)

        body = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers).json()

        lines = {line["item_id"]: line["thumbnail_url"] for line in body["breakdown"]["item_lines"]}
        assert lines == {"MLA970211": PHOTO, "MLA970212": None}


class TestPack:
    def test_the_pack_item_lines_carry_the_photo(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 97030
        _seed_order(db, order_id, pack_id=97100, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _item(db, order_id, "MLA970301")
        _publication(db, "MLA970301", pictures=[{"secure_url": PHOTO}])
        db.commit()

        body = client.get("/api/ml-ventas-ops/packs/97100", headers=admin_auth_headers).json()

        assert body["item_lines"][0]["thumbnail_url"] == PHOTO
