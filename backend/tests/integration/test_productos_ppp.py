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

from datetime import date, datetime

import pytest

from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.item_transaction import ItemTransaction
from app.models.producto import ProductoERP, ProductoPricing

# Force-register ERP stub models in Base.metadata (only imported inside
# endpoint function bodies otherwise) — mirrors test_productos_detail_envio.py.
import app.models.item_transaction  # noqa: F401
import app.models.commercial_transaction  # noqa: F401
import app.models.tb_supplier  # noqa: F401


def _guard_incompatible_raw_sql(db):
    """Stub the two Postgres-only `= ANY(:ids)` raw-SQL lookups (Tienda Nube
    prices, ML catalog status) that `listar_productos`/`listar_productos_tienda`
    always run when the result set is non-empty. These are unrelated legacy
    features that are genuinely incompatible with the SQLite test DB (SQLite
    has no `ANY` function) — see the `TestListingParityDefaultLayer` docstring
    in test_productos_colors_read_layer.py, which already documented this gap
    for the listing endpoint. Every other statement (ORM-generated or raw)
    passes through to the real connection unmodified, so the actual code path
    under test — including the PPP batch resolver — still runs for real."""
    original_execute = db.execute

    class _EmptyResult:
        def fetchall(self):
            return []

    def _wrapped(statement, *args, **kwargs):
        sql_text = str(statement)
        if "tienda_nube_productos" in sql_text or "v_ml_catalog_status_latest" in sql_text:
            return _EmptyResult()
        return original_execute(statement, *args, **kwargs)

    db.execute = _wrapped


@pytest.fixture()
def comision_fixtures(db):
    """Minimal commission fixtures so `_lookup_comision` resolves for grupo 1
    (GRUPO_DEFAULT) — reused pattern from test_pricing_envio_routing.py."""
    version = ComisionVersion(nombre="Test", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=12.0))
    db.flush()
    return version


@pytest.fixture()
def producto_con_todas_las_cuotas(db, comision_fixtures) -> ProductoERP:
    """Product with all 4 classic-installment prices set, plus a qualifying
    PPP row — drives the listing endpoint's `cuota_clasica_{n}` loop
    across its 4 iterations (fix-round finding 1)."""
    p = ProductoERP(
        item_id=9201,
        codigo="TEST-PPP-CUOTAS",
        descripcion="Producto con todas las cuotas",
        costo=100.0,
        moneda_costo="ARS",
        iva=21.0,
        activo=True,
        envio=0.0,
    )
    db.add(p)
    db.flush()

    pricing = ProductoPricing(
        item_id=p.item_id,
        precio_lista_ml=1400.0,
        precio_3_cuotas=1500.0,
        precio_6_cuotas=1600.0,
        precio_9_cuotas=1700.0,
        precio_12_cuotas=1800.0,
    )
    db.add(pricing)

    txn = ItemTransaction(
        it_transaction=90101,
        ct_transaction=1,
        item_id=p.item_id,
        it_priceofcostpp=85.0,
        it_cancelled=False,
        it_exchangetobranchcurrency=1.0,
        rmah_id=None,
        it_isrmasuppliercreditnote=False,
        it_cd=datetime(2026, 2, 14),
    )
    db.add(txn)
    db.flush()
    return p


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


class TestClasicaMarkupPpp:
    """T2.6 (reopened): the clásica (list-cost) markup gets its own PPP
    companion, computed in-request with the same inputs the batch
    (`recalcular_markups_service.py`) uses, WITHOUT touching the displayed
    `markup` field (still fed from the stored `markup_calculado` column)."""

    def test_clasica_ppp_markup_matches_calcular_markup_of_limpio_and_costo_ppp(
        self, client, auth_headers, db, comision_fixtures, producto_con_ppp
    ):
        from app.services.pricing_calculator import (
            calcular_comision_ml_total,
            calcular_limpio,
            calcular_markup,
        )

        pricing = ProductoPricing(item_id=producto_con_ppp.item_id, precio_lista_ml=15000.0)
        db.add(pricing)
        db.commit()

        response = client.get(f"/api/productos/{producto_con_ppp.item_id}", headers=auth_headers)

        assert response.status_code == 200, response.text
        data = response.json()

        assert data["ppp"] is not None
        assert "clasica" in data["ppp"]["markups"], data["ppp"]["markups"]

        # Recompute the expected value the same way the endpoint should:
        # comision_base=12.0 (grupo 1, comision_fixtures), envio=0 (producto_con_ppp).
        comisiones = calcular_comision_ml_total(15000.0, 12.0, producto_con_ppp.iva, db=db)
        limpio = calcular_limpio(15000.0, producto_con_ppp.iva, 0.0, comisiones["comision_total"], db=db)
        expected = round(calcular_markup(limpio, 8500.0) * 100, 2)

        assert data["ppp"]["markups"]["clasica"] == expected

        # The displayed markup is untouched — still None because markup_calculado
        # was never written (that column is fed by a separate batch process).
        assert data["markup"] is None

    def test_clasica_ppp_markup_absent_when_precio_lista_ml_is_missing(self, client, auth_headers, producto_con_ppp):
        """No `precio_lista_ml` => no clásica limpio to derive from => no key,
        NEVER a fabricated value."""
        response = client.get(f"/api/productos/{producto_con_ppp.item_id}", headers=auth_headers)

        assert response.status_code == 200, response.text
        data = response.json()

        assert data["ppp"] is not None
        assert "clasica" not in data["ppp"]["markups"]


class TestDistinctInstalmentKeys:
    """Fix-round finding 1: the 4 classic-installment markups must be DISTINCT.

    Before the fix, `ppp.record("calculado", limpio_cuota)` used the SAME
    fixed key across all 4 `cuotas_config` iterations (3/6/9/12 cuotas), so
    each iteration silently overwrote the previous one — only the 12-cuotas
    markup survived. This exercises the real `/api/productos` listing
    endpoint (the only one with the classic — non-PVP — cuotas loop) with a
    product that has all 4 installment prices set, and asserts all 4 keys
    are present and hold different values.
    """

    def test_all_four_instalment_markups_present_and_distinct(
        self, client, auth_headers, db, producto_con_todas_las_cuotas
    ):
        _guard_incompatible_raw_sql(db)

        response = client.get("/api/productos?page=1&page_size=10", headers=auth_headers)

        assert response.status_code == 200, response.text
        productos = response.json()["productos"]
        producto = next(p for p in productos if p["item_id"] == producto_con_todas_las_cuotas.item_id)

        assert producto["ppp"] is not None
        markups = producto["ppp"]["markups"]

        instalment_keys = ["cuota_clasica_3", "cuota_clasica_6", "cuota_clasica_9", "cuota_clasica_12"]
        for key in instalment_keys:
            assert key in markups, f"missing {key} in {markups}"

        values = [markups[key] for key in instalment_keys]
        assert len(set(values)) == len(values), f"instalment markups collapsed onto a shared key: {markups}"

        # The clásica (list-cost) markup also gets a PPP companion on this
        # same listing pass, reusing the same _lookup_comision(4, grupo_id)
        # dict lookup — no extra query.
        assert "clasica" in markups, f"missing clasica in {markups}"


class TestQueryCount:
    """Exactly ONE PPP-resolver query fires per request, regardless of
    page_size — proven via a REAL SQL statement counter (before_cursor_execute),
    not by counting Python-level calls to the resolver wrapper."""

    def test_exactly_one_ppp_query_for_single_item_detail(self, client, auth_headers, producto_con_ppp, query_counter):
        with query_counter() as counter:
            response = client.get(f"/api/productos/{producto_con_ppp.item_id}", headers=auth_headers)

        assert response.status_code == 200, response.text
        assert counter.matching("tb_item_transactions") == 1

    @pytest.mark.parametrize("page_size", [1, 100])
    def test_exactly_one_ppp_query_on_paginated_list_regardless_of_page_size(
        self, client, auth_headers, db, comision_fixtures, query_counter, page_size
    ):
        """Real SQL-count proof against the PAGINATED LIST endpoint
        (`GET /api/productos`), closing the coverage gap: the prior version of
        this test only exercised the single-item detail endpoint, which calls
        the resolver once by construction and can never reveal an N+1.

        The list endpoint's Tienda Nube batch price lookup uses a raw
        `= ANY(:ids)` query that only PostgreSQL supports; `_guard_incompatible_raw_sql`
        stubs ONLY that literal statement (and the equally Postgres-only ML
        catalog-status lookup) to an empty result so the endpoint's real code
        path — including the actual PPP batch resolver call we're counting —
        still executes end-to-end against the real SQLite test DB.
        """
        _guard_incompatible_raw_sql(db)

        for i in range(3):
            item_id = 9300 + i
            p = ProductoERP(
                item_id=item_id,
                codigo=f"TEST-PPP-LIST-{item_id}",
                descripcion="Producto listado",
                costo=100.0,
                moneda_costo="ARS",
                iva=21.0,
                activo=True,
                envio=0.0,
            )
            db.add(p)
            db.flush()
            db.add(
                ItemTransaction(
                    it_transaction=90200 + i,
                    ct_transaction=1,
                    item_id=item_id,
                    it_priceofcostpp=50.0 + i,
                    it_cancelled=False,
                    it_exchangetobranchcurrency=1.0,
                    rmah_id=None,
                    it_isrmasuppliercreditnote=False,
                    it_cd=datetime(2026, 2, 14),
                )
            )
        db.commit()

        with query_counter() as counter:
            response = client.get(f"/api/productos?page=1&page_size={page_size}", headers=auth_headers)

        assert response.status_code == 200, response.text
        assert counter.matching("tb_item_transactions") == 1
