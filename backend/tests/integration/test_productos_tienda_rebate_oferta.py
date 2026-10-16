"""`GET /api/productos/tienda` (`listar_productos_tienda`): rebate and best
offer, pinned BEFORE the tienda listing moved to the shared computation
(`app.services.productos_pricing_view`) the Productos listing and the product
detail use.

Characterization, not a spec: the expected values below were recorded on the
tienda listing's own copy of the computation, and the refactor must reproduce
them exactly (floats compared by repr), with the same number of statements.
The catalogue is the listing golden's (rebate with grupo-average, ERP and real
shipping, USD cost, default grupo, an active offer) plus an out-of-cards
product whose rebate replaces its offer, with a PPP cost on the rebate and
offer products so their PPP markups are pinned too.
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
    _FETCH_LIST_COST,
    _FUTURE,
    _PAST,
    _producto,
    _seed_catalogue,
    _seed_pricing_base,
)
from tests.integration.test_productos_tienda_orden import _guard_incompatible_raw_sql

# Force-register ERP stub models (only imported inside endpoint bodies otherwise).
import app.models.item_cost_list_history  # noqa: F401,E402
import app.models.commercial_transaction  # noqa: F401,E402
import app.models.tb_supplier  # noqa: F401,E402
import app.models.precio_gremio_override  # noqa: F401,E402

KEYS = (
    "precio_rebate",
    "markup_rebate",
    "mejor_oferta_precio",
    "mejor_oferta_monto_rebate",
    "mejor_oferta_pvp_seller",
    "mejor_oferta_markup",
    "mejor_oferta_porcentaje_rebate",
    "mejor_oferta_fecha_hasta",
)
PPP_KEYS = ("rebate", "mejor_oferta")
OUT_OF_CARDS_ITEM = 8


@pytest.fixture()
def seeded(db):
    _seed_pricing_base(db, with_commission_version=True)
    _seed_catalogue(db)
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
    for iclh_id, item_id, price in ((90001, 1, 9000.0), (90005, 5, 6500.0), (90008, OUT_OF_CARDS_ITEM, 8000.0)):
        db.add(
            ItemCostListHistory(
                iclh_id=iclh_id,
                coslis_id=1,
                item_id=item_id,
                iclh_price=price,
                iclh_price_aw=price,
                curr_id=1,
                iclh_cd=datetime(2026, 2, 14),
            )
        )
    db.commit()
    _guard_incompatible_raw_sql(db)
    return db


def _tienda(client, auth_headers) -> dict:
    with patch(_FETCH_LIST_COST, return_value={"MLA5": 1234.5}):
        response = client.get("/api/productos/tienda?page=1&page_size=50", headers=auth_headers)
    assert response.status_code == 200, response.text
    return json.loads(response.text)


def _rebate_oferta(data: dict) -> dict:
    """The pinned slice of each row: rebate, best offer and their PPP markups."""
    out = {}
    for row in data["productos"]:
        markups = (row.get("ppp") or {}).get("markups") or {}
        out[str(row["item_id"])] = {
            **{key: row[key] for key in KEYS},
            "ppp": {key: markups.get(key) for key in PPP_KEYS},
        }
    return out


# Recorded on the unrefactored tienda listing (JSON text: floats keep their repr).
RECORDED_ROWS = json.loads(
    """
{
 "1": {
  "markup_rebate": null,
  "mejor_oferta_fecha_hasta": "2099-12-31",
  "mejor_oferta_markup": 0.22479338842975194,
  "mejor_oferta_monto_rebate": 3000.0,
  "mejor_oferta_porcentaje_rebate": 14.29,
  "mejor_oferta_precio": 18000.0,
  "mejor_oferta_pvp_seller": 21000.0,
  "ppp": {
   "mejor_oferta": 0.3608815426997243,
   "rebate": null
  },
  "precio_rebate": null
 },
 "2": {
  "markup_rebate": 100.49483685847322,
  "mejor_oferta_fecha_hasta": null,
  "mejor_oferta_markup": null,
  "mejor_oferta_monto_rebate": null,
  "mejor_oferta_porcentaje_rebate": null,
  "mejor_oferta_precio": null,
  "mejor_oferta_pvp_seller": null,
  "ppp": {
   "mejor_oferta": null,
   "rebate": null
  },
  "precio_rebate": 62370.06237006237
 },
 "3": {
  "markup_rebate": 431.245167608804,
  "mejor_oferta_fecha_hasta": null,
  "mejor_oferta_markup": null,
  "mejor_oferta_monto_rebate": null,
  "mejor_oferta_porcentaje_rebate": null,
  "mejor_oferta_precio": null,
  "mejor_oferta_pvp_seller": null,
  "ppp": {
   "mejor_oferta": null,
   "rebate": null
  },
  "precio_rebate": 41580.04158004158
 },
 "4": {
  "markup_rebate": 270.762529853439,
  "mejor_oferta_fecha_hasta": null,
  "mejor_oferta_markup": null,
  "mejor_oferta_monto_rebate": null,
  "mejor_oferta_porcentaje_rebate": null,
  "mejor_oferta_precio": null,
  "mejor_oferta_pvp_seller": null,
  "ppp": {
   "mejor_oferta": null,
   "rebate": null
  },
  "precio_rebate": 46777.54677754678
 },
 "5": {
  "markup_rebate": 157.99586163222529,
  "mejor_oferta_fecha_hasta": null,
  "mejor_oferta_markup": null,
  "mejor_oferta_monto_rebate": null,
  "mejor_oferta_porcentaje_rebate": null,
  "mejor_oferta_precio": null,
  "mejor_oferta_pvp_seller": null,
  "ppp": {
   "mejor_oferta": null,
   "rebate": 177.84
  },
  "precio_rebate": 31185.031185031185
 },
 "6": {
  "markup_rebate": null,
  "mejor_oferta_fecha_hasta": null,
  "mejor_oferta_markup": null,
  "mejor_oferta_monto_rebate": null,
  "mejor_oferta_porcentaje_rebate": null,
  "mejor_oferta_precio": null,
  "mejor_oferta_pvp_seller": null,
  "ppp": {
   "mejor_oferta": null,
   "rebate": null
  },
  "precio_rebate": null
 },
 "7": {
  "markup_rebate": null,
  "mejor_oferta_fecha_hasta": null,
  "mejor_oferta_markup": null,
  "mejor_oferta_monto_rebate": null,
  "mejor_oferta_porcentaje_rebate": null,
  "mejor_oferta_precio": null,
  "mejor_oferta_pvp_seller": null,
  "ppp": {
   "mejor_oferta": null,
   "rebate": null
  },
  "precio_rebate": null
 },
 "8": {
  "markup_rebate": 71.60504567203134,
  "mejor_oferta_fecha_hasta": null,
  "mejor_oferta_markup": 0.7160504567203134,
  "mejor_oferta_monto_rebate": null,
  "mejor_oferta_porcentaje_rebate": null,
  "mejor_oferta_precio": 26315.78947368421,
  "mejor_oferta_pvp_seller": 26315.78947368421,
  "ppp": {
   "mejor_oferta": 0.9305567638103525,
   "rebate": 93.06
  },
  "precio_rebate": 26315.78947368421
 }
}
"""
)
# Statements the tienda listing issued for this catalogue, recorded alongside.
RECORDED_STATEMENTS = 26


def _snapshot() -> dict:
    return {"rows": RECORDED_ROWS, "statements": RECORDED_STATEMENTS}


class TestTiendaRebateOfertaCharacterization:
    def test_matches_the_recorded_values(self, client, auth_headers, seeded) -> None:
        produced = json.dumps(_rebate_oferta(_tienda(client, auth_headers)), sort_keys=True, indent=1) + "\n"
        assert produced == json.dumps(_snapshot()["rows"], sort_keys=True, indent=1) + "\n"

    def test_the_snapshot_is_not_vacuous(self) -> None:
        rows = _snapshot()["rows"]
        assert len(rows) == 8
        assert rows["1"]["mejor_oferta_markup"] is not None
        assert rows["1"]["ppp"]["mejor_oferta"] is not None
        assert rows["5"]["markup_rebate"] is not None
        assert rows["5"]["ppp"]["rebate"] is not None
        for item_id in ("2", "3", "4"):
            assert rows[item_id]["markup_rebate"] is not None
        out_of_cards = rows[str(OUT_OF_CARDS_ITEM)]
        assert out_of_cards["mejor_oferta_precio"] == out_of_cards["precio_rebate"]
        assert out_of_cards["mejor_oferta_fecha_hasta"] is None

    def test_statement_count_is_unchanged(self, client, auth_headers, seeded, query_counter) -> None:
        with query_counter() as counter:
            _tienda(client, auth_headers)
        assert counter.total == _snapshot()["statements"]
