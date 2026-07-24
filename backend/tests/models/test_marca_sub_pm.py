"""Model tests for MarcaSubPM (sub-pm-scope-marcas PR1).

Mirrors MarcaPM's column shapes but relaxes the pair uniqueness: the same
(marca, categoria) pair may be granted to several sub-PM users, so the
uniqueness is on (marca, categoria, usuario_id) instead.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.security import get_password_hash
from app.models.marca_sub_pm import MarcaSubPM
from app.models.usuario import AuthProvider, RolUsuario, Usuario


@pytest.fixture()
def sub_pm_user(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="sub_pm_user",
        email="sub_pm_user@example.com",
        nombre="Sub PM User",
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
def other_sub_pm_user(db, rol_ventas) -> Usuario:
    user = Usuario(
        username="other_sub_pm_user",
        email="other_sub_pm_user@example.com",
        nombre="Other Sub PM User",
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def test_create_marca_sub_pm_row(db, sub_pm_user) -> None:
    row = MarcaSubPM(marca="Nike", categoria="Zapatillas", usuario_id=sub_pm_user.id)
    db.add(row)
    db.flush()

    assert row.id is not None
    assert row.marca == "Nike"
    assert row.categoria == "Zapatillas"
    assert row.usuario_id == sub_pm_user.id
    assert row.creado_por is None
    assert row.created_at is not None


def test_same_pair_multiple_sub_pm_users_allowed(db, sub_pm_user, other_sub_pm_user) -> None:
    """NO unique on (marca, categoria) — several users can be sub-PM of the same pair."""
    db.add(MarcaSubPM(marca="Nike", categoria="Zapatillas", usuario_id=sub_pm_user.id))
    db.add(MarcaSubPM(marca="Nike", categoria="Zapatillas", usuario_id=other_sub_pm_user.id))
    db.flush()

    rows = db.query(MarcaSubPM).filter_by(marca="Nike", categoria="Zapatillas").all()
    assert len(rows) == 2


def test_duplicate_marca_categoria_usuario_violates_unique_constraint(db, sub_pm_user) -> None:
    db.add(MarcaSubPM(marca="Nike", categoria="Zapatillas", usuario_id=sub_pm_user.id))
    db.flush()

    db.add(MarcaSubPM(marca="Nike", categoria="Zapatillas", usuario_id=sub_pm_user.id))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_creado_por_is_nullable_but_tracks_grantor(db, sub_pm_user, other_sub_pm_user) -> None:
    row = MarcaSubPM(
        marca="Adidas",
        categoria="Ropa",
        usuario_id=sub_pm_user.id,
        creado_por=other_sub_pm_user.id,
    )
    db.add(row)
    db.flush()
    assert row.creado_por == other_sub_pm_user.id
