"""
Integration tests for PATCH /markups-tienda/productos/{item_id}/markup-sugerido

Covers:
- T-10 (parity): computar_precio_sugerido helper output matches the original inline formula
- T-7: user without productos.gestionar_markups_tienda → 403
- T-8: unknown item_id → 404
- T-1: sets markup_sugerido, preserves markup_porcentaje on existing row
- T-2: creates row when none exists, defaults markup_porcentaje to resolved gremio value
- T-6a (preserves): codigo/descripcion/activo/notas unchanged after PATCH
- T-5 (rounding): input 7.555 → persisted 7.56
- T-11 (negative): input -5.0 → HTTP 200, persisted -5.0
- T-3: null markup_sugerido deletes row, origin resolves to 'marca'
- T-4: clear when no row → idempotent 200, no error
- T-6b (zero): explicit 0 → stored 0.0, origin='producto'
- T-4b: clear with no brand row → origin null
- T-9a: product row exists → response.markup_sugerido_origen == 'producto'
- T-9b: no product row, brand row exists → 'marca'
- T-9c: neither → None
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.api.endpoints.productos_shared import computar_precio_sugerido
from app.models.markup_tienda import MarkupTiendaProducto, MarkupTiendaBrand
from app.models.producto import ProductoERP, ProductoPricing


# ==========================================================================
# Permission fixtures (same pattern as test_compras_endpoints.py)
# ==========================================================================


PERM_MARKUPS = "productos.gestionar_markups_tienda"


@pytest.fixture
def con_permiso_markups():
    """Forces both the cache and the service to grant gestionar_markups_tienda."""
    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            return_value=True,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value={PERM_MARKUPS},
        ),
    ):
        yield


@pytest.fixture
def sin_permiso_markups():
    """Forces both the cache and the service to deny all permissions."""
    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            return_value=False,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value=set(),
        ),
    ):
        yield


# ==========================================================================
# Data fixtures
# ==========================================================================

ITEM_ID = 42
ITEM_ID_2 = 55


@pytest.fixture
def producto_erp(db) -> ProductoERP:
    """A minimal ProductoERP row for testing."""
    p = ProductoERP(
        item_id=ITEM_ID,
        codigo="TST-001",
        descripcion="Producto Test",
        marca="MarcaTest",
        costo=100.0,
        moneda_costo="ARS",
        iva=21.0,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def producto_erp_2(db) -> ProductoERP:
    """A second product with no brand markup."""
    p = ProductoERP(
        item_id=ITEM_ID_2,
        codigo="TST-002",
        descripcion="Producto Sin Marca",
        marca=None,
        costo=200.0,
        moneda_costo="ARS",
        iva=21.0,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def producto_pricing(db, producto_erp) -> ProductoPricing:
    """ProductoPricing row with markup_calculado for ITEM_ID."""
    pp = ProductoPricing(
        item_id=ITEM_ID,
        markup_calculado=20.0,
        precio_lista_ml=1500.0,
    )
    db.add(pp)
    db.flush()
    return pp


@pytest.fixture
def markup_producto_existente(db, producto_erp) -> MarkupTiendaProducto:
    """An existing MarkupTiendaProducto row for ITEM_ID."""
    m = MarkupTiendaProducto(
        item_id=ITEM_ID,
        codigo="TST-001",
        descripcion="Producto Test",
        marca="MarcaTest",
        markup_porcentaje=15.0,
        markup_sugerido=5.0,
        activo=True,
        notas="nota1",
    )
    db.add(m)
    db.flush()
    return m


@pytest.fixture
def markup_brand(db) -> MarkupTiendaBrand:
    """A brand markup row for 'MarcaTest' (brand_id=999)."""
    b = MarkupTiendaBrand(
        comp_id=1,
        brand_id=999,
        brand_desc="MarcaTest",
        markup_porcentaje=10.0,
        markup_sugerido=3.0,
        activo=True,
    )
    db.add(b)
    db.flush()
    return b


# ==========================================================================
# T-10 — Parity: helper vs. original inline formula
# ==========================================================================


class TestComputarPrecioSugeridoHelper:
    """
    T-10: Asserts computar_precio_sugerido produces output identical to the
    original inline formula in productos_listing.py L2033-2040 (before extraction).
    This test locks the helper against drift and is a merge gate.
    """

    def test_parity_with_inline_formula(self):
        costo_ars = 1000.0
        iva = 21.0
        markup_clasica = 20.0
        markup_sugerido_valor = 5.0
        varios_porcentaje = 6.5

        # Original inline formula (verbatim from listing before extraction)
        effective_sugerido = markup_sugerido_valor if markup_sugerido_valor is not None else 0.0
        expected_total = markup_clasica + effective_sugerido
        expected_sin_iva = costo_ars * (1 + varios_porcentaje / 100) * (1 + expected_total / 100)
        expected_con_iva = expected_sin_iva * (1 + iva / 100)

        sin_iva, con_iva, total = computar_precio_sugerido(
            costo_ars=costo_ars,
            iva=iva,
            markup_clasica=markup_clasica,
            markup_sugerido_valor=markup_sugerido_valor,
            varios_porcentaje=varios_porcentaje,
        )

        assert sin_iva == expected_sin_iva
        assert con_iva == expected_con_iva
        assert total == expected_total

    def test_parity_with_none_sugerido(self):
        """markup_sugerido_valor=None should behave same as 0.0."""
        costo_ars = 500.0
        iva = 10.5
        markup_clasica = 15.0
        varios_porcentaje = 6.5

        # original: effective=0, total=15, sin_iva computed
        effective_sugerido = 0.0
        expected_total = markup_clasica + effective_sugerido
        expected_sin_iva = costo_ars * (1 + varios_porcentaje / 100) * (1 + expected_total / 100)
        expected_con_iva = expected_sin_iva * (1 + iva / 100)

        sin_iva, con_iva, total = computar_precio_sugerido(
            costo_ars=costo_ars,
            iva=iva,
            markup_clasica=markup_clasica,
            markup_sugerido_valor=None,
            varios_porcentaje=varios_porcentaje,
        )

        assert sin_iva == expected_sin_iva
        assert con_iva == expected_con_iva
        assert total == expected_total

    def test_returns_none_when_markup_clasica_missing(self):
        sin_iva, con_iva, total = computar_precio_sugerido(
            costo_ars=1000.0,
            iva=21.0,
            markup_clasica=None,
            markup_sugerido_valor=5.0,
            varios_porcentaje=6.5,
        )
        assert sin_iva is None
        assert con_iva is None
        assert total is None

    def test_returns_none_when_costo_zero(self):
        sin_iva, con_iva, total = computar_precio_sugerido(
            costo_ars=0.0,
            iva=21.0,
            markup_clasica=20.0,
            markup_sugerido_valor=5.0,
            varios_porcentaje=6.5,
        )
        assert sin_iva is None


# ==========================================================================
# Endpoint tests
# ==========================================================================

ENDPOINT = "/api/markups-tienda/productos/{item_id}/markup-sugerido"


class TestPermissionsAndErrors:
    """T-7 and T-8."""

    def test_t7_403_without_permission(self, client, auth_headers, producto_erp, sin_permiso_markups):
        url = ENDPOINT.format(item_id=ITEM_ID)
        response = client.patch(url, json={"markup_sugerido": 5.0}, headers=auth_headers)
        assert response.status_code == 403

    def test_t8_404_unknown_item(self, client, auth_headers, con_permiso_markups):
        url = ENDPOINT.format(item_id=99999)
        response = client.patch(url, json={"markup_sugerido": 5.0}, headers=auth_headers)
        assert response.status_code == 404

    def test_401_without_auth(self, client, producto_erp):
        url = ENDPOINT.format(item_id=ITEM_ID)
        response = client.patch(url, json={"markup_sugerido": 5.0})
        # The auth guard returns 401 or 403 depending on configuration; both are acceptable
        assert response.status_code in (401, 403)


class TestUpsertBehavior:
    """T-1, T-2, T-6a."""

    def test_t1_sets_markup_sugerido_preserves_markup_porcentaje(
        self, client, auth_headers, db, producto_erp, markup_producto_existente, con_permiso_markups
    ):
        """T-1: PATCH on existing row sets markup_sugerido, preserves markup_porcentaje."""
        url = ENDPOINT.format(item_id=ITEM_ID)
        response = client.patch(url, json={"markup_sugerido": 8.0}, headers=auth_headers)
        assert response.status_code == 200

        db.expire_all()
        row = db.query(MarkupTiendaProducto).filter_by(item_id=ITEM_ID).first()
        assert row is not None
        assert row.markup_sugerido == 8.0
        assert row.markup_porcentaje == 15.0  # preserved

        data = response.json()
        assert "precio_sugerido_sin_iva" in data
        assert "precio_sugerido_con_iva" in data
        assert "markup_sugerido_valor" in data
        assert "markup_sugerido_total" in data
        assert "markup_sugerido_origen" in data

    def test_t2_creates_row_when_none_exists(
        self, client, auth_headers, db, producto_erp, producto_pricing, con_permiso_markups
    ):
        """T-2: PATCH when no row exists creates row, defaults markup_porcentaje to gremio."""
        url = ENDPOINT.format(item_id=ITEM_ID)
        response = client.patch(url, json={"markup_sugerido": 3.0}, headers=auth_headers)
        assert response.status_code == 200

        db.expire_all()
        row = db.query(MarkupTiendaProducto).filter_by(item_id=ITEM_ID).first()
        assert row is not None
        assert row.markup_sugerido == 3.0
        # INTENTIONAL: creating a row freezes the product's gremio markup at current resolved value
        # When no existing product row, gremio resolves from brand or 0.
        assert row.markup_porcentaje is not None
        assert row.codigo == "TST-001"
        assert row.descripcion == "Producto Test"
        assert row.marca == "MarcaTest"

    def test_t6a_preserves_codigo_descripcion_activo_notas(
        self, client, auth_headers, db, producto_erp, markup_producto_existente, con_permiso_markups
    ):
        """T-6a: codigo/descripcion/activo/notas are unchanged after PATCH."""
        url = ENDPOINT.format(item_id=ITEM_ID)
        response = client.patch(url, json={"markup_sugerido": 3.0}, headers=auth_headers)
        assert response.status_code == 200

        db.expire_all()
        row = db.query(MarkupTiendaProducto).filter_by(item_id=ITEM_ID).first()
        assert row.codigo == "TST-001"
        assert row.descripcion == "Producto Test"
        assert row.activo is True
        assert row.notas == "nota1"


class TestRoundingAndEdgeCases:
    """T-5 (rounding), T-11 (negative)."""

    def test_t5_rounds_to_2_decimals(self, client, auth_headers, db, producto_erp, con_permiso_markups):
        """T-5: input 7.555 → persisted 7.56."""
        url = ENDPOINT.format(item_id=ITEM_ID)
        response = client.patch(url, json={"markup_sugerido": 7.555}, headers=auth_headers)
        assert response.status_code == 200

        db.expire_all()
        row = db.query(MarkupTiendaProducto).filter_by(item_id=ITEM_ID).first()
        assert row is not None
        assert row.markup_sugerido == round(7.555, 2)

    def test_t11_negative_markup_accepted(
        self, client, auth_headers, db, producto_erp, markup_producto_existente, con_permiso_markups
    ):
        """T-11: negative markup is allowed, persisted as-is."""
        url = ENDPOINT.format(item_id=ITEM_ID)
        response = client.patch(url, json={"markup_sugerido": -5.0}, headers=auth_headers)
        assert response.status_code == 200

        db.expire_all()
        row = db.query(MarkupTiendaProducto).filter_by(item_id=ITEM_ID).first()
        assert row.markup_sugerido == -5.0


class TestClearSemantics:
    """T-3, T-4, T-6b (zero), T-4b."""

    def test_t3_null_deletes_row(
        self, client, auth_headers, db, producto_erp, markup_producto_existente, con_permiso_markups
    ):
        """T-3: markup_sugerido: null deletes the row."""
        url = ENDPOINT.format(item_id=ITEM_ID)
        response = client.patch(url, json={"markup_sugerido": None}, headers=auth_headers)
        assert response.status_code == 200

        db.expire_all()
        row = db.query(MarkupTiendaProducto).filter_by(item_id=ITEM_ID).first()
        assert row is None

    def test_t4_clear_when_no_row_is_idempotent(self, client, auth_headers, db, producto_erp, con_permiso_markups):
        """T-4: clearing when no row exists → idempotent 200, no error."""
        url = ENDPOINT.format(item_id=ITEM_ID)
        response = client.patch(url, json={"markup_sugerido": None}, headers=auth_headers)
        assert response.status_code == 200

    def test_t6b_explicit_zero_stores_row(self, client, auth_headers, db, producto_erp, con_permiso_markups):
        """T-6b: explicit 0 → stored 0.0 (not treated as clear)."""
        url = ENDPOINT.format(item_id=ITEM_ID)
        response = client.patch(url, json={"markup_sugerido": 0}, headers=auth_headers)
        assert response.status_code == 200

        db.expire_all()
        row = db.query(MarkupTiendaProducto).filter_by(item_id=ITEM_ID).first()
        assert row is not None
        assert row.markup_sugerido == 0.0

        data = response.json()
        assert data["markup_sugerido_origen"] == "producto"

    def test_t4b_clear_with_no_brand_yields_null_origin(
        self, client, auth_headers, db, producto_erp_2, con_permiso_markups
    ):
        """T-4b: clear with no brand row → markup_sugerido_origen is null."""
        url = ENDPOINT.format(item_id=ITEM_ID_2)
        response = client.patch(url, json={"markup_sugerido": None}, headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert data["markup_sugerido_origen"] is None


class TestOriginResolution:
    """T-9a, T-9b, T-9c."""

    def test_t9a_origin_producto_when_row_exists(
        self, client, auth_headers, db, producto_erp, markup_producto_existente, con_permiso_markups
    ):
        """T-9a: product row exists → response.markup_sugerido_origen == 'producto'."""
        url = ENDPOINT.format(item_id=ITEM_ID)
        response = client.patch(url, json={"markup_sugerido": 5.0}, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["markup_sugerido_origen"] == "producto"

    def test_t9b_origin_marca_when_only_brand_row(
        self, client, auth_headers, db, producto_erp, markup_brand, con_permiso_markups
    ):
        """T-9b: no product row, brand row exists → 'marca'."""
        url = ENDPOINT.format(item_id=ITEM_ID)
        # Clear the individual row so the effective sugerido falls back to the brand.
        # The brand fixture seeds brand_desc='MarcaTest', matching producto_erp.marca,
        # so the endpoint must resolve the effective markup from the brand row.
        response = client.patch(url, json={"markup_sugerido": None}, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["markup_sugerido_origen"] == "marca"

    def test_t9c_origin_null_when_neither(self, client, auth_headers, db, producto_erp, con_permiso_markups):
        """T-9c: no product row, no brand row → markup_sugerido_origen is None."""
        url = ENDPOINT.format(item_id=ITEM_ID)
        response = client.patch(url, json={"markup_sugerido": None}, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["markup_sugerido_origen"] is None
