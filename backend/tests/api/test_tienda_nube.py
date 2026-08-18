"""Tests for `app/api/endpoints/tienda_nube.py`.

SEC1 (backend/security-hardening): `GET /tienda-nube/productos` was reachable
by any authenticated user with no permission check and no `response_model`,
and had zero callers anywhere in the repo (verified: no frontend caller, no
other backend module import). It was removed outright rather than gated,
per the spec's "zero current callers -> MUST be removed" rule.
"""

from __future__ import annotations

from app.core.security import create_access_token, get_password_hash
from app.models.usuario import AuthProvider, RolUsuario, Usuario


def _bearer(user: Usuario) -> dict[str, str]:
    token = create_access_token(data={"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


def _make_user(db) -> Usuario:
    user = Usuario(
        username="tn_productos_test",
        email="tn_productos_test@test.com",
        nombre="TN Productos Test",
        password_hash=get_password_hash("x"),
        rol=RolUsuario.VENTAS,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


class TestDeadUngatedProductosEndpointRemoved:
    def test_unauthenticated_request_returns_404(self, client):
        """No route registered at all — not even reachable to check auth."""
        response = client.get("/api/tienda-nube/productos")
        assert response.status_code == 404

    def test_authenticated_request_also_returns_404(self, client, db):
        """Removed for everyone, not just unauthenticated callers — the
        route simply does not exist anymore."""
        user = _make_user(db)
        response = client.get("/api/tienda-nube/productos", headers=_bearer(user))
        assert response.status_code == 404
