"""Permission matrix for Gestión Full router (view / depositos / gestor)."""

from __future__ import annotations

import pytest

BASE = "/api/gestion-full"
VIEW = "productos.ver"
DEPOSITOS = "gestion_full.depositos"
GESTOR = "gestion_full.gestor"


@pytest.fixture()
def viewer(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, VIEW)
    return admin_auth_headers


@pytest.fixture()
def depositos(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, VIEW)
    grant_permiso(rol_admin, DEPOSITOS)
    return admin_auth_headers


@pytest.fixture()
def gestor(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, VIEW)
    grant_permiso(rol_admin, GESTOR)
    return admin_auth_headers


VIEW_GETS = [
    f"{BASE}/envios",
    f"{BASE}/package",
]

DEPOSITOS_ENDPOINTS = [
    ("get", f"{BASE}/unidades-caja/pendientes", None),
    ("post", f"{BASE}/unidades-caja/import", {"rows": []}),
    ("patch", f"{BASE}/unidades-caja/1", {"unidades": 12}),
]

GESTOR_ENDPOINTS = [
    ("post", f"{BASE}/package/lines/from-ready", None),
    ("post", f"{BASE}/package/assign-inbound", {"inbound_id": "X", "line_ids": [1]}),
    ("post", f"{BASE}/package/remove-lines", {"line_ids": [1]}),
    ("get", f"{BASE}/package/export/ml", None),
]


@pytest.mark.parametrize("url", VIEW_GETS)
def test_view_endpoints_require_auth(client, url):
    assert client.get(url).status_code in (401, 403)


@pytest.mark.parametrize("url", VIEW_GETS)
def test_view_endpoints_forbid_without_view_perm(client, auth_headers, url):
    assert client.get(url, headers=auth_headers).status_code == 403


@pytest.mark.parametrize("url", VIEW_GETS)
def test_view_endpoints_allow_with_view_perm(client, viewer, url):
    # Business outcome may be 200 (empty list) or 404 (no package); never 403.
    assert client.get(url, headers=viewer).status_code in (200, 404)


@pytest.mark.parametrize("method,url,body", DEPOSITOS_ENDPOINTS)
def test_depositos_forbid_without_depositos_perm(client, viewer, method, url, body):
    kwargs = {"headers": viewer} | ({"json": body} if body is not None else {})
    assert getattr(client, method)(url, **kwargs).status_code == 403


@pytest.mark.parametrize("method,url,body", DEPOSITOS_ENDPOINTS)
def test_depositos_allow_with_depositos_perm(client, depositos, method, url, body):
    kwargs = {"headers": depositos} | ({"json": body} if body is not None else {})
    # Auth passed: 200/404/422 are fine; 403 means the guard is wrong.
    assert getattr(client, method)(url, **kwargs).status_code != 403


@pytest.mark.parametrize("method,url,body", GESTOR_ENDPOINTS)
def test_gestor_forbid_without_gestor_perm(client, viewer, method, url, body):
    kwargs = {"headers": viewer} | ({"json": body} if body is not None else {})
    assert getattr(client, method)(url, **kwargs).status_code == 403


@pytest.mark.parametrize("method,url,body", GESTOR_ENDPOINTS)
def test_gestor_allow_with_gestor_perm(client, gestor, method, url, body):
    kwargs = {"headers": gestor} | ({"json": body} if body is not None else {})
    assert getattr(client, method)(url, **kwargs).status_code != 403
