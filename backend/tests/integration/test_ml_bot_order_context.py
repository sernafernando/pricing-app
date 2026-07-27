"""
Integration tests — `GET /api/ml-bot/messages/order-context`.

Operator need: deciding whether the bot's draft makes sense requires knowing
what the buyer actually bought and where the shipment is. Both live in the ML
order tables keyed by `pack_id`; the Mensajes panel had neither.

Batched on purpose: the panel renders many threads at once, so a per-thread
endpoint would be an N+1 against three joined tables on every list render.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models.mercadolibre_order_detail import MercadoLibreOrderDetail
from app.models.mercadolibre_order_header import MercadoLibreOrderHeader
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping

BASE = "/api/ml-bot"


@pytest.fixture
def con_todos_los_permisos():
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=True),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


@pytest.fixture
def sin_permisos():
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=False),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


def _seed_order(
    db,
    *,
    mlo_id: int,
    pack_id: str,
    titles: list[str],
    shipping_status: str | None = "shipped",
    substatus: str | None = "in_transit",
) -> None:
    db.add(
        MercadoLibreOrderHeader(
            mlo_id=mlo_id,
            ml_pack_id=pack_id,
            mlo_status="paid",
            mlo_total_paid_amount=12345.67,
            ml_date_created=datetime(2026, 7, 20, 10, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None),
        )
    )
    for index, title in enumerate(titles):
        db.add(
            MercadoLibreOrderDetail(
                mlod_id=mlo_id * 100 + index,
                mlo_id=mlo_id,
                mlo_title=title,
                mlo_quantity=2,
                mlo_unit_price=1000,
                mlo_currency_id="ARS",
            )
        )
    if shipping_status is not None:
        db.add(
            MercadoLibreOrderShipping(
                mlm_id=mlo_id * 10,
                mlo_id=mlo_id,
                mlstatus=shipping_status,
                mlsubstatus=substatus,
                mllogistic_type="fulfillment",
            )
        )
    db.flush()


class TestPermission:
    def test_sin_permiso_403(self, client, auth_headers, db, sin_permisos) -> None:
        r = client.get(f"{BASE}/messages/order-context", params={"pack_ids": "1"}, headers=auth_headers)
        assert r.status_code == 403


class TestOrderContext:
    def test_returns_items_and_shipping_for_a_pack(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        _seed_order(db, mlo_id=5001, pack_id="PACK-A", titles=["Router TP-Link AX55"])
        db.commit()

        r = client.get(f"{BASE}/messages/order-context", params={"pack_ids": "PACK-A"}, headers=auth_headers)
        assert r.status_code == 200

        ctx = r.json()["contexts"]["PACK-A"]
        assert ctx["items"][0]["title"] == "Router TP-Link AX55"
        assert ctx["items"][0]["quantity"] == 2
        assert ctx["order_status"] == "paid"
        assert ctx["shipping"]["status"] == "shipped"
        assert ctx["shipping"]["substatus"] == "in_transit"

    def test_batches_several_packs_in_one_call(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        _seed_order(db, mlo_id=5002, pack_id="PACK-B", titles=["Switch 8p"])
        _seed_order(db, mlo_id=5003, pack_id="PACK-C", titles=["Access Point"])
        db.commit()

        r = client.get(f"{BASE}/messages/order-context", params={"pack_ids": "PACK-B,PACK-C"}, headers=auth_headers)
        assert r.status_code == 200
        assert set(r.json()["contexts"]) == {"PACK-B", "PACK-C"}

    def test_pack_grouping_several_orders_merges_their_items(
        self, client, auth_headers, db, con_todos_los_permisos
    ) -> None:
        """A pack IS a group of orders — both orders' items must show up, or
        the operator sees half of what the buyer bought."""
        _seed_order(db, mlo_id=5004, pack_id="PACK-D", titles=["Cable UTP"])
        _seed_order(db, mlo_id=5005, pack_id="PACK-D", titles=["Ficha RJ45"], shipping_status=None)
        db.commit()

        r = client.get(f"{BASE}/messages/order-context", params={"pack_ids": "PACK-D"}, headers=auth_headers)
        assert r.status_code == 200
        titles = sorted(item["title"] for item in r.json()["contexts"]["PACK-D"]["items"])
        assert titles == ["Cable UTP", "Ficha RJ45"]

    def test_unknown_pack_is_simply_absent(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        """Not an error: plenty of threads have no matching order (test packs,
        deleted orders). The panel just renders nothing for those."""
        r = client.get(f"{BASE}/messages/order-context", params={"pack_ids": "NOPE"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["contexts"] == {}

    def test_order_without_shipping_row_returns_null_shipping(
        self, client, auth_headers, db, con_todos_los_permisos
    ) -> None:
        _seed_order(db, mlo_id=5006, pack_id="PACK-E", titles=["Antena"], shipping_status=None)
        db.commit()

        r = client.get(f"{BASE}/messages/order-context", params={"pack_ids": "PACK-E"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["contexts"]["PACK-E"]["shipping"] is None

    def test_empty_pack_ids_returns_empty_without_querying(
        self, client, auth_headers, db, con_todos_los_permisos
    ) -> None:
        r = client.get(f"{BASE}/messages/order-context", params={"pack_ids": ""}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["contexts"] == {}

    def test_batch_size_is_capped(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        """Guards the endpoint against an unbounded IN (...) built from
        client-supplied input."""
        r = client.get(
            f"{BASE}/messages/order-context",
            params={"pack_ids": ",".join(str(n) for n in range(300))},
            headers=auth_headers,
        )
        assert r.status_code == 422


class TestPackWithSeveralOrdersIsDeterministic:
    def test_shipping_comes_from_the_newest_order_not_row_order(
        self, client, auth_headers, db, con_todos_los_permisos
    ) -> None:
        """Two orders in one pack, both shipped. Without an explicit ordering
        the status shown would depend on whatever Postgres returned first and
        could flip between refreshes."""
        _seed_order(db, mlo_id=6001, pack_id="PACK-F", titles=["Viejo"], shipping_status="delivered")
        _seed_order(
            db, mlo_id=6002, pack_id="PACK-F", titles=["Nuevo"], shipping_status="ready_to_ship", substatus="printed"
        )
        db.commit()

        seen = set()
        for _ in range(3):
            r = client.get(f"{BASE}/messages/order-context", params={"pack_ids": "PACK-F"}, headers=auth_headers)
            assert r.status_code == 200
            seen.add(r.json()["contexts"]["PACK-F"]["shipping"]["status"])

        assert seen == {"ready_to_ship"}, "must always resolve to the newest order's shipping"

    def test_total_paid_sums_every_order_in_the_pack(self, client, auth_headers, db, con_todos_los_permisos) -> None:
        _seed_order(db, mlo_id=6003, pack_id="PACK-G", titles=["A"])
        _seed_order(db, mlo_id=6004, pack_id="PACK-G", titles=["B"], shipping_status=None)
        db.commit()

        r = client.get(f"{BASE}/messages/order-context", params={"pack_ids": "PACK-G"}, headers=auth_headers)
        assert r.status_code == 200
        # 12345.67 seeded per order.
        assert r.json()["contexts"]["PACK-G"]["total_paid"] == pytest.approx(24691.34)
