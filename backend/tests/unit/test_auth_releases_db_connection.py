"""get_current_user must not hold its DB connection for the whole request.

The auth dependency uses get_async_db while most endpoints use get_db, so each
request opens two sessions. If auth keeps its transaction open, a burst of
concurrent requests holds one connection each while waiting for the second,
and the pool deadlocks until pool_timeout (prod incident 2026-09-25).
"""

import asyncio

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import inspect
from sqlalchemy.exc import InvalidRequestError

from app.api.deps import get_current_user
from app.core.security import create_access_token


def _call(db, username):
    token = create_access_token({"sub": username})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return asyncio.run(get_current_user(credentials=creds, db=db))


def test_get_current_user_ends_its_transaction(db, active_user):
    usuario = _call(db, active_user.username)

    assert usuario.id == active_user.id
    assert not db.in_transaction()


def test_user_and_role_stay_loaded_after_release(db, active_user):
    usuario = _call(db, active_user.username)

    assert not inspect(usuario).expired_attributes
    assert not inspect(usuario.rol_obj).expired_attributes
    assert not db.in_transaction()
    assert usuario.rol_codigo == "VENTAS"
    assert isinstance(usuario._permisos_cache, set)


def test_unloaded_relationship_raises_instead_of_reacquiring_a_connection(db, active_user):
    """A lazy load would start a new transaction on the auth session and hold
    a second pooled connection until the request ends, bringing the pool
    deadlock back. Unloaded relationships must fail loudly instead."""
    usuario = _call(db, active_user.username)

    with pytest.raises(InvalidRequestError):
        usuario.notificaciones
    with pytest.raises(InvalidRequestError):
        usuario.rol_obj.usuarios
    assert not db.in_transaction()
