"""Tests for Slice 1 of sub-pm-bulk-assignment: the shared writable-pairs
resolver plus the two read endpoints that feed the bulk-assignment picker
(pre-check listing and aggregate grant counts).

Does NOT cover the bulk PUT (Slice 2) or any frontend behavior.
"""

from app.api.endpoints.marcas_pm import _resolve_writable_pairs
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


import pytest


@pytest.fixture()
def titular(db, rol_ventas) -> Usuario:
    return _make_user(db, rol_ventas, username="titular_bulk_t")


@pytest.fixture()
def otro_titular(db, rol_ventas) -> Usuario:
    return _make_user(db, rol_ventas, username="titular_bulk_o")


@pytest.fixture()
def grantee(db, rol_ventas) -> Usuario:
    return _make_user(db, rol_ventas, username="grantee_bulk_g")


@pytest.fixture()
def par(db, titular) -> MarcaPM:
    return _make_pair(db, marca="Nike", categoria="Zapatillas", titular=titular)


@pytest.fixture()
def par_otro(db, otro_titular) -> MarcaPM:
    return _make_pair(db, marca="Puma", categoria="Remeras", titular=otro_titular)


@pytest.fixture()
def par_sin_titular(db) -> MarcaPM:
    return _make_pair(db, marca="Adidas", categoria="Ropa", titular=None)


# ── _resolve_writable_pairs (unit) ──────────────────────────────────────


class TestResolveWritablePairs:
    def test_titular_solo_ve_sus_propios_pares(self, db, titular, par, par_otro):
        pares = _resolve_writable_pairs(db, titular)
        assert pares == {(par.marca, par.categoria)}

    def test_admin_ve_todos_los_pares_incluidos_sin_titular(self, db, admin_user, par, par_otro, par_sin_titular):
        pares = _resolve_writable_pairs(db, admin_user)
        assert pares == {
            (par.marca, par.categoria),
            (par_otro.marca, par_otro.categoria),
            (par_sin_titular.marca, par_sin_titular.categoria),
        }

    def test_titular_sin_pares_devuelve_vacio(self, db, titular):
        assert _resolve_writable_pairs(db, titular) == set()

    def test_titular_no_ve_pares_sin_titular(self, db, titular, par, par_sin_titular):
        pares = _resolve_writable_pairs(db, titular)
        assert (par_sin_titular.marca, par_sin_titular.categoria) not in pares


# ── GET /marcas-pm/sub-pms/usuario/{usuario_id} ─────────────────────────


class TestGrantsPorUsuario:
    def test_admin_ve_grants_del_usuario_en_par_sin_titular(self, client, db, admin_user, par_sin_titular, grantee):
        db.add(MarcaSubPM(marca=par_sin_titular.marca, categoria=par_sin_titular.categoria, usuario_id=grantee.id))
        db.commit()

        resp = client.get(
            f"/api/marcas-pm/sub-pms/usuario/{grantee.id}",
            headers={"Authorization": f"Bearer {make_access_token(admin_user)}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert any(p["marca"] == "Adidas" and p["categoria"] == "Ropa" for p in data["pares"])

    def test_titular_no_ve_grants_en_par_sin_titular(self, client, db, titular, par_sin_titular, grantee):
        """A titular has no writable scope over an untitled pair (usuario_id
        IS NULL), so such grants are FILTERED OUT of the response — this
        endpoint returns 200 with the pair absent, NOT a 403. It reads the
        CALLER's writable pairs rather than authorizing one specific pair,
        so there is no pair to forbid. Per-pair CRUD still 403s; that
        difference is intentional."""
        db.add(MarcaSubPM(marca=par_sin_titular.marca, categoria=par_sin_titular.categoria, usuario_id=grantee.id))
        db.commit()

        resp = client.get(
            f"/api/marcas-pm/sub-pms/usuario/{grantee.id}",
            headers=_headers(titular),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert not any(p["marca"] == "Adidas" and p["categoria"] == "Ropa" for p in data["pares"])

    def test_titular_ve_solo_grants_en_su_scope(self, client, db, titular, par, par_otro, grantee):
        db.add(MarcaSubPM(marca=par.marca, categoria=par.categoria, usuario_id=grantee.id, creado_por=titular.id))
        db.add(MarcaSubPM(marca=par_otro.marca, categoria=par_otro.categoria, usuario_id=grantee.id))
        db.commit()

        resp = client.get(f"/api/marcas-pm/sub-pms/usuario/{grantee.id}", headers=_headers(titular))
        assert resp.status_code == 200
        data = resp.json()
        marcas = {(p["marca"], p["categoria"]) for p in data["pares"]}
        assert marcas == {(par.marca, par.categoria)}

    def test_usuario_sin_grants_devuelve_vacio(self, client, db, titular, grantee):
        resp = client.get(f"/api/marcas-pm/sub-pms/usuario/{grantee.id}", headers=_headers(titular))
        assert resp.status_code == 200
        assert resp.json() == {"pares": [], "total": 0}

    def test_usuario_desconocido_404(self, client, db, titular):
        resp = client.get("/api/marcas-pm/sub-pms/usuario/999999", headers=_headers(titular))
        assert resp.status_code == 404


# ── GET /marcas-pm/sub-pms/conteos ──────────────────────────────────────


class TestConteosPorUsuario:
    def test_conteo_agregado_admin(self, client, db, admin_user, par, par_otro, grantee):
        db.add(MarcaSubPM(marca=par.marca, categoria=par.categoria, usuario_id=grantee.id))
        db.add(MarcaSubPM(marca=par_otro.marca, categoria=par_otro.categoria, usuario_id=grantee.id))
        db.commit()

        resp = client.get(
            "/api/marcas-pm/sub-pms/conteos",
            headers={"Authorization": f"Bearer {make_access_token(admin_user)}"},
        )
        assert resp.status_code == 200
        conteos = {c["usuario_id"]: c["total"] for c in resp.json()["conteos"]}
        assert conteos[grantee.id] == 2

    def test_conteo_agregado_titular_scoped(self, client, db, titular, par, par_otro, grantee):
        db.add(MarcaSubPM(marca=par.marca, categoria=par.categoria, usuario_id=grantee.id, creado_por=titular.id))
        db.add(MarcaSubPM(marca=par_otro.marca, categoria=par_otro.categoria, usuario_id=grantee.id))
        db.commit()

        resp = client.get("/api/marcas-pm/sub-pms/conteos", headers=_headers(titular))
        assert resp.status_code == 200
        conteos = {c["usuario_id"]: c["total"] for c in resp.json()["conteos"]}
        assert conteos[grantee.id] == 1

    def test_zero_grants_devuelve_lista_vacia(self, client, db, admin_user):
        """Production currently has 0 rows in marca_sub_pm — the aggregate
        MUST return an empty list rather than error or omit the shape."""
        resp = client.get(
            "/api/marcas-pm/sub-pms/conteos",
            headers={"Authorization": f"Bearer {make_access_token(admin_user)}"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"conteos": []}

    def test_una_sola_query_agregada(self, client, db, admin_user, par, par_otro, grantee, monkeypatch):
        """Guards against N+1: the endpoint must issue exactly one grouped
        aggregate query against marca_sub_pm, not one per user."""
        db.add(MarcaSubPM(marca=par.marca, categoria=par.categoria, usuario_id=grantee.id))
        db.add(MarcaSubPM(marca=par_otro.marca, categoria=par_otro.categoria, usuario_id=grantee.id))
        db.commit()

        from sqlalchemy.orm import Query

        original_all = Query.all
        calls = {"marca_sub_pm_queries": 0}

        def counting_all(self):
            if self.column_descriptions and any(
                "MarcaSubPM" in str(desc.get("entity")) for desc in self.column_descriptions
            ):
                calls["marca_sub_pm_queries"] += 1
            return original_all(self)

        monkeypatch.setattr(Query, "all", counting_all)

        resp = client.get(
            "/api/marcas-pm/sub-pms/conteos",
            headers={"Authorization": f"Bearer {make_access_token(admin_user)}"},
        )
        assert resp.status_code == 200
        assert calls["marca_sub_pm_queries"] == 1
