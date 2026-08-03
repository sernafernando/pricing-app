"""Tests for the PxQ tier CRUD endpoints (PR 4b): create/edit/delete a tier.

These endpoints only touch our own DB (no ML call), so unlike the live-read
endpoint they use the ordinary `get_current_user` + `Depends(get_db)` -- no
transient-user/short-session dance is needed (see `app/routers/pxq.py` module
docstring). Tests call the router functions directly with the real `db`
fixture, same as `tests/services/test_pxq_tier_service.py`, and monkeypatch
`PermisosService.tiene_permiso` the same way `test_ml_pxq_write_service.py`
does, rather than wiring a full TestClient + auth stack.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.security import get_password_hash
from app.models.ml_pxq_tier import MlPxqTier
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.routers import pxq as pxq_router
from app.routers.pxq import (
    PxqCreateTierRequest,
    PxqUpdateTierRequest,
    crear_tier_pxq,
    editar_tier_pxq,
    eliminar_tier_pxq,
)


@pytest.fixture()
def pxq_user(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="pxq_crud_user",
        email="pxq_crud_user@example.com",
        nombre="PxQ CRUD User",
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
    producto = ProductoERP(item_id=90201, codigo="SKU-PXQ-CRUD", descripcion="Producto PxQ CRUD", costo=1000.0)
    db.add(producto)
    db.flush()
    return producto


@pytest.fixture()
def publicacion(db, producto) -> PublicacionML:
    pub = PublicacionML(mla="MLA920001", item_id=producto.item_id, codigo="SKU-PXQ-CRUD")
    db.add(pub)
    db.flush()
    return pub


@pytest.fixture(autouse=True)
def _grant_pxq_escribir(monkeypatch):
    """Same shortcut `test_ml_pxq_write_service.py` uses: bypass the real
    permission catalog and just say yes, so these tests exercise CRUD
    behaviour, not `PermisosService` internals."""
    monkeypatch.setattr(pxq_router.PermisosService, "tiene_permiso", lambda self, usuario, codigo: True)


def test_create_tier_via_endpoint(db, publicacion, pxq_user) -> None:
    body = PxqCreateTierRequest(cantidad_minima=5, precio_unitario=500.0)

    result = crear_tier_pxq(item_id=publicacion.mla, body=body, current_user=pxq_user, db=db)

    assert result.cantidad_minima == 5
    assert result.precio_unitario == 500.0
    row = db.query(MlPxqTier).filter_by(id=result.id).first()
    assert row is not None
    assert row.item_id == publicacion.mla


def test_create_tier_unknown_item_id_is_404(db, pxq_user) -> None:
    body = PxqCreateTierRequest(cantidad_minima=5, precio_unitario=500.0)

    with pytest.raises(HTTPException) as exc:
        crear_tier_pxq(item_id="MLA_NOPE", body=body, current_user=pxq_user, db=db)

    assert exc.value.status_code == 404


def test_create_tier_without_permission_is_403(db, publicacion, pxq_user, monkeypatch) -> None:
    monkeypatch.setattr(pxq_router.PermisosService, "tiene_permiso", lambda self, usuario, codigo: False)
    body = PxqCreateTierRequest(cantidad_minima=5, precio_unitario=500.0)

    with pytest.raises(HTTPException) as exc:
        crear_tier_pxq(item_id=publicacion.mla, body=body, current_user=pxq_user, db=db)

    assert exc.value.status_code == 403


def test_edit_tier_via_endpoint_changes_price_and_quantity(db, publicacion, pxq_user) -> None:
    created = crear_tier_pxq(
        item_id=publicacion.mla,
        body=PxqCreateTierRequest(cantidad_minima=5, precio_unitario=500.0),
        current_user=pxq_user,
        db=db,
    )

    updated = editar_tier_pxq(
        item_id=publicacion.mla,
        tier_id=created.id,
        body=PxqUpdateTierRequest(cantidad_minima=8, precio_unitario=650.0),
        current_user=pxq_user,
        db=db,
    )

    assert updated.cantidad_minima == 8
    assert updated.precio_unitario == 650.0


def test_edit_tier_never_advances_the_synced_snapshot_via_endpoint(db, publicacion, pxq_user) -> None:
    created = crear_tier_pxq(
        item_id=publicacion.mla,
        body=PxqCreateTierRequest(cantidad_minima=5, precio_unitario=500.0),
        current_user=pxq_user,
        db=db,
    )
    row = db.query(MlPxqTier).filter_by(id=created.id).first()
    row.cantidad_sincronizada = 5
    row.precio_sincronizado = Decimal("500.00")
    db.commit()

    editar_tier_pxq(
        item_id=publicacion.mla,
        tier_id=created.id,
        body=PxqUpdateTierRequest(cantidad_minima=9, precio_unitario=999.0),
        current_user=pxq_user,
        db=db,
    )

    db.refresh(row)
    assert row.cantidad_sincronizada == 5
    assert row.precio_sincronizado == Decimal("500.00")


def test_edit_tier_wrong_item_id_is_404(db, publicacion, pxq_user) -> None:
    created = crear_tier_pxq(
        item_id=publicacion.mla,
        body=PxqCreateTierRequest(cantidad_minima=5, precio_unitario=500.0),
        current_user=pxq_user,
        db=db,
    )

    with pytest.raises(HTTPException) as exc:
        editar_tier_pxq(
            item_id="MLA_OTHER",
            tier_id=created.id,
            body=PxqUpdateTierRequest(cantidad_minima=8),
            current_user=pxq_user,
            db=db,
        )

    assert exc.value.status_code == 404


def test_edit_tier_without_permission_is_403(db, publicacion, pxq_user, monkeypatch) -> None:
    created = crear_tier_pxq(
        item_id=publicacion.mla,
        body=PxqCreateTierRequest(cantidad_minima=5, precio_unitario=500.0),
        current_user=pxq_user,
        db=db,
    )
    monkeypatch.setattr(pxq_router.PermisosService, "tiene_permiso", lambda self, usuario, codigo: False)

    with pytest.raises(HTTPException) as exc:
        editar_tier_pxq(
            item_id=publicacion.mla,
            tier_id=created.id,
            body=PxqUpdateTierRequest(cantidad_minima=8),
            current_user=pxq_user,
            db=db,
        )

    assert exc.value.status_code == 403


def test_delete_tier_via_endpoint_removes_the_local_row(db, publicacion, pxq_user) -> None:
    created = crear_tier_pxq(
        item_id=publicacion.mla,
        body=PxqCreateTierRequest(cantidad_minima=5, precio_unitario=500.0),
        current_user=pxq_user,
        db=db,
    )

    eliminar_tier_pxq(item_id=publicacion.mla, tier_id=created.id, current_user=pxq_user, db=db)

    assert db.query(MlPxqTier).filter_by(id=created.id).first() is None


def test_delete_tier_wrong_item_id_is_404(db, publicacion, pxq_user) -> None:
    created = crear_tier_pxq(
        item_id=publicacion.mla,
        body=PxqCreateTierRequest(cantidad_minima=5, precio_unitario=500.0),
        current_user=pxq_user,
        db=db,
    )

    with pytest.raises(HTTPException) as exc:
        eliminar_tier_pxq(item_id="MLA_OTHER", tier_id=created.id, current_user=pxq_user, db=db)

    assert exc.value.status_code == 404
    # The row must still exist -- a 404 must not silently delete anyway.
    assert db.query(MlPxqTier).filter_by(id=created.id).first() is not None


def test_delete_tier_without_permission_is_403(db, publicacion, pxq_user, monkeypatch) -> None:
    created = crear_tier_pxq(
        item_id=publicacion.mla,
        body=PxqCreateTierRequest(cantidad_minima=5, precio_unitario=500.0),
        current_user=pxq_user,
        db=db,
    )
    monkeypatch.setattr(pxq_router.PermisosService, "tiene_permiso", lambda self, usuario, codigo: False)

    with pytest.raises(HTTPException) as exc:
        eliminar_tier_pxq(item_id=publicacion.mla, tier_id=created.id, current_user=pxq_user, db=db)

    assert exc.value.status_code == 403
    assert db.query(MlPxqTier).filter_by(id=created.id).first() is not None
