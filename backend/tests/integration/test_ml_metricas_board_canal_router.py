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
# what the ML board answers fails here, naming the endpoint.
BEFORE = {
    "board": "e39b283da88ca18f24024cbe8413242c1453c153070afabf2d0d1437e88853bf",
    "board_group": "7f55a74566d2eb04fe86ac7d5c8bc85341e1ee0515959d42e2168c23ef456094",
    "group_nodes": "cb5d47e33dd725b7e6ce2a1fdb8b36f73ddbdb0683a900a92bed8603ca567c25",
    "envios": "07fa64de8c9f2a887da307a3a76750d838c85def276035384b301ec41d59cd79",
    "export": "ad65039d33e507128b511bb5dd12ea4bb5decce5f36e6bb39b3c695136043f07",
    "publications": "0564bad811fec400aa0522f8d3467288195a2e622c77a9036abc953329cad231",
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
    """S7: canal=fuera|todo require ml_metricas.ver AND ventas_fuera.ver_metricas_pdf (403 otherwise); tplink.solo
    users get 403 on fuera/todo."""

    @pytest.mark.usefixtures("board_data")
    @pytest.mark.parametrize("canal", ["fuera", "todo"])
    @pytest.mark.parametrize("name", sorted(ENDPOINTS))
    def test_without_the_fuera_permission_is_403(self, client, admin_auth_headers, canal, name):
        path, params = ENDPOINTS[name]

        resp = client.get(path, params={**params, "canal": canal}, headers=admin_auth_headers)

        assert resp.status_code == 403
        assert FUERA in resp.text

    @pytest.mark.parametrize("canal", ["fuera", "todo"])
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
