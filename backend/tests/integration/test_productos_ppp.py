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
from app.models.item_cost_list_history import ItemCostListHistory
from app.models.producto import ProductoERP, ProductoPricing
from app.models.tipo_cambio import TipoCambio

# Force-register ERP stub models in Base.metadata (only imported inside
# endpoint function bodies otherwise) — mirrors test_productos_detail_envio.py.
import app.models.item_cost_list_history  # noqa: F401
import app.models.commercial_transaction  # noqa: F401
import app.models.tb_supplier  # noqa: F401
import app.models.precio_gremio_override  # noqa: F401 (only imported inside listar_productos_tienda otherwise)


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

    row = ItemCostListHistory(
        iclh_id=90101,
        coslis_id=1,
        item_id=p.item_id,
        iclh_price=85.0,
        iclh_price_aw=85.0,
        curr_id=1,
        iclh_cd=datetime(2026, 2, 14),
    )
    db.add(row)
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

    row = ItemCostListHistory(
        iclh_id=90001,
        coslis_id=1,
        item_id=p.item_id,
        iclh_price=8500.0,
        iclh_price_aw=8500.0,
        curr_id=1,
        iclh_cd=datetime(2026, 2, 14),
    )
    db.add(row)
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


@pytest.fixture()
def producto_con_ppp_usd(db) -> ProductoERP:
    """USD-costed product with a matching USD-denominated PPP row (reflects
    production reality — see `costo_ppp_service` module docstring's
    "Currency" section)."""
    p = ProductoERP(
        item_id=9103,
        codigo="TEST-PPP-USD",
        descripcion="Producto con PPP en USD",
        costo=10.0,
        moneda_costo="USD",
        iva=21.0,
        activo=True,
        envio=0.0,
    )
    db.add(p)
    db.flush()

    row = ItemCostListHistory(
        iclh_id=90002,
        coslis_id=1,
        item_id=p.item_id,
        iclh_price=8.5,
        iclh_price_aw=8.5,
        curr_id=2,
        iclh_cd=datetime(2026, 2, 14),
    )
    db.add(row)
    db.flush()
    return p


class TestPppDisplayMonedaMatchesMonedaCosto:
    """PPP cost is displayed in `producto_erp.moneda_costo`, never converted
    — see `costo_ppp_service` module docstring's "Currency" section for why."""

    def test_usd_moneda_costo_is_never_converted_for_display(self, client, auth_headers, db, producto_con_ppp_usd):
        db.add(TipoCambio(fecha=date.today(), moneda="USD", compra=1000.0, venta=1000.0))
        db.commit()

        response = client.get(f"/api/productos/{producto_con_ppp_usd.item_id}", headers=auth_headers)

        assert response.status_code == 200, response.text
        data = response.json()

        assert data["ppp"] is not None
        assert data["ppp"]["costo"] == 8.5  # own currency, untouched
        assert data["ppp"]["moneda"] == "USD"

    def test_ars_moneda_costo_is_labelled_ars(self, client, auth_headers, db, producto_con_ppp):
        db.add(TipoCambio(fecha=date.today(), moneda="USD", compra=1000.0, venta=1000.0))
        db.commit()

        response = client.get(f"/api/productos/{producto_con_ppp.item_id}", headers=auth_headers)

        assert response.status_code == 200, response.text
        data = response.json()

        assert data["ppp"]["costo"] == 8500.0
        assert data["ppp"]["moneda"] == "ARS"

    def test_usd_moneda_costo_display_unaffected_by_missing_exchange_rate(
        self, client, auth_headers, producto_con_ppp_usd
    ):
        """No TipoCambio row at all: display is unaffected either way, since
        it is never converted in the first place (only markups need the
        rate, and only when moneda_costo is not ARS — see
        TestClasicaMarkupFailsClosedOnMissingRate below)."""
        response = client.get(f"/api/productos/{producto_con_ppp_usd.item_id}", headers=auth_headers)

        assert response.status_code == 200, response.text
        data = response.json()

        assert data["ppp"]["costo"] == 8.5
        assert data["ppp"]["moneda"] == "USD"


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


class TestPvpKeyCorrespondsToDisplayedValue:
    """Fix-round finding: the listing endpoint (`GET /api/productos`) computes
    the PVP markups TWICE — once from `ProductoPricing.precio_pvp` (first
    pass, recorded under the base PPP key), then a SECOND time from the
    `PrecioML` table (a genuinely different source), which OVERWRITES the
    displayed `markup_pvp*` fields but used to record its PPP companion under
    a separate `_variant` key. The frontend reads the base key right next to
    the (second-pass, PrecioML-sourced) displayed value, so the PPP line
    never matched what the screen showed. The fix: the second pass must
    record under the SAME base key, so the PPP entry always describes the
    number the response actually returns.
    """

    def test_pvp_ppp_present_when_only_precio_ml_has_a_price(
        self, client, auth_headers, db, comision_fixtures, producto_con_ppp
    ):
        """Product with a PrecioML price but NO ProductoPricing.precio_pvp:
        a real markup_pvp is displayed, so the PPP line must NOT be missing."""
        from app.models.precio_ml import PrecioML

        _guard_incompatible_raw_sql(db)

        db.add(PrecioML(item_id=producto_con_ppp.item_id, pricelist_id=12, precio=20000.0))
        db.commit()

        response = client.get("/api/productos?page=1&page_size=10", headers=auth_headers)

        assert response.status_code == 200, response.text
        productos = response.json()["productos"]
        producto = next(p for p in productos if p["item_id"] == producto_con_ppp.item_id)

        assert producto["markup_pvp"] is not None, "PrecioML-sourced markup_pvp must be displayed"
        assert producto["ppp"] is not None
        assert "pvp_clasica" in producto["ppp"]["markups"], (
            "PPP line missing for a displayed markup_pvp that came from PrecioML "
            f"(indistinguishable from genuine no-data): {producto['ppp']['markups']}"
        )

    def test_pvp_ppp_matches_precio_ml_source_when_both_sources_present(
        self, client, auth_headers, db, comision_fixtures, producto_con_ppp
    ):
        """Product with BOTH a ProductoPricing.precio_pvp AND a PrecioML
        price: the response's displayed markup_pvp comes from PrecioML (the
        second pass overwrites it), so the PPP entry must correspond to the
        PrecioML-derived limpio, NOT the ProductoPricing one."""
        from app.models.precio_ml import PrecioML
        from app.services.pricing_calculator import (
            calcular_comision_ml_total,
            calcular_limpio,
            calcular_markup,
        )

        _guard_incompatible_raw_sql(db)

        pricing = ProductoPricing(item_id=producto_con_ppp.item_id, precio_pvp=15000.0)
        db.add(pricing)
        db.add(PrecioML(item_id=producto_con_ppp.item_id, pricelist_id=12, precio=20000.0))
        db.commit()

        response = client.get("/api/productos?page=1&page_size=10", headers=auth_headers)

        assert response.status_code == 200, response.text
        productos = response.json()["productos"]
        producto = next(p for p in productos if p["item_id"] == producto_con_ppp.item_id)

        # Expected value derived from the PrecioML price (20000.0), NOT the
        # ProductoPricing one (15000.0) — mirrors the second pass exactly.
        comisiones = calcular_comision_ml_total(20000.0, 12.0, producto_con_ppp.iva, db=db)
        limpio = calcular_limpio(20000.0, producto_con_ppp.iva, 0.0, comisiones["comision_total"], db=db)
        # The displayed markup_pvp is NOT rounded at its call site (only the
        # PPP-recorded companion is, via PppMarkups.record's percent=True path).
        expected_markup_pvp = calcular_markup(limpio, 10000.0) * 100

        assert producto["markup_pvp"] == pytest.approx(expected_markup_pvp)

        expected_ppp = round(calcular_markup(limpio, 8500.0) * 100, 2)
        assert producto["ppp"]["markups"]["pvp_clasica"] == pytest.approx(expected_ppp), (
            "PPP entry must correspond to the PrecioML-sourced (displayed) value, "
            f"not the ProductoPricing.precio_pvp one: {producto['ppp']['markups']}"
        )


class TestMejorOfertaKeyCorrespondsToDisplayedValue:
    """Same correspondence bug, different site: when a product participates
    in rebate and is out_of_cards, `mejor_oferta_markup` gets OVERWRITTEN to
    the rebate markup, but the `PPP_KEY_MEJOR_OFERTA` companion used to keep
    (or lack) the ORIGINAL mejor_oferta value/absence — a second source-vs-
    display mismatch of the same shape as the PVP one above."""

    def test_mejor_oferta_ppp_present_when_rebate_override_is_the_only_source(
        self, client, auth_headers, db, comision_fixtures
    ):
        """No real ML offer at all (no mejor_oferta/mejor_pub), but
        out_of_cards + rebate replicates a REAL displayed mejor_oferta_markup
        from the rebate — the PPP line must not be missing."""
        _guard_incompatible_raw_sql(db)

        p = ProductoERP(
            item_id=9401,
            codigo="TEST-PPP-MEJOR-OFERTA-REBATE",
            descripcion="Producto rebate out_of_cards",
            costo=10000.0,
            moneda_costo="ARS",
            iva=21.0,
            activo=True,
            envio=0.0,
        )
        db.add(p)
        db.flush()
        db.add(
            ProductoPricing(
                item_id=p.item_id,
                precio_lista_ml=15000.0,
                participa_rebate=True,
                porcentaje_rebate=3.8,
                out_of_cards=True,
            )
        )
        db.add(
            ItemCostListHistory(
                iclh_id=94011,
                coslis_id=1,
                item_id=p.item_id,
                iclh_price=8500.0,
                iclh_price_aw=8500.0,
                curr_id=1,
                iclh_cd=datetime(2026, 2, 14),
            )
        )
        db.commit()

        response = client.get("/api/productos?page=1&page_size=10", headers=auth_headers)

        assert response.status_code == 200, response.text
        productos = response.json()["productos"]
        producto = next(p2 for p2 in productos if p2["item_id"] == p.item_id)

        assert producto["mejor_oferta_markup"] is not None
        assert producto["ppp"] is not None
        assert "mejor_oferta" in producto["ppp"]["markups"], (
            "PPP line missing for a displayed mejor_oferta_markup sourced from the "
            f"rebate override: {producto['ppp']['markups']}"
        )
        # mejor_oferta is recorded with percent=False (decimal ratio, matching
        # the displayed mejor_oferta_markup convention), while rebate is
        # recorded with percent=True (the default, `*100` rounded) — compare
        # on a common percentage scale.
        # mejor_oferta (percent=False) keeps the raw unrounded ratio; rebate
        # (percent=True) is rounded to 2 decimals — compare with that
        # rounding applied instead of an implicit floating-point tolerance.
        assert round(producto["ppp"]["markups"]["mejor_oferta"] * 100, 2) == producto["ppp"]["markups"]["rebate"]


class TestQueryCount:
    """Exactly ONE PPP-resolver query fires per request, regardless of
    page_size — proven via a REAL SQL statement counter (before_cursor_execute),
    not by counting Python-level calls to the resolver wrapper."""

    def test_exactly_one_ppp_query_for_single_item_detail(self, client, auth_headers, producto_con_ppp, query_counter):
        with query_counter() as counter:
            response = client.get(f"/api/productos/{producto_con_ppp.item_id}", headers=auth_headers)

        assert response.status_code == 200, response.text
        assert counter.matching("tb_item_cost_list_history") == 1

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
                ItemCostListHistory(
                    iclh_id=90200 + i,
                    coslis_id=1,
                    item_id=item_id,
                    iclh_price=50.0 + i,
                    iclh_price_aw=50.0 + i,
                    curr_id=1,
                    iclh_cd=datetime(2026, 2, 14),
                )
            )
        db.commit()

        with query_counter() as counter:
            response = client.get(f"/api/productos?page=1&page_size={page_size}", headers=auth_headers)

        assert response.status_code == 200, response.text
        assert counter.matching("tb_item_cost_list_history") == 1


class TestClasicaMarkupFailsClosedOnMissingRate:
    """End-to-end regression for the fail-closed guard (a USD-costed product
    with NO `TipoCambio` row loaded for today) — see `costo_ppp_service`
    module docstring's "Currency" section for the full mechanism/rationale.
    Expected: `ppp.costo`/`ppp.moneda` still shown, `clasica` ABSENT from
    `ppp.markups`."""

    def test_detail_endpoint_fails_closed_when_no_exchange_rate_is_available(
        self, client, auth_headers, db, comision_fixtures, producto_con_ppp_usd
    ):
        db.add(ProductoPricing(item_id=producto_con_ppp_usd.item_id, precio_lista_ml=15000.0))
        db.commit()

        response = client.get(f"/api/productos/{producto_con_ppp_usd.item_id}", headers=auth_headers)

        assert response.status_code == 200, response.text
        data = response.json()

        assert data["ppp"] is not None
        assert data["ppp"]["costo"] == 8.5  # display unaffected by the missing rate
        assert data["ppp"]["moneda"] == "USD"
        assert "clasica" not in data["ppp"]["markups"], (
            f"markup must be absent (fail-closed), not fabricated: {data['ppp']['markups']}"
        )
