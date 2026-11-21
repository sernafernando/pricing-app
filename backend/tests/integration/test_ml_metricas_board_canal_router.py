"""vpf-metricas-canal (T2): the `canal` / `costo` / `empresas` / `vendedores` params of the Métricas ML board, the
parts that need no fuera data: their validation (S1, S4, S10), the permissions (S7), and that `canal=ml` -- or no
`canal` at all -- answers byte for byte what the board answered before the param existed (S6).

The fuera SQL itself is exercised on real Postgres (`tests/services/ml_daily_metrics/test_board_canal_postgres.py`).
SQLite here, on the same seeded ML board as `test_ml_metricas_board_router` (clock frozen at 2026-09-30)."""

from __future__ import annotations

import hashlib
import json

import pytest

from tests.integration.test_ml_metricas_board_router import (  # noqa: F401 -- fixtures
    URL,
    _frozen_clock,
    _grant,
    bg_sessions,
    board_data,
)

FUERA = "ventas_fuera.ver_metricas_pdf"

# Every endpoint of the board, on the seeded ML data: (path, params).
ENDPOINTS = {
    "board": (URL, {"solo_con_ventas": "true", "sort": "markup"}),
    "board_group": (URL, {"group_by": "group", "dimension": "marca"}),
    "group_nodes": (f"{URL}/group-nodes", {"path": json.dumps(["Epson"]), "dimension": "marca"}),
    "envios": (f"{URL}/envios", {}),
    "export": (f"{URL}/export", {}),
    "publications": (f"{URL}/products/11/publications", {}),
}

# sha256 of each response body, recorded on the code BEFORE `canal` existed (origin/main 80c6dc9b5). A change to
# what the ML board answers fails here, naming the endpoint. `board`, `board_group` and `publications` re-recorded
# when `sell_in_out` gained `sell_in_estimados` (tactical sell in USD S10): removing that one key from those bodies
# gives the previous digests byte for byte. `board`, `board_group`, `publications` and `export` re-recorded when Costo SI
# T3 D1 dropped the sell in figures (`sell_in`, `sell_in_estimados`, `costo_sell_in`; the CSV's "Sell in" / "Costo c/
# sell in" columns, the c/ sell in/out headers renamed c/ SO): the bodies differ from the previous ones only by those.
BEFORE = {
    "board": "9f3a05ff1518dfebac6efeed6766b8e6a7c3354cc36e22d09ca60f0492562890",
    "board_group": "3719d8c1ecf38cdf369a1595d9fd7aecd75c8766ded6f44a476c26eb77130b87",
    "group_nodes": "cb5d47e33dd725b7e6ce2a1fdb8b36f73ddbdb0683a900a92bed8603ca567c25",
    "envios": "07fa64de8c9f2a887da307a3a76750d838c85def276035384b301ec41d59cd79",
    "export": "9131ce80a147a1cb81d6e81b8c31a9939fcd2a8370e1c439967066424e2af5a6",
    "publications": "27c1268ad11a3ce6a00805016b1edf17614a3512e345dd472917e0c923fad3c3",
}


def _body(client, headers, name: str, **extra: str) -> bytes:
    path, params = ENDPOINTS[name]
    resp = client.get(path, params={**params, **extra}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.content


class TestCanalMlIsTheBoardAsBefore:
    """S6: "Include a test proving canal=ml responses are byte-identical to before." (default = canal absent)."""

    @pytest.mark.usefixtures("board_data")
    @pytest.mark.parametrize("name", sorted(ENDPOINTS))
    def test_canal_ml_and_no_canal_answer_the_bytes_of_before(self, client, admin_auth_headers, name):
        before = _body(client, admin_auth_headers, name)
        explicit = _body(client, admin_auth_headers, name, canal="ml")
        # `costo` is a fuera choice: on the ML board it changes nothing either.
        with_costo = _body(client, admin_auth_headers, name, canal="ml", costo="costo")

        digest = hashlib.sha256(before).hexdigest()
        assert digest == BEFORE[name], f"{name}: {digest}"
        assert explicit == before
        assert with_costo == before


class TestParams:
    """S1, S4: canal=ml|fuera|todo (default ml), costo=costo_d|costo (default costo_d); 422 on anything else."""

    @pytest.mark.usefixtures("board_data")
    @pytest.mark.parametrize("params", [{"canal": "web"}, {"canal": "FUERA"}, {"costo": "costo_pp"}])
    def test_an_unknown_canal_or_costo_is_422(self, client, admin_auth_headers, params):
        resp = client.get(URL, params=params, headers=admin_auth_headers)

        assert resp.status_code == 422
        assert list(params.values())[0] in resp.text

    @pytest.mark.usefixtures("board_data")
    def test_fuera_by_publication_is_422(self, client, admin_auth_headers, rol_admin, db):
        """S10: "fuera + group_by=publication -> 422"."""
        _grant(db, rol_admin, FUERA)
        db.commit()

        resp = client.get(URL, params={"canal": "fuera", "group_by": "publication"}, headers=admin_auth_headers)

        assert resp.status_code == 422
        assert "publication" in resp.text


class TestPermissions:
    """S7, as vpf-metricas-canal-fe S5 changed it: canal=fuera requires ventas_fuera.ver_metricas_pdf, canal=todo also
    ml_metricas.ver (403 otherwise); tplink.solo users get 403 on fuera/todo."""

    @pytest.mark.usefixtures("board_data")
    @pytest.mark.parametrize("canal", ["fuera", "todo"])
    @pytest.mark.parametrize("name", sorted(ENDPOINTS))
    def test_without_the_fuera_permission_is_403(self, client, admin_auth_headers, canal, name):
        path, params = ENDPOINTS[name]

        resp = client.get(path, params={**params, "canal": canal}, headers=admin_auth_headers)

        assert resp.status_code == 403
        assert FUERA in resp.text

    # vpf-metricas-canal-fe S5 (L23): "fuera needs ver_metricas_pdf only, ml needs ml_metricas.ver, todo needs both"
    # -- canal=fuera with the PDF permission alone is 200 (`test_board_canal_split_postgres`).
    @pytest.mark.parametrize("canal", ["todo"])
    def test_the_fuera_permission_without_ml_metricas_ver_is_403(
        self, client, admin_auth_headers, rol_admin, db, canal
    ):
        _grant(db, rol_admin, FUERA)
        db.commit()

        resp = client.get(URL, params={"canal": canal}, headers=admin_auth_headers)

        assert resp.status_code == 403
        assert "ml_metricas.ver" in resp.text

    @pytest.mark.usefixtures("board_data")
    @pytest.mark.parametrize("canal", ["fuera", "todo"])
    def test_tplink_solo_is_403(self, client, admin_auth_headers, rol_admin, db, canal):
        _grant(db, rol_admin, FUERA, "tplink.solo")
        db.commit()

        resp = client.get(URL, params={"canal": canal}, headers=admin_auth_headers)

        assert resp.status_code == 403
        assert "tplink.solo" in resp.text

    @pytest.mark.usefixtures("board_data")
    def test_canal_ml_needs_no_fuera_permission(self, client, admin_auth_headers):
        assert client.get(URL, params={"canal": "ml"}, headers=admin_auth_headers).status_code == 200


def _dependencias(dependant) -> set:
    vistas = set()
    for sub in dependant.dependencies:
        vistas.add(sub.call)
        vistas |= _dependencias(sub)
    return vistas


def test_every_route_gated_by_canal_also_validates_canal() -> None:
    """`require_ver` picks the permission from the raw `canal` query (fuera needs only ventas_fuera.ver_metricas_pdf),
    so a route that used it without `board_filter` (which validates `canal` and applies it to the rows) would let a
    PDF-only user read ML data by sending canal=fuera."""
    from fastapi.routing import APIRoute

    from app.routers.ml_metricas import board_filter, require_ver, router

    rutas = [r for r in router.routes if isinstance(r, APIRoute)]
    con_gate = [r.path for r in rutas if require_ver in _dependencias(r.dependant)]
    assert len(con_gate) == 5, con_gate
    assert [r.path for r in rutas if r.path in con_gate and board_filter not in _dependencias(r.dependant)] == []
