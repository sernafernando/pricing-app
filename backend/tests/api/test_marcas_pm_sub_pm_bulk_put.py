"""Tests for Slice 2 of sub-pm-bulk-assignment: PUT /marcas-pm/sub-pms/usuario/{usuario_id}.

Desired-set, fail-closed, single-transaction bulk assignment. Does NOT cover
the frontend (Slices 3/4).
"""

import pytest

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


def _put(client, usuario_id, pares, headers):
    return client.put(
        f"/api/marcas-pm/sub-pms/usuario/{usuario_id}",
        json={"pares": pares},
        headers=headers,
    )


@pytest.fixture()
def titular(db, rol_ventas) -> Usuario:
    return _make_user(db, rol_ventas, username="titular_put_t")


@pytest.fixture()
def otro_titular(db, rol_ventas) -> Usuario:
    return _make_user(db, rol_ventas, username="titular_put_o")


@pytest.fixture()
def grantee(db, rol_ventas) -> Usuario:
    return _make_user(db, rol_ventas, username="grantee_put_g")


@pytest.fixture()
def inactivo(db, rol_ventas) -> Usuario:
    return _make_user(db, rol_ventas, username="inactivo_put", activo=False)


@pytest.fixture()
def par(db, titular) -> MarcaPM:
    return _make_pair(db, marca="Nike", categoria="Zapatillas", titular=titular)


@pytest.fixture()
def par2(db, titular) -> MarcaPM:
    return _make_pair(db, marca="Adidas", categoria="Ropa", titular=titular)


@pytest.fixture()
def par_otro(db, otro_titular) -> MarcaPM:
    return _make_pair(db, marca="Puma", categoria="Remeras", titular=otro_titular)


@pytest.fixture()
def par_sin_titular(db) -> MarcaPM:
    return _make_pair(db, marca="Reebok", categoria="Botas", titular=None)


class TestBulkPutHappyPath:
    def test_grant_set_desde_vacio(self, client, db, titular, par, par2, grantee):
        resp = _put(
            client,
            grantee.id,
            [{"marca": par.marca, "categoria": par.categoria}, {"marca": par2.marca, "categoria": par2.categoria}],
            _headers(titular),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["otorgados"] == 2
        assert body["revocados"] == 0
        assert body["total"] == 2

        grants = db.query(MarcaSubPM).filter(MarcaSubPM.usuario_id == grantee.id).all()
        assert {(g.marca, g.categoria) for g in grants} == {
            (par.marca, par.categoria),
            (par2.marca, par2.categoria),
        }

    def test_revoke_via_omission(self, client, db, titular, par, par2, grantee):
        db.add(MarcaSubPM(marca=par.marca, categoria=par.categoria, usuario_id=grantee.id))
        db.add(MarcaSubPM(marca=par2.marca, categoria=par2.categoria, usuario_id=grantee.id))
        db.commit()

        resp = _put(client, grantee.id, [{"marca": par.marca, "categoria": par.categoria}], _headers(titular))
        assert resp.status_code == 200
        body = resp.json()
        assert body["otorgados"] == 0
        assert body["revocados"] == 1
        assert body["total"] == 1

        grants = db.query(MarcaSubPM).filter(MarcaSubPM.usuario_id == grantee.id).all()
        assert {(g.marca, g.categoria) for g in grants} == {(par.marca, par.categoria)}

    def test_mixed_add_and_remove(self, client, db, titular, par, par2, grantee):
        db.add(MarcaSubPM(marca=par.marca, categoria=par.categoria, usuario_id=grantee.id))
        db.commit()

        resp = _put(client, grantee.id, [{"marca": par2.marca, "categoria": par2.categoria}], _headers(titular))
        assert resp.status_code == 200
        body = resp.json()
        assert body["otorgados"] == 1
        assert body["revocados"] == 1
        assert body["total"] == 1

        grants = db.query(MarcaSubPM).filter(MarcaSubPM.usuario_id == grantee.id).all()
        assert {(g.marca, g.categoria) for g in grants} == {(par2.marca, par2.categoria)}

    def test_unchanged_set_es_noop(self, client, db, titular, par, grantee):
        db.add(MarcaSubPM(marca=par.marca, categoria=par.categoria, usuario_id=grantee.id))
        db.commit()

        resp = _put(client, grantee.id, [{"marca": par.marca, "categoria": par.categoria}], _headers(titular))
        assert resp.status_code == 200
        body = resp.json()
        assert body["otorgados"] == 0
        assert body["revocados"] == 0
        assert body["total"] == 1

    def test_admin_puede_asignar_par_sin_titular(self, client, db, admin_user, par_sin_titular, grantee):
        resp = _put(
            client,
            grantee.id,
            [{"marca": par_sin_titular.marca, "categoria": par_sin_titular.categoria}],
            {"Authorization": f"Bearer {make_access_token(admin_user)}"},
        )
        assert resp.status_code == 200
        assert resp.json()["otorgados"] == 1

        grants = db.query(MarcaSubPM).filter(MarcaSubPM.usuario_id == grantee.id).all()
        assert {(g.marca, g.categoria) for g in grants} == {(par_sin_titular.marca, par_sin_titular.categoria)}


class TestBulkPutFailClosed:
    def test_par_fuera_de_scope_rechaza_todo(self, client, db, titular, par, par_otro, grantee):
        resp = _put(
            client,
            grantee.id,
            [
                {"marca": par.marca, "categoria": par.categoria},
                {"marca": par_otro.marca, "categoria": par_otro.categoria},
            ],
            _headers(titular),
        )
        assert resp.status_code == 403
        body = resp.json()
        assert {"marca": par_otro.marca, "categoria": par_otro.categoria} in body["pares_rechazados"]

        assert db.query(MarcaSubPM).filter(MarcaSubPM.usuario_id == grantee.id).count() == 0

    def test_par_inexistente_rechaza_todo(self, client, db, titular, par, grantee):
        resp = _put(
            client,
            grantee.id,
            [
                {"marca": par.marca, "categoria": par.categoria},
                {"marca": "NoExiste", "categoria": "Tampoco"},
            ],
            _headers(titular),
        )
        assert resp.status_code == 403
        body = resp.json()
        assert {"marca": "NoExiste", "categoria": "Tampoco"} in body["pares_rechazados"]

        assert db.query(MarcaSubPM).filter(MarcaSubPM.usuario_id == grantee.id).count() == 0

    def test_titular_no_toca_grants_fuera_de_su_scope(self, client, db, titular, par, par_otro, otro_titular, grantee):
        """A titular's save must never touch grants on pairs outside their
        writable scope — those grants must survive the save untouched."""
        db.add(MarcaSubPM(marca=par_otro.marca, categoria=par_otro.categoria, usuario_id=grantee.id))
        db.commit()

        resp = _put(client, grantee.id, [{"marca": par.marca, "categoria": par.categoria}], _headers(titular))
        assert resp.status_code == 200

        ajeno = (
            db.query(MarcaSubPM)
            .filter(
                MarcaSubPM.marca == par_otro.marca,
                MarcaSubPM.categoria == par_otro.categoria,
                MarcaSubPM.usuario_id == grantee.id,
            )
            .first()
        )
        assert ajeno is not None

    def test_inactivo_rechazado(self, client, db, titular, par, inactivo):
        resp = _put(client, inactivo.id, [{"marca": par.marca, "categoria": par.categoria}], _headers(titular))
        assert resp.status_code == 400
        assert db.query(MarcaSubPM).filter(MarcaSubPM.usuario_id == inactivo.id).count() == 0

    def test_self_grant_rechazado(self, client, db, titular, par):
        resp = _put(client, titular.id, [{"marca": par.marca, "categoria": par.categoria}], _headers(titular))
        assert resp.status_code == 400
        assert db.query(MarcaSubPM).filter(MarcaSubPM.usuario_id == titular.id).count() == 0

    def test_usuario_desconocido_404(self, client, db, titular, par):
        resp = _put(client, 999999, [{"marca": par.marca, "categoria": par.categoria}], _headers(titular))
        assert resp.status_code == 404


class TestBulkPutEmpty:
    def test_set_vacio_revoca_todo(self, client, db, titular, par, grantee):
        db.add(MarcaSubPM(marca=par.marca, categoria=par.categoria, usuario_id=grantee.id))
        db.commit()

        resp = _put(client, grantee.id, [], _headers(titular))
        assert resp.status_code == 200
        body = resp.json()
        assert body["revocados"] == 1
        assert body["total"] == 0
        assert db.query(MarcaSubPM).filter(MarcaSubPM.usuario_id == grantee.id).count() == 0

    def test_set_vacio_contra_usuario_sin_grants_es_noop(self, client, db, titular, par, grantee):
        """The LIVE rollout path: production has zero rows in marca_sub_pm
        today, so on day one every save starts from an empty desired set
        against a target with zero existing grants. Must be an explicit
        no-op, not just "happens to work"."""
        resp = _put(client, grantee.id, [], _headers(titular))
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"otorgados": 0, "revocados": 0, "total": 0}
        assert db.query(MarcaSubPM).filter(MarcaSubPM.usuario_id == grantee.id).count() == 0


class TestBulkPutConcurrency:
    def test_integrity_error_en_commit_revierte_todo_y_409(self, client, db, titular, par, par2, grantee, monkeypatch):
        """Forces the IntegrityError -> rollback -> 409 path deterministically
        (real cross-session races are awkward to reproduce in a test). The
        contract has two halves and both must hold: the response is 409 AND
        the database is left EXACTLY as it was before the call — no partial
        grant, no partial revoke."""
        db.add(MarcaSubPM(marca=par.marca, categoria=par.categoria, usuario_id=grantee.id))
        db.commit()

        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.orm import Session as OrmSession

        def raising_commit(self):
            # Flush so the pending delete+insert actually reach the DB inside
            # the current SAVEPOINT (matching how a real IntegrityError is
            # normally raised — during flush, as part of commit's autoflush —
            # not by skipping flush entirely), then simulate the failure at
            # the point commit() would otherwise finalize. This keeps
            # SQLAlchemy's SAVEPOINT bookkeeping intact so the app's
            # subsequent real `db.rollback()` only undoes THIS request's
            # changes, not the test's already-committed fixture data.
            self.flush()
            raise IntegrityError("stmt", {}, Exception("duplicate key"))

        monkeypatch.setattr(OrmSession, "commit", raising_commit)

        # Desired set swaps par -> par2: one revoke, one grant, both must be
        # rolled back together.
        resp = _put(client, grantee.id, [{"marca": par2.marca, "categoria": par2.categoria}], _headers(titular))
        assert resp.status_code == 409

        monkeypatch.undo()

        grants = db.query(MarcaSubPM).filter(MarcaSubPM.usuario_id == grantee.id).all()
        assert {(g.marca, g.categoria) for g in grants} == {(par.marca, par.categoria)}
