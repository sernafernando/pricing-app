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
from app.models.tienda_nube_producto import TiendaNubeProducto
from app.models.usuario import AuthProvider, RolUsuario, Usuario


def _bearer(user: Usuario) -> dict[str, str]:
    token = create_access_token(data={"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def sync_user(db) -> Usuario:
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
