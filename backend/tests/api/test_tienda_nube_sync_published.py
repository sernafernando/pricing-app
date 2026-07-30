"""Integration tests for `POST /api/tienda-nube/sync`'s `published` mapping.

Fourth review round found a real bug: this endpoint is the SECOND writer of
`tienda_nube_productos` (the first being `scripts/sync_tienda_nube.py`) and,
unlike that script, never mapped TN's product-level `published` field onto
its per-variant rows — every row this endpoint touches got `published=NULL`
forever, silently defeating `_is_visible()`'s DESPUBLICAR logic for any
catalog synced this way.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.models.usuario import AuthProvider, RolUsuario, Usuario


def _bearer(user: Usuario) -> dict[str, str]:
    token = create_access_token(data={"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _tn_credentials():
    """Provide Tienda Nube credentials to the endpoint under test.

    `app/api/endpoints/tienda_nube.py` reads `TN_STORE_ID`/`TN_ACCESS_TOKEN`
    into module globals at import time and returns 500 when either is falsy,
    before any mocked HTTP call is reached. Those values come from
    `backend/.env`, which is gitignored and therefore absent on CI — the
    workflow exports only ENVIRONMENT, DATABASE_URL and SECRET_KEY. Without
    this fixture these tests pass locally and fail on CI with 500 instead
    of 200.

    Patch the module globals, not `settings`: the binding already happened
    at import, so patching `settings` would have no effect here.
    """
    from app.api.endpoints import tienda_nube as tn_endpoint

    with (
        patch.object(tn_endpoint, "TN_STORE_ID", "123456"),
        patch.object(tn_endpoint, "TN_ACCESS_TOKEN", "fake-token"),
    ):
        yield


@pytest.fixture()
def perm_publicacion(db) -> Permiso:
    p = Permiso(
        codigo="admin.gestionar_tn_publicacion",
        nombre="Gestionar publicación Tienda Nube",
        descripcion="Publish/unpublish",
        categoria="administracion",
        orden=64,
        es_critico=True,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def sync_user(db, perm_publicacion) -> Usuario:
    # Legacy `rol=ADMIN`/`rol_id=None` carries no role-based permissions of
    # its own (this project's permission model is role-ID/override based,
    # not tied to the legacy enum) — grant the new server-side permission
    # gate explicitly via an override so this fixture keeps exercising the
    # published-mapping behavior these tests are actually about, unaffected
    # by the separate `TestSyncEndpointPermission` gate tests below.
    user = Usuario(
        username="tn_sync_user",
        email="tn_sync@test.com",
        nombre="Sync User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.ADMIN,
        rol_id=None,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=perm_publicacion.id, concedido=True))
    db.flush()
    return user


@pytest.fixture()
def brand_rol(db) -> Rol:
    rol = Rol(codigo="TN_SYNC_TEST", nombre="TN Sync Test", es_sistema=False, orden=99, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def user_no_perm(db, brand_rol) -> Usuario:
    user = Usuario(
        username="tn_sync_no_perm",
        email="tn_sync_no_perm@test.com",
        nombre="No Perm",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=brand_rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def user_publicacion(db, brand_rol, perm_publicacion) -> Usuario:
    user = Usuario(
        username="tn_sync_pub",
        email="tn_sync_pub@test.com",
        nombre="Pub User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=brand_rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=perm_publicacion.id, concedido=True))
    db.flush()
    return user


def _tn_product(product_id=1, published=True, variant_id=10, sku="SKU-1", price=100.0):
    product = {
        "id": product_id,
        "name": {"es": "Producto"},
        "price": price,
        "variants": [{"id": variant_id, "sku": sku, "price": price}],
    }
    if published is not None:
        product["published"] = published
    return product


def _tn_product_raw_variant(product_id, variant_id, variant: dict):
    """Like `_tn_product` but lets the caller pass the variant dict verbatim
    (e.g. `sku: None` or no `sku` key at all) instead of always setting a
    string `sku`."""
    return {
        "id": product_id,
        "name": {"es": "Producto"},
        "published": True,
        "variants": [{"id": variant_id, **variant}],
    }


def _mock_products_response(products: list[dict]):
    """One page of results, then an empty page to end pagination."""
    first_page = httpx.Response(200, json=products, request=httpx.Request("GET", "http://test"))
    empty_page = httpx.Response(200, json=[], request=httpx.Request("GET", "http://test"))
    return AsyncMock(side_effect=[first_page, empty_page] if products else [empty_page])


class TestSyncEndpointPublishedMapping:
    def test_new_row_gets_published_true(self, client, db, sync_user):
        products = [_tn_product(product_id=100, published=True, variant_id=1000, sku="NEW-SKU")]
        with patch("httpx.AsyncClient.get", new=_mock_products_response(products)):
            response = client.post("/api/tienda-nube/sync", headers=_bearer(sync_user))

        assert response.status_code == 200
        row = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.variant_id == 1000).first()
        assert row is not None
        assert row.published is True

    def test_missing_published_field_maps_to_none_not_false(self, client, db, sync_user):
        products = [_tn_product(product_id=101, published=None, variant_id=1001, sku="NO-PUBLISHED-FIELD")]
        with patch("httpx.AsyncClient.get", new=_mock_products_response(products)):
            response = client.post("/api/tienda-nube/sync", headers=_bearer(sync_user))

        assert response.status_code == 200
        row = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.variant_id == 1001).first()
        assert row is not None
        assert row.published is None

    def test_known_true_is_not_nulled_by_a_later_sync_missing_the_field(self, client, db, sync_user):
        # First sync: published=True is recorded.
        first_products = [_tn_product(product_id=102, published=True, variant_id=1002, sku="STAYS-TRUE")]
        with patch("httpx.AsyncClient.get", new=_mock_products_response(first_products)):
            response = client.post("/api/tienda-nube/sync", headers=_bearer(sync_user))
        assert response.status_code == 200
        row = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.variant_id == 1002).first()
        assert row.published is True

        # Second sync: TN's response happens to omit `published` this time —
        # the previously-known True must survive, never silently become NULL.
        second_products = [_tn_product(product_id=102, published=None, variant_id=1002, sku="STAYS-TRUE")]
        with patch("httpx.AsyncClient.get", new=_mock_products_response(second_products)):
            response = client.post("/api/tienda-nube/sync", headers=_bearer(sync_user))
        assert response.status_code == 200

        db.expire_all()
        row = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.variant_id == 1002).first()
        assert row.published is True


class TestSyncEndpointPermission:
    """This slice turned `POST /tienda-nube/sync` into a visible operator
    action (a UI trigger gated on `admin.gestionar_tn_publicacion`), so
    server-side enforcement of that same permission must ship in the same
    PR — the UI gate alone is presentation, not a real access control."""

    def test_requires_permission(self, client, db, user_no_perm):
        response = client.post("/api/tienda-nube/sync", headers=_bearer(user_no_perm))
        assert response.status_code == 403

    def test_succeeds_with_permission(self, client, db, user_publicacion):
        products = [_tn_product(product_id=200, published=True, variant_id=2000, sku="PERM-OK")]
        with patch("httpx.AsyncClient.get", new=_mock_products_response(products)):
            response = client.post("/api/tienda-nube/sync", headers=_bearer(user_publicacion))
        assert response.status_code == 200


class TestSyncEndpointVariantSkuNormalization:
    """Round 7, item 1: `variant_sku` is the reconciliation join key
    (`compute_verdicts._normalize_sku`) — both `tienda_nube_productos`
    writers must normalize it IDENTICALLY to the cron writer
    (`extract_variantes`, pinned in
    tests/unit/test_sync_tienda_nube_published_mapping.py::TestVariantSkuNormalization).
    Before this fix the endpoint stored raw `None`/whitespace instead."""

    def test_null_sku_normalizes_to_empty_string_not_none(self, client, db, sync_user):
        products = [_tn_product_raw_variant(product_id=200, variant_id=2000, variant={"sku": None})]
        with patch("httpx.AsyncClient.get", new=_mock_products_response(products)):
            response = client.post("/api/tienda-nube/sync", headers=_bearer(sync_user))

        assert response.status_code == 200
        row = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.variant_id == 2000).first()
        assert row is not None
        # Must match extract_variantes' normalization exactly — "" not None,
        # so _normalize_sku (which drops None from the join index) can never
        # silently un-match this row.
        assert row.variant_sku == ""

    def test_absent_sku_normalizes_to_empty_string(self, client, db, sync_user):
        products = [_tn_product_raw_variant(product_id=201, variant_id=2001, variant={})]
        with patch("httpx.AsyncClient.get", new=_mock_products_response(products)):
            response = client.post("/api/tienda-nube/sync", headers=_bearer(sync_user))

        assert response.status_code == 200
        row = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.variant_id == 2001).first()
        assert row is not None
        assert row.variant_sku == ""

    def test_sku_with_surrounding_whitespace_is_stripped(self, client, db, sync_user):
        products = [_tn_product_raw_variant(product_id=202, variant_id=2002, variant={"sku": "  0123456  "})]
        with patch("httpx.AsyncClient.get", new=_mock_products_response(products)):
            response = client.post("/api/tienda-nube/sync", headers=_bearer(sync_user))

        assert response.status_code == 200
        row = db.query(TiendaNubeProducto).filter(TiendaNubeProducto.variant_id == 2002).first()
        assert row is not None
        # Untrimmed whitespace would make every ERP match query (exact,
        # SUBSTRING, '0'||...) miss and item_id would stay NULL forever.
        assert row.variant_sku == "0123456"
