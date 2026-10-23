"""HTTP-level gate for `GET /api/dev/openapi.json` (the in-app API docs page).

`/api/docs` and `/api/openapi.json` are disabled outside development/testing, and a browser
navigation carries no Bearer token, so the frontend `/api-docs` page fetches the schema through
this endpoint instead. It must answer only to users holding `admin.ver_api_docs`, in every
environment. These tests go through the real HTTP stack so `require_permiso(...)` runs.
"""

from __future__ import annotations

from app.models.permiso import Permiso, RolPermisoBase

URL = "/api/dev/openapi.json"
PERMISO = "admin.ver_api_docs"


def _grant(db, rol, codigo: str) -> None:
    permiso = db.query(Permiso).filter(Permiso.codigo == codigo).first()
    if not permiso:
        permiso = Permiso(codigo=codigo, nombre=codigo, descripcion="", categoria="administracion", orden=999)
        db.add(permiso)
        db.flush()
    db.add(RolPermisoBase(rol_id=rol.id, permiso_id=permiso.id))
    db.commit()


class TestApiDocsPermiso:
    def test_without_token_gets_401_or_403(self, client) -> None:
        resp = client.get(URL)

        assert resp.status_code in (401, 403)

    def test_without_permission_gets_403(self, client, admin_auth_headers) -> None:
        resp = client.get(URL, headers=admin_auth_headers)

        assert resp.status_code == 403

    def test_with_permission_gets_the_full_schema(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, PERMISO)

        resp = client.get(URL, headers=admin_auth_headers)

        assert resp.status_code == 200
        schema = resp.json()
        assert schema["info"]["title"] == "Pricing API"
        assert "/api/varios-venta-pct" in schema["paths"]

    def test_the_endpoint_does_not_list_itself(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, PERMISO)

        paths = client.get(URL, headers=admin_auth_headers).json()["paths"]

        assert URL not in paths
