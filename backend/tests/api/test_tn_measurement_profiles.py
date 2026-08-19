"""Integration tests for TN measurement profile CRUD + suggestion (PR-4).

Covers: profile-CRUD permission gate (MP1) separable in both directions from
the publish permission (D5/D10), and the category-based suggestion endpoint
(MP3) — exact match, category-only fallback, and cold-start empty result.
"""

from __future__ import annotations

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.tn_category_profile_hint import TnCategoryProfileHint
from app.models.tn_measurement_profile import TnMeasurementProfile
from app.models.usuario import AuthProvider, RolUsuario, Usuario


def _bearer(user: Usuario) -> dict[str, str]:
    token = create_access_token(data={"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def brand_rol(db) -> Rol:
    rol = Rol(codigo="TN_PROFILES_TEST", nombre="TN Profiles Test", es_sistema=False, orden=99, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def perm_perfiles(db) -> Permiso:
    p = Permiso(
        codigo="admin.gestionar_tn_perfiles",
        nombre="Gestionar perfiles de medidas TN",
        descripcion="Manage profiles",
        categoria="administracion",
        orden=65,
        es_critico=False,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def perm_publicacion(db) -> Permiso:
    p = Permiso(
        codigo="admin.gestionar_tn_publicacion",
        nombre="Gestionar publicación Tienda Nube",
        descripcion="Publish",
        categoria="administracion",
        orden=64,
        es_critico=True,
    )
    db.add(p)
    db.flush()
    return p


def _make_user(db, brand_rol, username, perms=()) -> Usuario:
    user = Usuario(
        username=username,
        email=f"{username}@test.com",
        nombre=username,
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=brand_rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    for perm in perms:
        db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=perm.id, concedido=True))
    db.flush()
    return user


@pytest.fixture()
def user_only_publicacion(db, brand_rol, perm_publicacion) -> Usuario:
    return _make_user(db, brand_rol, "tn_only_publicacion", perms=[perm_publicacion])


@pytest.fixture()
def user_only_perfiles(db, brand_rol, perm_perfiles) -> Usuario:
    return _make_user(db, brand_rol, "tn_only_perfiles", perms=[perm_perfiles])


@pytest.fixture()
def user_no_perm(db, brand_rol) -> Usuario:
    return _make_user(db, brand_rol, "tn_profiles_no_perm")


class TestProfileCrudPermissionGate:
    def test_publish_permission_alone_gets_403_on_create(self, client, db, user_only_publicacion):
        resp = client.post(
            "/api/tn-measurement-profiles",
            json={"name": "test", "weight": 1.0, "width": 10, "height": 10, "depth": 10},
            headers=_bearer(user_only_publicacion),
        )
        assert resp.status_code == 403

    def test_publish_permission_alone_gets_403_on_update(self, client, db, user_only_publicacion):
        profile = TnMeasurementProfile(name="seed", weight=1, width=10, height=10, depth=10)
        db.add(profile)
        db.flush()

        resp = client.put(
            f"/api/tn-measurement-profiles/{profile.id}",
            json={"name": "updated", "weight": 2.0, "width": 20, "height": 20, "depth": 20},
            headers=_bearer(user_only_publicacion),
        )
        assert resp.status_code == 403

    def test_publish_permission_alone_gets_403_on_delete(self, client, db, user_only_publicacion):
        profile = TnMeasurementProfile(name="seed", weight=1, width=10, height=10, depth=10)
        db.add(profile)
        db.flush()

        resp = client.delete(
            f"/api/tn-measurement-profiles/{profile.id}",
            headers=_bearer(user_only_publicacion),
        )
        assert resp.status_code == 403

    def test_perfiles_permission_alone_gets_403_on_publish_endpoint(self, client, db, user_only_perfiles):
        resp = client.post(
            "/api/tienda-nube-reconcile/publicar",
            json={
                "ean": "EAN-1",
                "product_data": {"name": "Test", "price": 100},
                "category_id": 1,
                "description_html": "<p>Test</p>",
            },
            headers=_bearer(user_only_perfiles),
        )
        assert resp.status_code == 403

    def test_perfiles_permission_grants_create(self, client, db, user_only_perfiles):
        resp = client.post(
            "/api/tn-measurement-profiles",
            json={"name": "30x20x20", "weight": 0.3, "width": 30, "height": 20, "depth": 20},
            headers=_bearer(user_only_perfiles),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "30x20x20"
        assert float(body["weight"]) == 0.3

    def test_no_permission_gets_403(self, client, db, user_no_perm):
        resp = client.post(
            "/api/tn-measurement-profiles",
            json={"name": "test", "weight": 1.0, "width": 10, "height": 10, "depth": 10},
            headers=_bearer(user_no_perm),
        )
        assert resp.status_code == 403


class TestReadEndpointsRequireAuthentication:
    """Pre-push review finding: "no permission gate" must not mean "no
    authentication". Every endpoint still requires a valid bearer token
    (repo Security Checklist) — the read side is merely permission-free,
    not anonymous."""

    def test_list_without_token_is_rejected(self, client):
        resp = client.get("/api/tn-measurement-profiles")
        assert resp.status_code == 401

    def test_suggestion_without_token_is_rejected(self, client):
        resp = client.get(
            "/api/tn-measurement-profiles/suggestion",
            params={"categoria": "Hogar"},
        )
        assert resp.status_code == 401

    def test_list_with_token_needs_no_permission(self, client, db, user_no_perm):
        resp = client.get("/api/tn-measurement-profiles", headers=_bearer(user_no_perm))
        assert resp.status_code == 200


class TestDeleteResponseContract:
    def test_delete_returns_typed_response(self, client, db, user_only_perfiles):
        profile = TnMeasurementProfile(name="seed", weight=1, width=10, height=10, depth=10)
        db.add(profile)
        db.flush()

        resp = client.delete(
            f"/api/tn-measurement-profiles/{profile.id}",
            headers=_bearer(user_only_perfiles),
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "message": "Perfil de medidas eliminado",
            "profile_id": profile.id,
        }


class TestProfileSuggestion:
    def test_suggestion_returns_profile_id_for_category_with_history(self, client, db, user_no_perm):
        profile = TnMeasurementProfile(name="30x20x20", weight=0.3, width=30, height=20, depth=20)
        db.add(profile)
        db.flush()

        hint = TnCategoryProfileHint(
            categoria="Electrónica", subcategoria="Auriculares", profile_id=profile.id, uso_count=5
        )
        db.add(hint)
        db.flush()

        resp = client.get(
            "/api/tn-measurement-profiles/suggestion",
            params={"categoria": "Electrónica", "subcategoria": "Auriculares"},
            headers=_bearer(user_no_perm),
        )
        assert resp.status_code == 200
        assert resp.json()["profile_id"] == profile.id

    def test_suggestion_falls_back_to_category_only_hint(self, client, db, user_no_perm):
        profile = TnMeasurementProfile(name="50x40x20", weight=0.6, width=50, height=40, depth=20)
        db.add(profile)
        db.flush()

        hint = TnCategoryProfileHint(categoria="Hogar", subcategoria=None, profile_id=profile.id, uso_count=2)
        db.add(hint)
        db.flush()

        resp = client.get(
            "/api/tn-measurement-profiles/suggestion",
            params={"categoria": "Hogar", "subcategoria": "Cocina"},
            headers=_bearer(user_no_perm),
        )
        assert resp.status_code == 200
        assert resp.json()["profile_id"] == profile.id

    def test_tied_uso_count_resolves_deterministically_to_lowest_id(self, client, db, user_no_perm):
        profile_a = TnMeasurementProfile(name="A", weight=1, width=10, height=10, depth=10)
        profile_b = TnMeasurementProfile(name="B", weight=2, width=20, height=20, depth=20)
        db.add_all([profile_a, profile_b])
        db.flush()

        hint_a = TnCategoryProfileHint(categoria="Empate", subcategoria=None, profile_id=profile_a.id, uso_count=3)
        hint_b = TnCategoryProfileHint(categoria="Empate", subcategoria=None, profile_id=profile_b.id, uso_count=3)
        db.add_all([hint_a, hint_b])
        db.flush()

        # Tie on uso_count: the secondary `id` ordering makes the answer
        # stable across query plans instead of arbitrary.
        resp = client.get(
            "/api/tn-measurement-profiles/suggestion",
            params={"categoria": "Empate"},
            headers=_bearer(user_no_perm),
        )
        assert resp.status_code == 200
        assert resp.json()["profile_id"] == profile_a.id

    def test_no_suggestion_available_returns_empty_not_error(self, client, db, user_no_perm):
        resp = client.get(
            "/api/tn-measurement-profiles/suggestion",
            params={"categoria": "Categoria-Nunca-Usada"},
            headers=_bearer(user_no_perm),
        )
        assert resp.status_code == 200
        assert resp.json()["profile_id"] is None


class TestSuggestionRouteRegisteredBeforeProfileId:
    """PR-7 task D — route ordering bomb. There is no `GET /{profile_id}`
    today, so `GET /suggestion` happens to work regardless of registration
    order; but FastAPI matches routes in REGISTRATION order, and the day a
    `GET /{profile_id}` is added, a `/suggestion` request registered AFTER
    it would parse `"suggestion"` as `int` against `{profile_id}` first and
    422. Pinning the registration order itself — not just the current
    200 — is what actually prevents that regression."""

    def test_suggestion_route_index_precedes_every_profile_id_route(self):
        from app.api.endpoints.tn_measurement_profiles import router

        route_paths = [route.path for route in router.routes]
        suggestion_index = route_paths.index("/tn-measurement-profiles/suggestion")
        profile_id_indexes = [
            i for i, path in enumerate(route_paths) if path == "/tn-measurement-profiles/{profile_id}"
        ]
        assert profile_id_indexes, "expected PUT/DELETE /{profile_id} routes to exist"
        assert all(suggestion_index < i for i in profile_id_indexes)
