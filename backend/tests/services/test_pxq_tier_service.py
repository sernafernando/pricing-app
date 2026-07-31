"""Service-layer validation for creating `MlPxqTier` rows (PR2, task 9/10).

Max 5 tiers per publication and `cantidad_minima > 1` are validated here
(422) BEFORE hitting the DB — the DB CheckConstraint/UniqueConstraint are a
second, independent line of defense (see tests/models/test_ml_pxq_tier.py),
not the primary UX-facing validation path.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.security import get_password_hash
from app.models.ml_pxq_tier import MlPxqTier
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services.pxq_tier_service import MAX_TIERS_PER_PUBLICATION, create_pxq_tier


@pytest.fixture()
def pxq_user(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="pxq_svc_user",
        email="pxq_svc_user@example.com",
        nombre="PxQ Service User",
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
    producto = ProductoERP(item_id=90101, codigo="SKU-PXQ-SVC", descripcion="Producto PxQ", costo=1000.0)
    db.add(producto)
    db.flush()
    return producto


@pytest.fixture()
def publicacion(db, producto) -> PublicacionML:
    pub = PublicacionML(mla="MLA910001", item_id=producto.item_id, codigo="SKU-PXQ-SVC")
    db.add(pub)
    db.flush()
    return pub


def test_create_tier_happy_path(db, publicacion, pxq_user) -> None:
    tier = create_pxq_tier(
        db,
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=5,
        precio_unitario=500.0,
        usuario_id=pxq_user.id,
    )
    assert tier.id is not None
    assert tier.estado == "incompleto"


def test_cantidad_minima_of_one_rejected_with_422(db, publicacion, pxq_user) -> None:
    with pytest.raises(HTTPException) as exc_info:
        create_pxq_tier(
            db,
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=1,
            precio_unitario=500.0,
            usuario_id=pxq_user.id,
        )
    assert exc_info.value.status_code == 422


def test_sixth_tier_for_same_publication_rejected_with_422(db, publicacion, pxq_user) -> None:
    for cantidad in range(2, 2 + MAX_TIERS_PER_PUBLICATION):
        create_pxq_tier(
            db,
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=cantidad,
            precio_unitario=500.0,
            usuario_id=pxq_user.id,
        )

    assert db.query(MlPxqTier).filter_by(publicacion_ml_id=publicacion.id).count() == MAX_TIERS_PER_PUBLICATION

    with pytest.raises(HTTPException) as exc_info:
        create_pxq_tier(
            db,
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=2 + MAX_TIERS_PER_PUBLICATION,
            precio_unitario=500.0,
            usuario_id=pxq_user.id,
        )
    assert exc_info.value.status_code == 422
    # The 6th tier must never have been persisted.
    assert db.query(MlPxqTier).filter_by(publicacion_ml_id=publicacion.id).count() == MAX_TIERS_PER_PUBLICATION
