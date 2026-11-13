"""marcas-sin-stock S5: the Admin exception list of brands kept visible without stock
(`app/routers/marcas_visibles.py`). Every route needs `admin.marcas_visibles`; the list
shows every brand of the catalog with its stock state; adding a brand makes it come back
to the option lists (`/api/marcas`), removing it hides it again."""

from __future__ import annotations

from app.models.marca_visible_excepcion import MarcaVisibleExcepcion
from app.models.permiso import Permiso, RolPermisoBase
from app.models.producto import ProductoERP

CODIGO = "admin.marcas_visibles"


def _grant(db, rol_admin) -> None:
    permiso = Permiso(codigo=CODIGO, nombre=CODIGO, descripcion="", categoria="configuracion", orden=91)
    db.add(permiso)
    db.flush()
    db.add(RolPermisoBase(rol_id=rol_admin.id, permiso_id=permiso.id))
    db.flush()


def _seed(db) -> None:
    db.add_all(
        [
            ProductoERP(item_id=1, codigo="E1", marca="Epson", stock=4),
            ProductoERP(item_id=2, codigo="E2", marca="EPSON", stock=0),
            ProductoERP(item_id=3, codigo="V1", marca="Vieja", stock=0),
        ]
    )
    db.flush()


def _marcas(client, headers) -> list:
    resp = client.get("/api/marcas", headers=headers)
    assert resp.status_code == 200
    return resp.json()["marcas"]


class TestPermission:
    def test_every_route_needs_the_permission(self, db, client, auth_headers) -> None:
        _seed(db)
        assert client.get("/api/marcas-visibles", headers=auth_headers).status_code == 403
        resp = client.post("/api/marcas-visibles/excepciones", json={"marca": "Vieja"}, headers=auth_headers)
        assert resp.status_code == 403
        db.add(MarcaVisibleExcepcion(marca="Vieja"))
        db.flush()
        row_id = db.query(MarcaVisibleExcepcion).one().id
        assert client.delete(f"/api/marcas-visibles/excepciones/{row_id}", headers=auth_headers).status_code == 403
        assert db.query(MarcaVisibleExcepcion).count() == 1


class TestAddRemove:
    def test_list_shows_every_brand_with_its_stock_state(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin)
        _seed(db)
        body = client.get("/api/marcas-visibles", headers=admin_auth_headers).json()
        assert body["excepciones"] == []
        assert {(m["marca"].upper(), m["con_stock"], m["en_excepcion"]) for m in body["marcas"]} == {
            ("EPSON", True, False),
            ("VIEJA", False, False),
        }

    def test_adding_a_brand_brings_it_back_and_removing_hides_it(
        self, db, client, admin_auth_headers, rol_admin, admin_user
    ) -> None:
        _grant(db, rol_admin)
        _seed(db)
        assert _marcas(client, admin_auth_headers) == ["EPSON", "Epson"]

        resp = client.post("/api/marcas-visibles/excepciones", json={"marca": " vieja "}, headers=admin_auth_headers)
        assert resp.status_code == 201
        created = resp.json()
        assert created["marca"] == "Vieja"
        assert created["con_stock"] is False
        assert created["creado_por"] == admin_user.nombre
        row = db.query(MarcaVisibleExcepcion).one()
        assert row.creado_por_id == admin_user.id
        assert "Vieja" in _marcas(client, admin_auth_headers)
        listed = client.get("/api/marcas-visibles", headers=admin_auth_headers).json()
        assert [(e["marca"], e["con_stock"]) for e in listed["excepciones"]] == [("Vieja", False)]

        resp = client.delete(f"/api/marcas-visibles/excepciones/{created['id']}", headers=admin_auth_headers)
        assert resp.status_code == 204
        assert db.query(MarcaVisibleExcepcion).count() == 0
        assert "Vieja" not in _marcas(client, admin_auth_headers)

    def test_a_duplicate_is_409_and_an_unknown_brand_404(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin)
        _seed(db)
        assert (
            client.post(
                "/api/marcas-visibles/excepciones", json={"marca": "Vieja"}, headers=admin_auth_headers
            ).status_code
            == 201
        )
        dup = client.post("/api/marcas-visibles/excepciones", json={"marca": "VIEJA"}, headers=admin_auth_headers)
        assert dup.status_code == 409
        unknown = client.post("/api/marcas-visibles/excepciones", json={"marca": "Nada"}, headers=admin_auth_headers)
        assert unknown.status_code == 404
        assert db.query(MarcaVisibleExcepcion).count() == 1

    def test_removing_a_missing_exception_is_404(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin)
        assert client.delete("/api/marcas-visibles/excepciones/999", headers=admin_auth_headers).status_code == 404
