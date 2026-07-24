"""Endpoint tests for sub-PM CRUD (PR2 of sub-pm-scope-marcas).

Covers the ownership guard (_require_titular_or_admin) and the
GET/POST/DELETE /marcas-pm/sub-pms + GET /marcas-pm/mis-titularidades
routes: 200/201/204/400/403/404 matrix, idempotent duplicate grant,
self-grant rejection, inactive-target rejection, and re-verified (not
cached) ownership on every write.
"""

from app.models.marca_pm import MarcaPM
from app.models.marca_sub_pm import MarcaSubPM
from app.models.usuario import RolUsuario, Usuario, AuthProvider
from app.core.security import get_password_hash

from tests.conftest import TEST_PASSWORD, make_access_token


def _make_user(db, rol_ventas, *, username: str, activo: bool = True) -> Usuario:
    user = Usuario(
        username=username,
        email=f"{username}@example.com",
        nombre=username,
        password_hash=get_password_hash(TEST_PASSWORD),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=activo,
    )
    db.add(user)
    db.flush()
    return user


def _headers(user: Usuario) -> dict:
    return {"Authorization": f"Bearer {make_access_token(user)}"}


def _make_pair(db, *, marca="Nike", categoria="Zapatillas", titular: Usuario = None) -> MarcaPM:
    pair = MarcaPM(marca=marca, categoria=categoria, usuario_id=titular.id if titular else None)
    db.add(pair)
    db.flush()
    return pair


# ── Fixtures ──────────────────────────────────────────────────────────────


import pytest


@pytest.fixture()
def titular(db, rol_ventas) -> Usuario:
    return _make_user(db, rol_ventas, username="titular_t")


@pytest.fixture()
def otro_usuario(db, rol_ventas) -> Usuario:
    return _make_user(db, rol_ventas, username="no_titular_x")


@pytest.fixture()
def grantee(db, rol_ventas) -> Usuario:
    return _make_user(db, rol_ventas, username="grantee_g")


@pytest.fixture()
def inactive_grantee(db, rol_ventas) -> Usuario:
    return _make_user(db, rol_ventas, username="inactive_g", activo=False)


@pytest.fixture()
def par(db, titular) -> MarcaPM:
    return _make_pair(db, titular=titular)


@pytest.fixture()
def par_sin_titular(db) -> MarcaPM:
    return _make_pair(db, marca="Adidas", categoria="Ropa", titular=None)


# ── GET /marcas-pm/mis-titularidades ────────────────────────────────────


class TestMisTitularidades:
    def test_devuelve_solo_pares_titular(self, client, db, titular, par):
        resp = client.get("/api/marcas-pm/mis-titularidades", headers=_headers(titular))
        assert resp.status_code == 200
        data = resp.json()
        assert any(p["marca"] == "Nike" and p["categoria"] == "Zapatillas" for p in data["pares"])

    def test_excluye_pares_solo_sub_pm(self, client, db, titular, grantee, par):
        """A sub-PM-only pair MUST NOT leak into mis-titularidades (no UNION)."""
        db.add(MarcaSubPM(marca=par.marca, categoria=par.categoria, usuario_id=grantee.id, creado_por=titular.id))
        db.commit()

        resp = client.get("/api/marcas-pm/mis-titularidades", headers=_headers(grantee))
        assert resp.status_code == 200
        assert resp.json()["pares"] == []


# ── GET /marcas-pm/sub-pms ──────────────────────────────────────────────


class TestListarSubPMs:
    def test_titular_lista_sus_sub_pms(self, client, db, titular, par, grantee):
        db.add(MarcaSubPM(marca=par.marca, categoria=par.categoria, usuario_id=grantee.id, creado_por=titular.id))
        db.commit()

        resp = client.get(
            "/api/marcas-pm/sub-pms",
            params={"marca": par.marca, "categoria": par.categoria},
            headers=_headers(titular),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["usuario_id"] == grantee.id

    def test_admin_lista_cualquier_par(self, client, db, admin_user, par, grantee):
        db.add(MarcaSubPM(marca=par.marca, categoria=par.categoria, usuario_id=grantee.id))
        db.commit()

        resp = client.get(
            "/api/marcas-pm/sub-pms",
            params={"marca": par.marca, "categoria": par.categoria},
            headers={"Authorization": f"Bearer {make_access_token(admin_user)}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_no_titular_no_admin_403(self, client, db, otro_usuario, par):
        resp = client.get(
            "/api/marcas-pm/sub-pms",
            params={"marca": par.marca, "categoria": par.categoria},
            headers=_headers(otro_usuario),
        )
        assert resp.status_code == 403

    def test_par_desconocido_404(self, client, db, titular):
        resp = client.get(
            "/api/marcas-pm/sub-pms",
            params={"marca": "Inexistente", "categoria": "Nada"},
            headers=_headers(titular),
        )
        assert resp.status_code == 404

    def test_par_sin_titular_no_admin_403(self, client, db, otro_usuario, par_sin_titular):
        resp = client.get(
            "/api/marcas-pm/sub-pms",
            params={"marca": par_sin_titular.marca, "categoria": par_sin_titular.categoria},
            headers=_headers(otro_usuario),
        )
        assert resp.status_code == 403

    def test_par_sin_titular_admin_ok(self, client, db, admin_user, par_sin_titular):
        resp = client.get(
            "/api/marcas-pm/sub-pms",
            params={"marca": par_sin_titular.marca, "categoria": par_sin_titular.categoria},
            headers={"Authorization": f"Bearer {make_access_token(admin_user)}"},
        )
        assert resp.status_code == 200


# ── POST /marcas-pm/sub-pms ─────────────────────────────────────────────


class TestCrearSubPM:
    def test_titular_crea_grant_201(self, client, db, titular, par, grantee):
        resp = client.post(
            "/api/marcas-pm/sub-pms",
            json={"marca": par.marca, "categoria": par.categoria, "usuario_id": grantee.id},
            headers=_headers(titular),
        )
        assert resp.status_code == 201
        assert resp.json()["usuario_id"] == grantee.id

    def test_duplicado_idempotente_200(self, client, db, titular, par, grantee):
        db.add(MarcaSubPM(marca=par.marca, categoria=par.categoria, usuario_id=grantee.id, creado_por=titular.id))
        db.commit()

        resp = client.post(
            "/api/marcas-pm/sub-pms",
            json={"marca": par.marca, "categoria": par.categoria, "usuario_id": grantee.id},
            headers=_headers(titular),
        )
        assert resp.status_code == 200
        assert db.query(MarcaSubPM).filter(MarcaSubPM.usuario_id == grantee.id).count() == 1

    def test_no_titular_403(self, client, db, otro_usuario, par, grantee):
        resp = client.post(
            "/api/marcas-pm/sub-pms",
            json={"marca": par.marca, "categoria": par.categoria, "usuario_id": grantee.id},
            headers=_headers(otro_usuario),
        )
        assert resp.status_code == 403

    def test_par_desconocido_404(self, client, db, titular, grantee):
        resp = client.post(
            "/api/marcas-pm/sub-pms",
            json={"marca": "Inexistente", "categoria": "Nada", "usuario_id": grantee.id},
            headers=_headers(titular),
        )
        assert resp.status_code == 404

    def test_usuario_desconocido_404(self, client, db, titular, par):
        resp = client.post(
            "/api/marcas-pm/sub-pms",
            json={"marca": par.marca, "categoria": par.categoria, "usuario_id": 999999},
            headers=_headers(titular),
        )
        assert resp.status_code == 404

    def test_auto_grant_400(self, client, db, titular, par):
        resp = client.post(
            "/api/marcas-pm/sub-pms",
            json={"marca": par.marca, "categoria": par.categoria, "usuario_id": titular.id},
            headers=_headers(titular),
        )
        assert resp.status_code == 400

    def test_usuario_inactivo_400(self, client, db, titular, par, inactive_grantee):
        resp = client.post(
            "/api/marcas-pm/sub-pms",
            json={"marca": par.marca, "categoria": par.categoria, "usuario_id": inactive_grantee.id},
            headers=_headers(titular),
        )
        assert resp.status_code == 400

    def test_no_infiere_permisos(self, client, db, titular, par, grantee):
        """Granting sub-PM status MUST NOT alter the grantee's role/permisos."""
        resp = client.post(
            "/api/marcas-pm/sub-pms",
            json={"marca": par.marca, "categoria": par.categoria, "usuario_id": grantee.id},
            headers=_headers(titular),
        )
        assert resp.status_code == 201
        db.refresh(grantee)
        assert grantee.rol == RolUsuario.VENTAS


# ── DELETE /marcas-pm/sub-pms/{id} ──────────────────────────────────────


class TestRevocarSubPM:
    def test_titular_revoca_204(self, client, db, titular, par, grantee):
        grant = MarcaSubPM(marca=par.marca, categoria=par.categoria, usuario_id=grantee.id, creado_por=titular.id)
        db.add(grant)
        db.commit()

        resp = client.delete(f"/api/marcas-pm/sub-pms/{grant.id}", headers=_headers(titular))
        assert resp.status_code == 204
        assert db.query(MarcaSubPM).filter(MarcaSubPM.id == grant.id).first() is None

    def test_no_titular_actual_403(self, client, db, titular, otro_usuario, par, grantee):
        """Ownership is re-verified against the row's CURRENT pair ownership,
        not cached from grant time: reassign the pair's titular away from
        `titular`, then the original titular can no longer revoke."""
        grant = MarcaSubPM(marca=par.marca, categoria=par.categoria, usuario_id=grantee.id, creado_por=titular.id)
        db.add(grant)
        db.flush()

        par.usuario_id = otro_usuario.id
        db.commit()

        resp = client.delete(f"/api/marcas-pm/sub-pms/{grant.id}", headers=_headers(titular))
        assert resp.status_code == 403

    def test_admin_revoca_cualquiera(self, client, db, admin_user, titular, par, grantee):
        grant = MarcaSubPM(marca=par.marca, categoria=par.categoria, usuario_id=grantee.id, creado_por=titular.id)
        db.add(grant)
        db.commit()

        resp = client.delete(
            f"/api/marcas-pm/sub-pms/{grant.id}",
            headers={"Authorization": f"Bearer {make_access_token(admin_user)}"},
        )
        assert resp.status_code == 204

    def test_grant_desconocido_404(self, client, db, titular):
        resp = client.delete("/api/marcas-pm/sub-pms/999999", headers=_headers(titular))
        assert resp.status_code == 404
