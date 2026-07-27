"""
Integration tests for PPP (ERP weighted-average cost) surfaced on the
Productos detail endpoint (`GET /api/productos/{item_id}`, `obtener_producto`).

Spec coverage (openspec/changes/productos-costo-ppp/specs.md):
  - Golden no-regression: every pre-existing field is unaffected; the only
    diff between "no qualifying PPP row" and "qualifying PPP row" responses
    is the new `ppp` key.
  - No-data contract: `ppp` is `None` when there is no qualifying row, and no
    emitted value equals `costo` (never a fallback).
  - Query-count: exactly ONE PPP-resolver query fires per request, regardless
    of how many item_ids would be involved in a batch call.

These tests exercise the REAL endpoint via the FastAPI TestClient against the
in-memory SQLite test DB — this is also the environment that proves the
resolver's window-function query (not `DISTINCT ON`) works outside Postgres.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.models.item_transaction import ItemTransaction
from app.models.producto import ProductoERP

# Force-register ERP stub models in Base.metadata (only imported inside
# endpoint function bodies otherwise) — mirrors test_productos_detail_envio.py.
import app.models.item_transaction  # noqa: F401
import app.models.commercial_transaction  # noqa: F401
import app.models.tb_supplier  # noqa: F401


@pytest.fixture()
def producto_sin_ppp(db) -> ProductoERP:
    p = ProductoERP(
        item_id=9101,
        codigo="TEST-PPP-NODATA",
        descripcion="Producto sin PPP",
        costo=10000,
        moneda_costo="ARS",
        iva=21.0,
        activo=True,
        envio=0.0,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def producto_con_ppp(db) -> ProductoERP:
    p = ProductoERP(
        item_id=9102,
        codigo="TEST-PPP-DATA",
        descripcion="Producto con PPP",
        costo=10000,
        moneda_costo="ARS",
        iva=21.0,
        activo=True,
        envio=0.0,
    )
    db.add(p)
    db.flush()

    txn = ItemTransaction(
        it_transaction=90001,
        ct_transaction=1,
        item_id=p.item_id,
        it_priceofcostpp=8500.0,
        it_cancelled=False,
        it_exchangetobranchcurrency=1.0,
        rmah_id=None,
        it_isrmasuppliercreditnote=False,
        it_cd=datetime(2026, 2, 14),
    )
    db.add(txn)
    db.flush()
    return p


class TestNoDataGoldenNoRegression:
    """A product with no qualifying PPP row must diff by nothing but `ppp`."""

    def test_no_ppp_row_returns_null_ppp_and_no_costo_fallback(self, client, auth_headers, producto_sin_ppp):
        response = client.get(f"/api/productos/{producto_sin_ppp.item_id}", headers=auth_headers)

        assert response.status_code == 200, response.text
        data = response.json()

        assert data["ppp"] is None
        assert data["costo"] == 10000.0  # pre-existing field untouched
        assert data["markup_pvp"] is None  # unrelated to ppp — no PPP-derived leakage

    def test_no_ppp_row_response_matches_baseline_except_ppp_key(self, client, auth_headers, producto_sin_ppp):
        """Golden diff: strip `ppp` and compare against the pre-PPP field set."""
        response = client.get(f"/api/productos/{producto_sin_ppp.item_id}", headers=auth_headers)
        data = response.json()

        pre_existing_keys = {k for k in data.keys() if k != "ppp"}
        expected_pre_existing_keys = {
            "item_id",
            "codigo",
            "descripcion",
            "marca",
            "categoria",
            "subcategoria_id",
            "moneda_costo",
            "costo",
            "costo_ars",
            "iva",
            "stock",
            "precio_lista_ml",
            "markup",
            "usuario_modifico",
            "fecha_modificacion",
            "tiene_precio",
            "necesita_revision",
            "participa_rebate",
            "porcentaje_rebate",
            "precio_rebate",
            "markup_rebate",
            "participa_web_transferencia",
            "porcentaje_markup_web",
            "precio_web_transferencia",
            "markup_web_real",
            "preservar_porcentaje_web",
            "mejor_oferta_precio",
            "mejor_oferta_monto_rebate",
            "mejor_oferta_pvp_seller",
            "mejor_oferta_markup",
            "mejor_oferta_porcentaje_rebate",
            "mejor_oferta_fecha_hasta",
            "out_of_cards",
            "color_marcado",
            "color_hint_global",
            "color_hint_equipo_inicial",
            "precio_3_cuotas",
            "precio_6_cuotas",
            "precio_9_cuotas",
            "precio_12_cuotas",
            "markup_3_cuotas",
            "markup_6_cuotas",
            "markup_9_cuotas",
            "markup_12_cuotas",
            "precio_pvp",
            "precio_pvp_3_cuotas",
            "precio_pvp_6_cuotas",
            "precio_pvp_9_cuotas",
            "precio_pvp_12_cuotas",
            "markup_pvp",
            "markup_pvp_3_cuotas",
            "markup_pvp_6_cuotas",
            "markup_pvp_9_cuotas",
            "markup_pvp_12_cuotas",
            "recalcular_cuotas_auto",
            "markup_adicional_cuotas_custom",
            "markup_adicional_cuotas_pvp_custom",
            "catalog_status",
            "has_catalog",
            "catalog_price_to_win",
            "catalog_winner_price",
            "tn_price",
            "tn_promotional_price",
            "tn_has_promotion",
        }

        assert pre_existing_keys == expected_pre_existing_keys


class TestQualifyingRowSurfacesPpp:
    def test_qualifying_row_returns_ppp_cost_and_date(self, client, auth_headers, producto_con_ppp):
        response = client.get(f"/api/productos/{producto_con_ppp.item_id}", headers=auth_headers)

        assert response.status_code == 200, response.text
        data = response.json()

        assert data["ppp"] is not None
        assert data["ppp"]["costo"] == 8500.0
        assert data["ppp"]["fecha"] == "2026-02-14"
        # costo (list-cost) is untouched by the presence of PPP
        assert data["costo"] == 10000.0


class TestQueryCount:
    """Exactly one PPP-resolver query fires per request (no N+1)."""

    def test_exactly_one_ppp_query_for_single_item_detail(self, client, auth_headers, producto_con_ppp, monkeypatch):
        import app.api.endpoints.productos_listing as listing_module

        call_count = {"n": 0}
        original = listing_module.resolver_ppp_batch

        def _counting_resolver(db, item_ids):
            call_count["n"] += 1
            return original(db, item_ids)

        monkeypatch.setattr(listing_module, "resolver_ppp_batch", _counting_resolver)

        response = client.get(f"/api/productos/{producto_con_ppp.item_id}", headers=auth_headers)

        assert response.status_code == 200, response.text
        assert call_count["n"] == 1
