"""ODD `metricas-ml-scope-pm` T2: every `/ml-metricas` endpoint is bounded by the
caller's PM scope (`pm_scope`): a PM sees their `marcas_pm` pairs, a sub-PM the
union with `marca_sub_pm`, full-view callers (role or `ventas_ml.ver_todas_marcas`)
see everything and a caller with no pair sees nothing. The scope is resolved
server-side from the authenticated user -- never from the query -- and the `pms`
filter can only narrow it ("view as PM X" for a full-view user, no escalation
for a PM).

Same data as the board's router tests (`board_data`): products 11 Epson, 12
Lenovo, 13 DeWalt, 14 TP-Link, all in categoría "Cat". The scope SQL is
dialect-neutral, so these run on the SQLite suite like the rest of the router
tests; the Postgres side of the scope is covered by
`tests/services/ml_daily_metrics/test_board_pm_scope_postgres.py`."""

# ruff: noqa: F811 -- the imported fixtures are re-named by the tests that use them
from __future__ import annotations

import csv
import io
import json

import pytest

from app.core.security import get_password_hash
from app.models.marca_pm import MarcaPM
from app.models.marca_sub_pm import MarcaSubPM
from app.models.permiso import Permiso, RolPermisoBase
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from tests.conftest import TEST_PASSWORD, make_access_token
from tests.integration.test_ml_metricas_board_router import (  # noqa: F401 -- fixtures
    URL,
    _frozen_clock,
    _grant,
    bg_sessions,
    board_data,
)

NODES = f"{URL}/group-nodes"
EXPORT = f"{URL}/export"
ALL = {"11", "12", "13", "14"}


def _user(db, rol: Rol, username: str, *, activo: bool = True) -> Usuario:
    user = Usuario(
        username=username,
        email=f"{username}@example.com",
        nombre=username,
        password_hash=get_password_hash(TEST_PASSWORD),
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=activo,
    )
    db.add(user)
    db.flush()
    return user


def _headers(user: Usuario) -> dict:
    return {"Authorization": f"Bearer {make_access_token(user)}"}


@pytest.fixture()
def people(db, board_data, rol_ventas):
    """A PM (Epson), a sub-PM (own Lenovo + delegated TP-Link), a caller with
    no pair, one holding `ventas_ml.ver_todas_marcas`, and the admin."""
    _grant(db, rol_ventas, "ml_metricas.ver", "ml_metricas.ver_ganancia")
    todas = Rol(codigo="PRICING", nombre="Pricing", es_sistema=False, orden=11, activo=True)
    db.add(todas)
    db.flush()
    _grant(db, todas, "ml_metricas.ver", "ml_metricas.ver_ganancia")
    ver_todas = Permiso(codigo="ventas_ml.ver_todas_marcas", nombre="todas", categoria="ventas_ml", orden=1)
    db.add(ver_todas)
    db.flush()
    db.add(RolPermisoBase(rol_id=todas.id, permiso_id=ver_todas.id))

    ana = _user(db, rol_ventas, "ana")
    beto = _user(db, rol_ventas, "beto")
    nadie = _user(db, rol_ventas, "nadie")
    todo = _user(db, todas, "todo")
    db.add_all(
        [
            MarcaPM(marca="Epson", categoria="Cat", usuario_id=ana.id),
            MarcaPM(marca="Lenovo", categoria="Cat", usuario_id=beto.id),
            MarcaSubPM(marca="TP-Link", categoria="Cat", usuario_id=beto.id),
        ]
    )
    db.commit()
    return {"ana": ana, "beto": beto, "nadie": nadie, "todo": todo}


def _get(client, user, url=URL, **params):
    resp = client.get(url, params=params, headers=_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _keys(body):
    return {row["key"] for row in body["rows"]}


def _csv(resp):
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))


class TestBoard:
    def test_a_pm_sees_only_their_pairs(self, client, people):
        body = _get(client, people["ana"])

        assert _keys(body) == {"11"}
        assert body["total"] == 1
        assert body["kpis"]["units"]["value"] == 6

    def test_a_sub_pm_sees_the_union_of_their_own_and_delegated_pairs(self, client, people):
        assert _keys(_get(client, people["beto"])) == {"12", "14"}

    def test_the_admin_and_a_ver_todas_marcas_holder_see_everything(self, client, people, admin_auth_headers):
        assert _keys(_get(client, people["todo"])) == ALL
        resp = client.get(URL, headers=admin_auth_headers)
        assert {row["key"] for row in resp.json()["rows"]} == ALL

    def test_a_caller_with_no_pair_sees_nothing(self, client, people):
        body = _get(client, people["nadie"])

        assert body["rows"] == [] and body["total"] == 0
        assert body["kpis"]["units"]["value"] == 0
        assert body["facets"]["product"]["marcas"] == []

    def test_an_inactive_caller_cannot_reach_the_board(self, db, client, people, rol_ventas):
        gone = _user(db, rol_ventas, "gone", activo=False)
        db.add(MarcaSubPM(marca="Epson", categoria="Cat", usuario_id=gone.id))
        db.commit()

        assert client.get(URL, headers=_headers(gone)).status_code == 401

    def test_the_facets_offer_only_the_scoped_options(self, client, people):
        facets = _get(client, people["ana"])["facets"]

        assert facets["product"]["marcas"] == ["Epson"]
        assert facets["stores"] == {"57997": 1}

    def test_a_pm_cannot_widen_the_scope_with_marcas_or_pms(self, client, people):
        ana, beto = people["ana"], people["beto"]

        assert _get(client, ana, marcas="Lenovo")["rows"] == []
        assert _get(client, ana, marcas="Epson,Lenovo")["total"] == 1
        assert _get(client, ana, pms=str(beto.id))["rows"] == []
        assert _keys(_get(client, ana, pms=f"{ana.id},{beto.id}")) == {"11"}

    def test_a_full_view_caller_can_view_as_another_pm(self, client, people, admin_auth_headers):
        ana = people["ana"]
        resp = client.get(URL, params={"pms": str(ana.id)}, headers=admin_auth_headers)

        assert {row["key"] for row in resp.json()["rows"]} == {"11"}
        assert _keys(_get(client, people["todo"], pms=str(ana.id))) == {"11"}

    def test_the_grouped_top_level_is_scoped(self, client, people):
        body = _get(client, people["beto"], group_by="group", dimension="marca")

        assert _keys(body) == {"LENOVO", "TP-LINK"}
        assert body["total"] == 2


class TestPublications:
    def test_a_pm_gets_the_publications_of_their_products(self, client, people):
        body = _get(client, people["ana"], url=f"{URL}/products/11/publications")

        assert {row["key"] for row in body["rows"]} == {"MLA1", "MLA2"}

    def test_a_pm_gets_nothing_for_a_product_out_of_scope(self, client, people):
        assert _get(client, people["ana"], url=f"{URL}/products/12/publications")["rows"] == []

    def test_the_admin_still_reads_any_product(self, client, people, admin_auth_headers):
        resp = client.get(f"{URL}/products/12/publications", headers=admin_auth_headers)

        assert {row["key"] for row in resp.json()["rows"]} == {"MLA3"}


class TestGroupNodes:
    def _nodes(self, client, user, *path, dimension="marca", **params):
        return _get(client, user, url=NODES, path=json.dumps(list(path)), dimension=dimension, **params)

    def test_every_level_of_the_tree_is_scoped(self, client, people):
        ana = people["ana"]

        assert _keys(self._nodes(client, ana, "EPSON")) == {"CAT"}
        assert _keys(self._nodes(client, ana, "EPSON", "CAT")) == {"1"}
        assert _keys(self._nodes(client, ana, "EPSON", "CAT", "1")) == {"11"}

    def test_a_node_out_of_scope_opens_into_nothing_at_every_level(self, client, people):
        ana = people["ana"]

        for path in (("LENOVO",), ("LENOVO", "CAT"), ("LENOVO", "CAT", "2")):
            body = self._nodes(client, ana, *path)
            assert body["rows"] == [] and body["total"] == 0, path

    def test_other_dimensions_are_scoped_too(self, client, people):
        ana = people["ana"]

        assert _keys(self._nodes(client, ana, "CAT", dimension="categoria")) == {"1"}
        # Store 57997 also sells DeWalt (13): only Ana's brand opens under it.
        assert _keys(self._nodes(client, ana, "s:57997", dimension="tienda")) == {"EPSON"}
        assert self._nodes(client, ana, "1|CAT", dimension="subcategoria")["total"] == 1

    def test_the_admin_opens_any_node(self, client, people, admin_auth_headers):
        resp = client.get(
            NODES, params={"path": json.dumps(["LENOVO"]), "dimension": "marca"}, headers=admin_auth_headers
        )

        assert {row["key"] for row in resp.json()["rows"]} == {"CAT"}


class TestExport:
    def test_the_csv_holds_only_the_scoped_products(self, client, people):
        resp = client.get(EXPORT, headers=_headers(people["ana"]))

        assert resp.status_code == 200
        assert {line["SKU"] for line in _csv(resp)} == {"SKU-11"}

    def test_the_grouped_csv_holds_only_the_scoped_products(self, client, people):
        resp = client.get(EXPORT, params={"group_by": "group", "dimension": "marca"}, headers=_headers(people["beto"]))

        assert resp.status_code == 200
        assert {line["SKU"] for line in _csv(resp)} == {"SKU-12", "SKU-14"}

    def test_a_caller_with_no_pair_exports_only_the_header(self, client, people):
        assert _csv(client.get(EXPORT, headers=_headers(people["nadie"]))) == []

    def test_the_admin_exports_everything(self, client, people, admin_auth_headers):
        resp = client.get(EXPORT, headers=admin_auth_headers)

        assert {line["SKU"] for line in _csv(resp)} == {"SKU-11", "SKU-12", "SKU-13", "SKU-14"}

    def test_every_export_page_is_scoped(self, client, people, monkeypatch):
        from app.routers import ml_metricas

        monkeypatch.setattr(ml_metricas, "EXPORT_PAGE_SIZE", 1)
        resp = client.get(EXPORT, headers=_headers(people["beto"]))

        assert {line["SKU"] for line in _csv(resp)} == {"SKU-12", "SKU-14"}
