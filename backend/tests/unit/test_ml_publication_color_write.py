"""
Per-publication ML color writes (seleccion-por-publicacion S3).

`PUT /api/ml-publications/colors` paints, or with `color: null` unpaints, the given MLAs in one team layer
(`publicacion_color`). It never touches `producto_color`: the product keeps its color, and an unpainted
publication falls back to it. The layer rule is Productos' (`puede_escribir_layer`): a member of the team, or the
global layer with `productos.marcar_color` (`productos.marcar_color_lote` for more than one MLA). It also needs the
Publicaciones ML screen. Each write publishes `publicacion_color:changed`.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.models.equipo import ProductoColor, PublicacionColor
from app.models.producto import ProductoERP
from tests.unit.test_productos_colors_equipo import (
    _add_member,
    _global_equipo,
    _grant_marcar_color,
    _make_equipo,
    _make_usuario,
    auth_headers_for,
)

URL = "/api/ml-publications/colors"
SSE = "app.routers.ml_publication_color.sse_publish_bg"


def own(db, equipo_id: int) -> dict:
    rows = db.query(PublicacionColor).filter(PublicacionColor.equipo_id == equipo_id).all()
    return {row.item_id: row.color_ml for row in rows}


@pytest.fixture()
def team(db, rol_ventas):
    """A team with a member who may see Publicaciones ML, and product 77 painted green in that team."""
    _global_equipo(db)
    equipo = _make_equipo(db, "Ventas")
    user = _make_usuario(db, "pintor", rol_ventas.id)
    _add_member(db, equipo.id, user.id)
    _grant_marcar_color(db, rol_ventas.id, "productos.ver")
    db.add(ProductoERP(item_id=77, codigo="C77", descripcion="Router"))
    db.flush()
    db.add(ProductoColor(equipo_id=equipo.id, item_id=77, color_ml="verde"))
    db.commit()
    return equipo, auth_headers_for(user), user


def put(client, headers, **body):
    return client.put(URL, headers=headers, json=body)


class TestPaint:
    def test_paints_the_given_publications_only_in_that_team_and_publishes_them(self, client, db, team) -> None:
        equipo, headers, user = team
        with patch(SSE) as publish:
            response = put(client, headers, item_ids=["MLA1", "MLA2"], color="rojo", equipo_id=equipo.id)
        assert response.status_code == 200, response.text
        assert response.json() == {"count": 2, "color": "rojo"}
        assert own(db, equipo.id) == {"MLA1": "rojo", "MLA2": "rojo"}
        assert {row.updated_by for row in db.query(PublicacionColor).all()} == {user.id}
        # The product keeps its own color: a publication color never writes producto_color.
        assert db.query(ProductoColor).filter(ProductoColor.item_id == 77).one().color_ml == "verde"
        publish.assert_called_once_with(
            "publicacion_color:changed",
            {"equipo_id": equipo.id, "is_global": False, "item_ids": ["MLA1", "MLA2"], "color": "rojo"},
        )

    def test_repainting_replaces_the_color_without_a_second_row(self, client, db, team) -> None:
        equipo, headers, _ = team
        put(client, headers, item_ids=["MLA1"], color="rojo", equipo_id=equipo.id)
        assert put(client, headers, item_ids=["MLA1", "MLA1"], color="azul", equipo_id=equipo.id).status_code == 200
        assert own(db, equipo.id) == {"MLA1": "azul"}
        assert db.query(PublicacionColor).count() == 1

    def test_unpainting_deletes_the_publications_own_row_only_in_that_team(self, client, db, team) -> None:
        equipo, headers, user = team
        otro = _make_equipo(db, "Compras")
        _add_member(db, otro.id, user.id)
        db.add(PublicacionColor(equipo_id=otro.id, item_id="MLA1", color_ml="gris"))
        db.commit()
        put(client, headers, item_ids=["MLA1", "MLA2"], color="rojo", equipo_id=equipo.id)
        with patch(SSE) as publish:
            assert put(client, headers, item_ids=["MLA1"], color=None, equipo_id=equipo.id).status_code == 200
        assert own(db, equipo.id) == {"MLA2": "rojo"}
        assert own(db, otro.id) == {"MLA1": "gris"}
        assert db.query(ProductoColor).filter(ProductoColor.item_id == 77).one().color_ml == "verde"
        assert publish.call_args.args[1]["color"] is None


class TestWhoMayPaint:
    def test_a_non_member_is_403_and_nothing_is_written(self, client, db, team, rol_ventas) -> None:
        equipo, _, _ = team
        outsider = _make_usuario(db, "ajeno", rol_ventas.id)
        db.commit()
        with patch(SSE) as publish:
            response = put(client, auth_headers_for(outsider), item_ids=["MLA1"], color="rojo", equipo_id=equipo.id)
        assert response.status_code == 403
        assert db.query(PublicacionColor).count() == 0
        publish.assert_not_called()

    def test_without_the_publicaciones_ml_screen_it_is_403(self, client, db, rol_ventas) -> None:
        # A team member whose role was granted nothing: the layer alone does not open the screen's write.
        _global_equipo(db)
        equipo = _make_equipo(db, "Sin pantalla")
        user = _make_usuario(db, "sin_pantalla", rol_ventas.id)
        _add_member(db, equipo.id, user.id)
        db.commit()
        response = put(client, auth_headers_for(user), item_ids=["MLA1"], color="rojo", equipo_id=equipo.id)
        assert response.status_code == 403
        assert db.query(PublicacionColor).count() == 0

    def test_the_global_layer_needs_marcar_color_and_marcar_color_lote_for_several(
        self, client, db, rol_ventas
    ) -> None:
        global_id = _global_equipo(db).id
        _grant_marcar_color(db, rol_ventas.id, "productos.ver")
        user = _make_usuario(db, "global", rol_ventas.id)
        db.commit()
        headers = auth_headers_for(user)
        assert put(client, headers, item_ids=["MLA1"], color="rojo").status_code == 403
        _grant_marcar_color(db, rol_ventas.id)
        db.commit()
        with patch(SSE) as publish:
            assert put(client, headers, item_ids=["MLA1"], color="rojo").status_code == 200
        assert publish.call_args.args[1]["is_global"] is True
        assert put(client, headers, item_ids=["MLA1", "MLA2"], color="rojo").status_code == 403
        assert own(db, global_id) == {"MLA1": "rojo"}
        _grant_marcar_color(db, rol_ventas.id, "productos.marcar_color_lote")
        db.commit()
        assert put(client, headers, item_ids=["MLA1", "MLA2"], color="rojo").status_code == 200
        assert own(db, global_id) == {"MLA1": "rojo", "MLA2": "rojo"}


@pytest.mark.parametrize(
    "body",
    [
        {"item_ids": [f"MLA{n}" for n in range(501)], "color": "rojo"},  # over the bulk cap of 500
        {"item_ids": [], "color": "rojo"},
        {"item_ids": ["123"], "color": "rojo"},
        {"item_ids": ["MLA" + "1" * 28], "color": "rojo"},  # longer than the column's 30
        {"item_ids": ["MLA1"], "color": "fucsia"},
        {"item_ids": ["MLA1"]},
        {"item_ids": ["MLA1"], "color": "rojo", "producto_id": 77},
    ],
)
def test_an_invalid_request_is_422_and_writes_nothing(client, db, team, body) -> None:
    equipo, headers, _ = team
    assert put(client, headers, equipo_id=equipo.id, **body).status_code == 422
    assert db.query(PublicacionColor).count() == 0
