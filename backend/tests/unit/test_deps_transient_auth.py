"""Regression test for `get_current_user_transient` (app/api/deps.py).

Discovered while wiring `GET /tienda-nube-reconcile/reporte` to use transient
auth (review blocker #2): the returned `Usuario` is DETACHED from its
session (`db.expunge`), but the query building it did NOT eager-load
`rol_obj` the way `get_current_user` does. Any caller that then touches
`usuario.es_superadmin` (which reads `self.rol_obj.codigo`) — e.g.
`verificar_permiso`'s fallback path for cache-less/detached users — hits a
`DetachedInstanceError` trying to lazy-load `rol_obj` on an object with no
live session. `get_current_user_transient` must eager-load `rol_obj` too so
its stated contract ("solo usar para leer atributos ya cargados") actually
holds for `rol`/`rol_obj`-derived attributes.

Production incident (2026-07-23): the fix above (eager-load `rol_obj`) was
NOT enough, and the earlier versions of this test could not catch it. The
real trigger is `get_background_db()`'s "on success: commit + close" plus
`SessionLocal`'s default `expire_on_commit=True`: the commit EXPIRES every
loaded instance's attributes, including the eager-loaded `Rol`, right before
the session closes. `get_current_user_transient` only `expunge`d the
`Usuario` (not its `rol_obj`), so the `Rol` stayed attached, got expired by
that commit, and then detached — so `rol_obj.codigo` raised
`DetachedInstanceError` in prod even WITH the joinedload. Fix:
`db.expunge_all()` (detach the Rol too, BEFORE the commit expires it).

Every earlier version of this test merely CLOSED the fake background
session; closing detaches but does NOT expire loaded attributes, so the bug
was invisible here. This fixture now `expire_all()`s on success — exactly
what the real commit does to attribute state — before closing, so a `Rol`
left attached expires just as it does in production.

This module is deliberately synchronous and drives the coroutine with
`asyncio.run`: the project has NO pytest-asyncio configured (CI installs only
`requirements.txt` plus `pytest httpx`), so `@pytest.mark.asyncio` is silently
skipped locally and fails on CI with "async def functions are not natively
supported". Other test modules in this repo carry the same warning.
"""

import asyncio
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_current_user_transient
from app.core.security import create_access_token, get_password_hash
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario


@pytest.fixture()
def rol_ventas_transient(db) -> Rol:
    rol = Rol(codigo="VENTAS", nombre="Ventas", es_sistema=False, orden=10, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def transient_user(db, rol_ventas_transient) -> Usuario:
    user = Usuario(
        username="transient_user",
        email="transient@test.com",
        nombre="Transient User",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas_transient.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


@contextmanager
def _fake_background_db(bind):
    """A faithful stand-in for the real `get_background_db()` — a separate
    session bound to the SAME connection as the test's `db` fixture (so it
    sees the fixture-created rows within the same not-yet-committed
    transaction), that reproduces production's "on success: commit + close".

    The `expire_all()` on the success path is the crucial part: the real
    session commits, and `expire_on_commit=True` expires every loaded
    instance's attributes before the close. `expire_all()` reproduces exactly
    that attribute-state effect WITHOUT a real commit (which would break the
    test's outer transaction). Merely closing — as every earlier version of
    this test did — detaches without expiring, so a `Rol` left attached never
    surfaced as a `DetachedInstanceError` here even though it did in prod."""
    session = sessionmaker(bind=bind)()
    try:
        yield session
        session.expire_all()  # mirror commit's expire_on_commit effect
    finally:
        session.close()


class TestTransientAuthEagerLoadsRolObj:
    def test_rol_derived_attrs_readable_after_detach(self, db, transient_user):
        """`es_superadmin` and `rol_codigo` (both read `self.rol_obj.codigo`,
        and drive `verificar_permiso`'s fallback path) must be readable on the
        returned user WITHOUT a live session — the whole point of "transient"
        auth. This is the production `/reporte` 500 path. Confirmed RED
        (`DetachedInstanceError`) with `db.expunge_all()` reverted to
        `db.expunge(usuario)`, GREEN with `expunge_all()` in place."""
        token = create_access_token(data={"sub": transient_user.username})
        credentials = MagicMock(credentials=token)

        with patch("app.api.deps.get_background_db", lambda: _fake_background_db(db.connection())):
            usuario = asyncio.run(get_current_user_transient(credentials=credentials))

        # The background session has committed-then-closed (see the fixture),
        # so both the Usuario and its Rol are detached. Reading rol-derived
        # attributes must not trigger a refresh, or this raises
        # DetachedInstanceError — the exact prod failure in /reporte.
        assert usuario.rol_codigo == "VENTAS"
        assert usuario.es_superadmin is False
