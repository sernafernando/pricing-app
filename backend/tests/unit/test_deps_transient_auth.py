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

Fourth review round: the original version of this test reused the live `db`
fixture session as the "background" session, which never actually closes
during the test — so `usuario.es_superadmin` could still lazy-load `rol_obj`
successfully through that still-open session even WITHOUT the `joinedload`
fix, meaning the test could not fail for the reason it claimed to guard.
Fixed by using a genuinely separate session (bound to the same underlying
connection, so it still sees the fixture-created rows) that is closed via
its own `finally` before the assertion runs, exactly mirroring the
production code path (`get_background_db()`'s own session close).
"""

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
    """A genuinely separate, genuinely-closed-on-exit session — bound to
    the SAME connection as the test's `db` fixture (so it sees the
    fixture-created rows within the same not-yet-committed transaction),
    but its own lifecycle is independent: `.close()` runs in `finally`,
    detaching whatever was loaded through it, exactly like the real
    `get_background_db()` context manager does. Reusing the live `db`
    fixture session directly (the original version of this test) would
    never close, so a missing eager-load could never actually surface as
    a `DetachedInstanceError` here."""
    session = sessionmaker(bind=bind)()
    try:
        yield session
    finally:
        session.close()


class TestTransientAuthEagerLoadsRolObj:
    @pytest.mark.asyncio
    async def test_es_superadmin_readable_after_detach(self, db, transient_user):
        """`es_superadmin` (and therefore `verificar_permiso`'s fallback
        path) must be readable on the returned user WITHOUT a live session —
        that's the whole point of "transient" auth. Confirmed RED (raises
        `DetachedInstanceError`) with the `joinedload(Usuario.rol_obj)` fix
        temporarily removed from `get_current_user_transient`, and GREEN
        with it in place — see apply-progress for the exact RED/GREEN
        transcript."""
        token = create_access_token(data={"sub": transient_user.username})
        credentials = MagicMock(credentials=token)

        with patch("app.api.deps.get_background_db", lambda: _fake_background_db(db.connection())):
            usuario = await get_current_user_transient(credentials=credentials)

        # The session that loaded `usuario` is now closed (see
        # `_fake_background_db`'s `finally`) — reading `es_superadmin` must
        # not need a lazy load, or this raises DetachedInstanceError.
        assert usuario.es_superadmin is False
