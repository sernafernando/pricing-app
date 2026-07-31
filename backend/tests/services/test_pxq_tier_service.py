"""Service-layer validation for creating `MlPxqTier` rows (PR2, task 9/10).

Max 5 tiers per publication and `cantidad_minima > 1` are validated here
(422) BEFORE hitting the DB — the DB CheckConstraint/UniqueConstraint are a
second, independent line of defense (see tests/models/test_ml_pxq_tier.py),
not the primary UX-facing validation path.
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


def test_unknown_publicacion_is_a_clean_422_not_an_integrity_error(db, pxq_user) -> None:
    """`with_for_update().first()` takes no lock when the row does not exist,
    so the TOCTOU window this service claims to close stayed open for exactly
    the case nobody checked. Verifying the lookup succeeded closes it and, in
    the same move, turns an FK IntegrityError at flush into the clean 422 this
    service says it produces."""
    with pytest.raises(HTTPException) as exc:
        create_pxq_tier(
            db,
            publicacion_ml_id=987654,
            item_id="MLA_NOPE",
            cantidad_minima=5,
            precio_unitario=Decimal("500.00"),
            usuario_id=pxq_user.id,
        )

    assert exc.value.status_code == 422
    assert "987654" in str(exc.value.detail)


def test_price_is_stored_as_decimal_not_binary_float(db, publicacion, pxq_user) -> None:
    """`precio_unitario` is Numeric(14, 2). Money entering as a binary float
    means 500.10 is not 500.10, and nobody notices until a sum of tiers fails
    to reconcile."""
    tier = create_pxq_tier(
        db,
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=5,
        precio_unitario=500.10,
        usuario_id=pxq_user.id,
        costo_envio_total=3200.45,
    )
    db.flush()

    assert isinstance(tier.precio_unitario, Decimal)
    assert tier.precio_unitario == Decimal("500.10")
    assert isinstance(tier.costo_envio_total, Decimal)
    assert tier.costo_envio_total == Decimal("3200.45")


def test_duplicate_cantidad_minima_through_the_service_is_a_clean_422(db, publicacion, pxq_user) -> None:
    """The unique constraint was only ever exercised by writing rows directly,
    so the service path — the one an endpoint actually calls — reached flush
    and raised IntegrityError, i.e. a 500 where this module promises a 422.

    The check sits inside the window already serialized by the publication
    lock, so it is not a new race of its own."""
    create_pxq_tier(
        db,
        publicacion_ml_id=publicacion.id,
        item_id=publicacion.mla,
        cantidad_minima=5,
        precio_unitario=Decimal("500.00"),
        usuario_id=pxq_user.id,
    )
    db.flush()

    with pytest.raises(HTTPException) as exc:
        create_pxq_tier(
            db,
            publicacion_ml_id=publicacion.id,
            item_id=publicacion.mla,
            cantidad_minima=5,
            precio_unitario=Decimal("900.00"),
            usuario_id=pxq_user.id,
        )

    assert exc.value.status_code == 422
    assert "5" in str(exc.value.detail)


def test_item_id_must_match_its_publication(db, publicacion, pxq_user) -> None:
    """`item_id` is the MLA denormalized off the publication, and PR 3 keys the
    live-vs-mirror diff on it. A row claiming a different MLA than its own
    publication would aim that diff at the wrong listing — so it is checked
    against the row the service already holds under lock."""
    with pytest.raises(HTTPException) as exc:
        create_pxq_tier(
            db,
            publicacion_ml_id=publicacion.id,
            item_id="MLA_SOMETHING_ELSE",
            cantidad_minima=5,
            precio_unitario=Decimal("500.00"),
            usuario_id=pxq_user.id,
        )

    assert exc.value.status_code == 422
    assert "MLA_SOMETHING_ELSE" in str(exc.value.detail)
