"""`GET /api/productos/{item_id}` (`obtener_producto`) returns the rebate price,
the rebate markup and the best current offer exactly as the Productos listing
does for the same product.

The detail used to hard-code `precio_rebate`, `markup_rebate` and every
`mejor_oferta_*` field to None. The Publicaciones ML "Precios" tab reads this
endpoint and must show what Productos shows, so both endpoints now run the
same shared computation (`app.services.productos_pricing_view`).

The catalogue is the listing golden's (rebate with grupo-average, ERP and real
shipping, USD cost, default grupo, an active offer) plus one out-of-cards
product, where the rebate replaces the offer. The listing's values for that
product are pinned below (characterization recorded on the unrefactored
listing); the golden snapshot pins the rest.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from app.models.item_cost_list_history import ItemCostListHistory
from app.models.oferta_ml import OfertaML
from app.models.producto import ProductoPricing
from app.models.publicacion_ml import PublicacionML
from tests.integration.test_productos_listing_golden import (
    _FUTURE,
    _PAST,
    _FETCH_LIST_COST,
    _patch_postgres_only_sql,
    _producto,
    _seed_catalogue,
    _seed_pricing_base,
)

# Force-register ERP stub models (only imported inside endpoint bodies otherwise),
# as test_producto_detail_cuota_markups.py does.
import app.models.item_cost_list_history  # noqa: F401,E402
import app.models.commercial_transaction  # noqa: F401,E402
import app.models.tb_supplier  # noqa: F401,E402

REBATE_OFERTA_KEYS = (
    "precio_rebate",
    "markup_rebate",
    "mejor_oferta_precio",
    "mejor_oferta_monto_rebate",
    "mejor_oferta_pvp_seller",
    "mejor_oferta_markup",
    "mejor_oferta_porcentaje_rebate",
    "mejor_oferta_fecha_hasta",
)

OUT_OF_CARDS_ITEM = 8


@pytest.fixture(autouse=True)
def _ventas_ve_productos(grant_permiso, rol_ventas):
    """GET /productos/{item_id} and GET /productos require productos.ver."""
    grant_permiso(rol_ventas, "productos.ver")


@pytest.fixture()
def seeded(db):
    _seed_pricing_base(db, with_commission_version=True)
    _seed_catalogue(db)
    # 8: out of cards with a rebate AND an active offer: the rebate wins.
    db.add(_producto(OUT_OF_CARDS_ITEM, costo=9000.0, moneda="ARS", subcat=100, envio=0.0))
    db.flush()
    db.add(
        ProductoPricing(
            item_id=OUT_OF_CARDS_ITEM,
            precio_lista_ml=25000.0,
            markup_calculado=20.0,
            participa_rebate=True,
            porcentaje_rebate=5.0,
            out_of_cards=True,
            fecha_modificacion=datetime(2026, 1, 1, 12, 0, 0),
        )
    )
    db.add(PublicacionML(mla="MLA8", item_id=OUT_OF_CARDS_ITEM, pricelist_id=4, activo=True))
    db.flush()
    db.add(
        OfertaML(
            mla="MLA8",
            fecha_desde=_PAST,
            fecha_hasta=_FUTURE,
            precio_final=22000.0,
            pvp_seller=24000.0,
            aporte_meli_pesos=2000.0,
            aporte_meli_porcentaje=8.33,
        )
    )
    db.commit()
    _patch_postgres_only_sql(db)
    return db


def _json(response) -> dict:
    assert response.status_code == 200, response.text
    # Round-trip through text so floats compare by repr, like the golden.
    return json.loads(response.text)


def _listing_rows(client, auth_headers) -> dict[int, dict]:
    with patch(_FETCH_LIST_COST, return_value={"MLA5": 1234.5}):
        data = _json(client.get("/api/productos?page=1&page_size=50", headers=auth_headers))
    return {row["item_id"]: row for row in data["productos"]}


def _detail(client, auth_headers, item_id) -> dict:
    with patch(_FETCH_LIST_COST, return_value={"MLA5": 1234.5}):
        return _json(client.get(f"/api/productos/{item_id}", headers=auth_headers))


class TestListingCharacterization:
    """What the listing returns for the out-of-cards product. Recorded before
    the computation was moved to a shared service; it must not move."""

    def test_out_of_cards_rebate_replaces_the_offer(self, client, auth_headers, seeded) -> None:
        row = _listing_rows(client, auth_headers)[OUT_OF_CARDS_ITEM]

        assert row["precio_rebate"] == 26315.78947368421
        assert row["markup_rebate"] == 71.60504567203134
        assert row["mejor_oferta_precio"] == row["precio_rebate"]
        assert row["mejor_oferta_pvp_seller"] == row["precio_rebate"]
        assert row["mejor_oferta_markup"] == row["markup_rebate"] / 100
        assert row["mejor_oferta_monto_rebate"] is None
        assert row["mejor_oferta_porcentaje_rebate"] is None
        assert row["mejor_oferta_fecha_hasta"] is None


class TestDetailMatchesListing:
    @pytest.mark.parametrize("item_id", [1, 2, 3, 4, 5, 6, 7, OUT_OF_CARDS_ITEM])
    def test_rebate_and_best_offer_fields_are_the_listings(self, client, auth_headers, seeded, item_id) -> None:
        row = _listing_rows(client, auth_headers)[item_id]
        detail = _detail(client, auth_headers, item_id)

        assert {key: detail[key] for key in REBATE_OFERTA_KEYS} == {key: row[key] for key in REBATE_OFERTA_KEYS}

    def test_the_seed_exercises_rebate_offer_and_out_of_cards(self, client, auth_headers, seeded) -> None:
        """Guard against a vacuous comparison: the detail returns real values."""
        detail_offer = _detail(client, auth_headers, 1)
        detail_rebate = _detail(client, auth_headers, 5)
        detail_out_of_cards = _detail(client, auth_headers, OUT_OF_CARDS_ITEM)

        assert detail_offer["mejor_oferta_precio"] == 18000.0
        assert detail_offer["mejor_oferta_markup"] is not None
        assert detail_rebate["precio_rebate"] is not None
        assert detail_rebate["markup_rebate"] is not None
        assert detail_out_of_cards["mejor_oferta_precio"] == detail_out_of_cards["precio_rebate"]

    def test_detail_ppp_records_the_rebate_and_offer_like_the_listing(self, client, auth_headers, seeded) -> None:
        seeded.add(
            ItemCostListHistory(
                iclh_id=80001,
                coslis_id=1,
                item_id=OUT_OF_CARDS_ITEM,
                iclh_price=8000.0,
                iclh_price_aw=8000.0,
                curr_id=1,
                iclh_cd=datetime(2026, 2, 14),
            )
        )
        seeded.flush()

        row = _listing_rows(client, auth_headers)[OUT_OF_CARDS_ITEM]
        detail = _detail(client, auth_headers, OUT_OF_CARDS_ITEM)

        assert {"rebate", "mejor_oferta"} <= set(row["ppp"]["markups"])
        assert detail["ppp"]["markups"] == row["ppp"]["markups"]
