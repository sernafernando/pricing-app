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
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

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
def _fake_background_db(db):
    yield db


class TestTransientAuthEagerLoadsRolObj:
    @pytest.mark.asyncio
    async def test_es_superadmin_readable_after_detach(self, db, transient_user):
        """`es_superadmin` (and therefore `verificar_permiso`'s fallback
        path) must be readable on the returned user WITHOUT a live session —
        that's the whole point of "transient" auth."""
        token = create_access_token(data={"sub": transient_user.username})
        credentials = MagicMock(credentials=token)

        with patch("app.api.deps.get_background_db", lambda: _fake_background_db(db)):
            usuario = await get_current_user_transient(credentials=credentials)

        # Session is "closed" from this object's perspective (expunged) —
        # reading es_superadmin must not need a lazy load.
        assert usuario.es_superadmin is False
