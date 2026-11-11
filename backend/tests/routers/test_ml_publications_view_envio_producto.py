"""S1, S5-S7: `GET/PUT /api/ml-publications/view/products/{item_id}/envio`, the shipping-cost choice of a product.

Same harness as `test_ml_publications_view.py`: permissions in the SQLite test database, the store (products,
publications, choices) in a throwaway Postgres schema. The mlwebhook costs and the units sold are stubbed; the
resolver's rules are pinned in `tests/services/ml_publications/view/test_envio_producto_postgres.py`, this file pins
the HTTP contract. Costs are RE200's production figures (L9); the units are synthetic weights.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.api.endpoints.pricing import PERMISOS_EDITAR_PRODUCTOS
from app.routers import ml_publications_view
from app.services import envio_real_service
from tests.routers.test_ml_publications_links import grant
from tests.routers.test_ml_publications_view import VER, pg as view_pg, seed_rows  # noqa: F401
from tests.services.ml_publications.conftest import mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed
from tests.services.ml_publications.view.test_envio_producto_postgres import CHOICE_DDL, add_publication

pytestmark = pytest.mark.postgres

URL = "/api/ml-publications/view/products/{}/envio"
EDITAR = "productos.editar_precio_clasica"
OWN, OUTLIER = "MLA1173065146", "MLA2517958828"
COSTS = {OWN: 7290.0, OUTLIER: 10890.0}


@pytest.fixture()
def pg(view_pg, monkeypatch):  # noqa: F811
    with view_pg.begin() as conn:
        conn.execute(text(CHOICE_DDL))
    monkeypatch.setattr(
        envio_real_service, "_query_list_cost_by_mla", lambda mlas: {m: COSTS[m] for m in mlas if m in COSTS}
    )
    return view_pg


@pytest.fixture()
def units(monkeypatch):
    calls: list[tuple[date, date]] = []
    sold = {OWN: 3, OUTLIER: 1}

    def read(db, mlas, date_from, date_to):
        calls.append((date_from, date_to))
        return {m: sold[m] for m in mlas if m in sold}

    monkeypatch.setattr(envio_real_service, "unidades_vendidas_por_mla", read)
    return calls


def fill(conn) -> None:
    seed.add_product(conn, 22, "C22", "RE200")
    add_publication(conn, OWN, 22)
    add_publication(conn, OUTLIER, 22)
    seed.add_product(conn, 90, "C90", "Otro")
    add_publication(conn, "MLA_OTHER", 90)


@pytest.fixture()
def reader(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER)
    return admin_auth_headers


@pytest.fixture()
def editor(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, VER, EDITAR)
    return admin_auth_headers


def stored(pg) -> list[tuple]:
    with pg.connect() as conn:
        return [tuple(r) for r in conn.execute(text("SELECT item_id, modo, mla FROM producto_envio_eleccion"))]


class TestOptions:
    def test_the_options_with_the_most_sold_flagged(self, client, pg, reader, units) -> None:
        seed_rows(pg, fill)
        response = client.get(
            URL.format(22), headers=reader, params={"date_from": "2026-10-01", "date_to": "2026-10-30"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["publicaciones"] == [
            {"mla": OWN, "costo": 7290.0, "unidades": 3, "mas_vendida": True},
            {"mla": OUTLIER, "costo": 10890.0, "unidades": 1, "mas_vendida": False},
        ]
        assert (body["promedio"], body["ponderado"], body["max"]) == (9090.0, 8190.0, 10890.0)
        assert body["eleccion"]["modo"] == "max" and body["eleccion"]["costo"] == 10890.0
        assert body["eleccion"]["warning"] is None
        assert units[0] == (date(2026, 10, 1), date(2026, 10, 30))

    def test_the_default_period_is_the_last_30_days(self, client, pg, reader, units) -> None:
        seed_rows(pg, fill)
        body = client.get(URL.format(22), headers=reader).json()
        today = envio_real_service.hoy()
        assert (body["date_from"], body["date_to"]) == ((today - timedelta(days=29)).isoformat(), today.isoformat())

    def test_a_period_backwards_is_422(self, client, pg, reader, units) -> None:
        seed_rows(pg, fill)
        response = client.get(
            URL.format(22), headers=reader, params={"date_from": "2026-10-30", "date_to": "2026-10-01"}
        )
        assert response.status_code == 422

    def test_an_unknown_product_is_404(self, client, pg, reader, units) -> None:
        assert client.get(URL.format(404), headers=reader).status_code == 404

    def test_without_the_screen_permission_is_403(self, client, pg, auth_headers, units) -> None:
        assert client.get(URL.format(22), headers=auth_headers).status_code == 403

    def test_mlwebhook_down_is_503_not_a_silent_empty_list(self, client, pg, reader, units, monkeypatch) -> None:
        seed_rows(pg, fill)

        def down(mlas):
            raise RuntimeError("mlwebhook unreachable")

        monkeypatch.setattr(envio_real_service, "_query_list_cost_by_mla", down)
        assert client.get(URL.format(22), headers=reader).status_code == 503


class TestSaveChoice:
    def test_the_permission_is_the_productos_clasica_price_edit(self) -> None:
        assert ml_publications_view.PERMISO_ELEGIR_ENVIO == EDITAR
        assert EDITAR in PERMISOS_EDITAR_PRODUCTOS

    def test_it_stores_the_choice_and_who(self, client, pg, editor, units, admin_user) -> None:
        seed_rows(pg, fill)
        response = client.put(URL.format(22), headers=editor, json={"modo": "mla", "mla": OWN})
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["modo"], body["mla"], body["usuario_id"]) == ("mla", OWN, admin_user.id)
        assert body["updated_at"]
        assert stored(pg) == [(22, "mla", OWN)]
        eleccion = client.get(URL.format(22), headers=editor).json()["eleccion"]
        assert (eleccion["modo"], eleccion["costo"]) == ("mla", 7290.0)

    def test_max_is_stored_as_max(self, client, pg, editor, units) -> None:
        seed_rows(pg, fill)
        client.put(URL.format(22), headers=editor, json={"modo": "mla", "mla": OWN})
        assert client.put(URL.format(22), headers=editor, json={"modo": "max"}).status_code == 200
        assert stored(pg) == [(22, "max", None)]

    def test_without_the_permission_is_403(self, client, pg, reader, units) -> None:
        seed_rows(pg, fill)
        response = client.put(URL.format(22), headers=reader, json={"modo": "promedio"})
        assert response.status_code == 403
        assert stored(pg) == []

    def test_an_mla_of_another_product_is_422(self, client, pg, editor, units) -> None:
        seed_rows(pg, fill)
        response = client.put(URL.format(22), headers=editor, json={"modo": "mla", "mla": "MLA_OTHER"})
        assert response.status_code == 422
        assert response.json()["error"]["field"] == "mla"
        assert stored(pg) == []

    @pytest.mark.parametrize(
        "payload",
        [{"modo": "mla"}, {"modo": "promedio", "mla": OWN}, {"modo": "barato"}],
    )
    def test_an_inconsistent_body_is_422(self, client, pg, editor, units, payload) -> None:
        seed_rows(pg, fill)
        assert client.put(URL.format(22), headers=editor, json=payload).status_code == 422
        assert stored(pg) == []

    def test_an_unknown_product_is_404(self, client, pg, editor, units) -> None:
        assert client.put(URL.format(404), headers=editor, json={"modo": "max"}).status_code == 404
