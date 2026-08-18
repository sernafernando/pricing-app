"""Tests for `GET /pxq/{item_id}/markup` (slice A1, task 1.6; pool-safety
fix in slice B).

NOT a pure DB read anymore (slice B): the endpoint runs a TTL-gated shipping
auto-fetch (`pxq_markup_service.refresh_stale_tier_shipping`) before the
markup read, so -- like `GET /{item_id}/live` -- it now uses
`get_current_user_transient` with short `get_background_db()` blocks
instead of `Depends(get_db)`. Tests call the router function directly and
monkeypatch BOTH `pxq_router.get_background_db` AND
`pxq_markup_service.get_background_db` to a double wrapping the real `db`
fixture (same technique `test_pxq_router_live_endpoint.py` uses for
`GET /{item_id}/live`) -- `refresh_stale_tier_shipping` lives in a
different module and opens its OWN sessions, so both call sites need the
double independently. `tests/conftest.py`'s autouse guard already pins the
proxy fetch itself to `None` for every test here (today's real production
answer, proxy route absent), so these tests keep exercising the
degrade-to-`shipping_unavailable` path exactly as before, plus the
`costo_envio_total` set directly by `_add_tier` (bypassing the fetch)
covers the resolved-markup path. Authentication itself (401) is enforced by
the `get_current_user` JWT dependency at the FastAPI layer, out of scope for
this direct-function unit test; only the `pxq.ver` permission check
(`_require_pxq_read`, 403) is exercised here.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.security import get_password_hash
from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.ml_pxq_tier import MlPxqTier
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services import pxq_markup_service
from app.routers import pxq as pxq_router
from app.routers.pxq import obtener_markup_pxq


@pytest.fixture()
def pxq_user(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="pxq_markup_endpoint_user",
        email="pxq_markup_endpoint_user@example.com",
        nombre="PxQ Markup Endpoint User",
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def producto(db) -> ProductoERP:
    producto = ProductoERP(
        item_id=93001,
        codigo="SKU-PXQ-MKT-EP",
        descripcion="Producto PxQ markup endpoint",
        costo=1000.0,
        moneda_costo="ARS",
        iva=21.0,
    )
    db.add(producto)
    db.flush()
    return producto


@pytest.fixture()
def publicacion(db, producto) -> PublicacionML:
    pub = PublicacionML(mla="MLA9300001", item_id=producto.item_id, codigo=producto.codigo, pricelist_id=4)
    db.add(pub)
    db.flush()
    return pub


@pytest.fixture()
def comision_fixtures(db) -> ComisionVersion:
    version = ComisionVersion(nombre="Test PxQ Endpoint", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=18.0))
    db.flush()
    return version


@pytest.fixture(autouse=True)
def _grant_pxq_ver(monkeypatch):
    """Same shortcut `test_pxq_router_tier_crud.py` uses: bypass the real
    permission catalog and just say yes, so these tests exercise the
    endpoint's own behaviour, not `PermisosService` internals."""
    monkeypatch.setattr(pxq_router.PermisosService, "tiene_permiso", lambda self, usuario, codigo: True)


class _RealDbCM:
    """Wraps the REAL test `db` fixture session so the endpoint's short
    `get_background_db()` blocks -- and `refresh_stale_tier_shipping`'s own,
    separate ones in `pxq_markup_service` -- see the fixture-created data,
    instead of the disjoint production `SessionLocal`/`DATABASE_URL`
    `get_background_db` is bound to by default in tests."""

    def __init__(self, db):
        self._db = db

    def __call__(self):
        return self

    def __enter__(self):
        return self._db

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _real_background_db(db, monkeypatch):
    double = _RealDbCM(db)
    monkeypatch.setattr(pxq_router, "get_background_db", double)
    monkeypatch.setattr(pxq_markup_service, "get_background_db", double)


def _add_tier(db, publicacion, pxq_user, *, cantidad_minima, precio_unitario, costo_envio_total=None):
    tier = MlPxqTier(
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=cantidad_minima,
        precio_unitario=Decimal(precio_unitario),
        costo_envio_total=Decimal(costo_envio_total) if costo_envio_total is not None else None,
        usuario_id=pxq_user.id,
    )
    db.add(tier)
    db.flush()
    return tier


def test_get_markup_returns_resolved_markup_for_a_tier(db, publicacion, pxq_user, comision_fixtures) -> None:
    tier = _add_tier(
        db, publicacion, pxq_user, cantidad_minima=10, precio_unitario="500.00", costo_envio_total="200.00"
    )

    response = obtener_markup_pxq(item_id=publicacion.mla, current_user=pxq_user)

    assert response.item_id == publicacion.mla
    entries = {t.tier_id: t for t in response.tiers}
    assert tier.id in entries
    resolved = entries[tier.id]
    assert resolved.reason is None
    assert resolved.markup is not None
    assert resolved.limpio is not None
    assert resolved.comision_total is not None


def test_get_markup_response_omits_numeric_fields_when_unresolved(db, publicacion, pxq_user, comision_fixtures) -> None:
    tier = _add_tier(db, publicacion, pxq_user, cantidad_minima=5, precio_unitario="300.00", costo_envio_total=None)

    response = obtener_markup_pxq(item_id=publicacion.mla, current_user=pxq_user)

    entries = {t.tier_id: t for t in response.tiers}
    unresolved = entries[tier.id]
    assert unresolved.reason == "shipping_unavailable"

    # Structural regression guard: serialize with the same `exclude_none`
    # contract the route is declared with, and confirm no numeric field
    # survives -- not just that the Python attributes happen to be None.
    dumped = unresolved.model_dump(exclude_none=True)
    assert "markup" not in dumped
    assert "limpio" not in dumped
    assert "comision_total" not in dumped
    assert dumped["reason"] == "shipping_unavailable"


def test_get_markup_batch_covers_all_tiers(db, publicacion, pxq_user, comision_fixtures) -> None:
    tier_a = _add_tier(
        db, publicacion, pxq_user, cantidad_minima=5, precio_unitario="300.00", costo_envio_total="80.00"
    )
    tier_b = _add_tier(db, publicacion, pxq_user, cantidad_minima=10, precio_unitario="500.00", costo_envio_total=None)

    response = obtener_markup_pxq(item_id=publicacion.mla, current_user=pxq_user)

    tier_ids = {t.tier_id for t in response.tiers}
    assert tier_ids == {tier_a.id, tier_b.id}


def test_get_markup_without_permission_is_403(db, publicacion, pxq_user, monkeypatch) -> None:
    monkeypatch.setattr(pxq_router.PermisosService, "tiene_permiso", lambda self, usuario, codigo: False)

    with pytest.raises(HTTPException) as exc:
        obtener_markup_pxq(item_id=publicacion.mla, current_user=pxq_user)

    assert exc.value.status_code == 403
