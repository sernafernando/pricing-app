"""RED/GREEN -- `app/routers/tiendas_oficiales.py`: any authenticated user
reads the official-store names; creating/editing needs
`admin.tiendas_oficiales`."""

from __future__ import annotations

from app.models.ml_tienda_oficial import MlTiendaOficial
from app.models.permiso import Permiso, RolPermisoBase

CODIGO = "admin.tiendas_oficiales"


def _grant(db, rol_admin) -> None:
    permiso = Permiso(codigo=CODIGO, nombre=CODIGO, descripcion="", categoria="configuracion", orden=90)
    db.add(permiso)
    db.flush()
    db.add(RolPermisoBase(rol_id=rol_admin.id, permiso_id=permiso.id))
    db.flush()


def _seed(db) -> None:
    db.add_all(
        [
            MlTiendaOficial(store_id=2, nombre="Beta", orden=2),
            MlTiendaOficial(store_id=1, nombre="Alfa", orden=1, clave="tplink"),
            MlTiendaOficial(store_id=3, nombre="Vieja", orden=0, activa=False),
        ]
    )
    db.flush()


class TestList:
    def test_requires_authentication(self, client) -> None:
        assert client.get("/api/tiendas-oficiales").status_code in (401, 403)

    def test_any_authenticated_user_lists_all_stores_ordered_including_inactive(self, db, client, auth_headers) -> None:
        _seed(db)
        resp = client.get("/api/tiendas-oficiales", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        # Inactive stores stay in the list: their sales still need a name.
        assert [r["store_id"] for r in body] == [3, 1, 2]
        assert body[1] == {"store_id": 1, "nombre": "Alfa", "clave": "tplink", "orden": 1, "activa": True}
        assert body[0]["activa"] is False


class TestCreate:
    def test_without_permission_is_403(self, db, client, auth_headers) -> None:
        resp = client.post("/api/tiendas-oficiales", json={"store_id": 9, "nombre": "X"}, headers=auth_headers)
        assert resp.status_code == 403
        assert db.get(MlTiendaOficial, 9) is None

    def test_creates_with_defaults(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin)
        resp = client.post(
            "/api/tiendas-oficiales", json={"store_id": 9, "nombre": "  Nueva  "}, headers=admin_auth_headers
        )
        assert resp.status_code == 201
        assert resp.json() == {"store_id": 9, "nombre": "Nueva", "clave": None, "orden": 0, "activa": True}

    def test_duplicate_store_id_is_409(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin)
        _seed(db)
        resp = client.post("/api/tiendas-oficiales", json={"store_id": 1, "nombre": "Otra"}, headers=admin_auth_headers)
        assert resp.status_code == 409

    def test_clave_is_normalized_and_may_be_shared(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin)
        _seed(db)
        resp = client.post(
            "/api/tiendas-oficiales",
            json={"store_id": 10, "nombre": "TP nuevo", "clave": " TPLink "},
            headers=admin_auth_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["clave"] == "tplink"

    def test_invalid_input_is_422(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin)
        for payload in (
            {"store_id": 0, "nombre": "X"},
            {"store_id": 5, "nombre": "   "},
            {"store_id": 5, "nombre": "X", "clave": "con espacios"},
        ):
            resp = client.post("/api/tiendas-oficiales", json=payload, headers=admin_auth_headers)
            assert resp.status_code == 422, payload


class TestUpdate:
    def test_without_permission_is_403(self, db, client, auth_headers) -> None:
        _seed(db)
        resp = client.put("/api/tiendas-oficiales/1", json={"nombre": "Hack"}, headers=auth_headers)
        assert resp.status_code == 403
        assert db.get(MlTiendaOficial, 1).nombre == "Alfa"

    def test_updates_only_the_sent_fields(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin)
        _seed(db)
        resp = client.put(
            "/api/tiendas-oficiales/1", json={"nombre": "Renombrada", "activa": False}, headers=admin_auth_headers
        )
        assert resp.status_code == 200
        assert resp.json() == {"store_id": 1, "nombre": "Renombrada", "clave": "tplink", "orden": 1, "activa": False}

    def test_clave_can_be_cleared_with_null(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin)
        _seed(db)
        resp = client.put("/api/tiendas-oficiales/1", json={"clave": None}, headers=admin_auth_headers)
        assert resp.status_code == 200
        assert resp.json()["clave"] is None

    def test_unknown_store_is_404(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin)
        resp = client.put("/api/tiendas-oficiales/404", json={"nombre": "X"}, headers=admin_auth_headers)
        assert resp.status_code == 404
