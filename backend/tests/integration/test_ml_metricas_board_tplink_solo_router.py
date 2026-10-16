"""metricas-ml-tplink-mode P5b: `tplink.solo` on the Métricas ML board, enforced server-side.

A TP-only user (still needs `ml_metricas.ver`) reads only the TP store group (the `tplink` clave, matched on the
PUBLICATION's store; a client store filter is intersected, never widened), always at the TP cost, and never a Gauss
figure at any depth: no Total Gauss in the board, the sub-rows, the group nodes, the KPI strip or the CSV. No PM
filter (422), no PM scope, no PM facet; only the group+tienda, product and publication groupings (422 otherwise).
The Gauss figures are seeded with distinctive amounts so a leak shows up even under a renamed field.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import BaseModel

from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_tienda_oficial import MlTiendaOficial
from app.routers import ml_metricas
from app.services import pm_scope
from app.services.tplink_solo import es_tplink_solo
from tests.integration.test_ml_metricas_board_router import (  # noqa: F401 -- fixtures
    URL,
    _frozen_clock,
    _grant,
    _producto,
    _pub,
    bg_sessions,
)
from tests.services.ml_daily_metrics.seed import Line, seed_sale

_ORDER_IDS = iter(range(2000096000000001, 2000096000100000))
GAUSS, TP_OLD, TP_NEW = 57997, 2645, 471846
# Every Total Gauss amount the fixture can produce (per pair, per row, per period), in both decimal styles.
GAUSS_AMOUNTS = ("31.13", "23.17", "41.19", "54.3", "64.36", "95.49")
GAUSS_AMOUNTS_CSV = tuple(amount.replace(".", ",") for amount in GAUSS_AMOUNTS)
GAUSS_DENY = {"total_gauss", "tg", "prev_tg", "series_tg", "mtg", "mcosto", "costo_mercaderia"}


def _sale(db, product, mla, tg, costo_tp=None, total_tp=None) -> None:
    order_id = next(_ORDER_IDS)
    accredited = datetime.combine(date(2026, 9, 20), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=15)
    seed_sale(db, order_id, accredited, [Line(product, mla, 1, Decimal("200"))], tg=tg, costo="100")
    metrics = db.get(MlOrderMetrics, order_id)
    metrics.costo_tp = Decimal(costo_tp) if costo_tp is not None else None
    metrics.total_tp = Decimal(total_tp) if total_tp is not None else None
    metrics.tp_incompleto = costo_tp is None


@pytest.fixture()
def tienda(db):
    """11 sells in Gauss 57997 (MLA1) and in TP 2645 (MLA2, TP cost 50, Total TP 73.17); 12 sells only in TP
    471846 (MLA3) without a TP cost (incomplete)."""
    db.add_all(
        [
            MlTiendaOficial(store_id=GAUSS, nombre="Gauss", clave=None, orden=1, activa=True),
            MlTiendaOficial(store_id=TP_OLD, nombre="TP-Link vieja", clave="tplink", orden=2, activa=False),
            MlTiendaOficial(store_id=TP_NEW, nombre="TP-Link", clave="tplink", orden=3, activa=True),
        ]
    )
    _producto(db, 11, "Router AX55", "TP-Link")
    _producto(db, 12, "Switch", "TP-Link")
    db.flush()
    _pub(db, 1, "MLA1", 11, GAUSS)
    _pub(db, 2, "MLA2", 11, TP_OLD)
    _pub(db, 3, "MLA3", 12, TP_NEW)
    _sale(db, 11, "MLA1", "31.13")
    _sale(db, 11, "MLA2", "23.17", costo_tp="50", total_tp="73.17")
    _sale(db, 12, "MLA3", "41.19")
    db.flush()


@pytest.fixture()
def tp_solo(db, rol_admin, tienda):
    """TP-only, without the Gauss profit view: `tplink.solo` alone grants the TP figures."""
    _grant(db, rol_admin, "ml_metricas.ver", "tplink.solo")
    db.commit()


def _get(client, headers, suffix="", **params):
    resp = client.get(URL + suffix, params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _by_key(body):
    return {row["key"]: row for row in body["rows"]}


def _csv(client, headers, **params):
    resp = client.get(URL + "/export", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return list(csv.reader(io.StringIO(resp.text.lstrip("﻿")), delimiter=";"))


def _all_keys(obj) -> set:
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in _all_keys(v)}
    if isinstance(obj, list):
        return {k for v in obj for k in _all_keys(v)}
    return set()


class TestLockedToTheTpGroupAtTpCost:
    def test_the_board_reads_only_tp_store_pairs_at_tp_cost(self, client, admin_auth_headers, tp_solo) -> None:
        body = _get(client, admin_auth_headers, costos_tp="false")

        rows = _by_key(body)
        assert set(rows) == {"11", "12"}
        # Only MLA2 of product 11: its gross, Total TP and Markup TP (73.17 / 50).
        assert (rows["11"]["gross"], rows["11"]["total_tp"], rows["11"]["markup_pct"]) == (200.0, 73.17, 146.3)
        assert (rows["12"]["total_tp"], rows["12"]["tp_incompletos"], rows["12"]["markup_pct"]) == (None, 1, None)
        assert body["kpis"]["gross"]["value"] == 400.0
        assert body["kpis"]["total_tp"] == {"value": 73.17, "incompletos": 1}
        assert set(body["facets"]["stores"]) <= {str(TP_OLD), str(TP_NEW)}
        assert body["facets"]["stores_total"] == 2

    def test_a_client_store_filter_is_intersected_never_widened(self, client, admin_auth_headers, tp_solo) -> None:
        assert _get(client, admin_auth_headers, stores=str(GAUSS))["rows"] == []
        only_old = _by_key(_get(client, admin_auth_headers, stores=f"{GAUSS},{TP_OLD}"))
        assert set(only_old) == {"11"} and only_old["11"]["gross"] == 200.0

    def test_the_sub_rows_and_the_group_nodes_are_locked_too(self, client, admin_auth_headers, tp_solo) -> None:
        subs = _get(client, admin_auth_headers, "/products/11/publications")
        assert [row["mla"] for row in subs["rows"]] == ["MLA2"]
        assert subs["rows"][0]["is_best"] is True

        groups = _by_key(_get(client, admin_auth_headers, group_by="group", dimension="tienda"))
        assert set(groups) == {"c:tplink"}
        assert (groups["c:tplink"]["total_tp"], groups["c:tplink"]["tp_incompletos"]) == (73.17, 1)

        # The tienda tree opens into its brands: only the TP store's sales.
        brands = _by_key(_get(client, admin_auth_headers, "/group-nodes", path='["c:tplink"]', dimension="tienda"))
        assert set(brands) == {"TP-LINK"}
        assert (brands["TP-LINK"]["gross"], brands["TP-LINK"]["total_tp"]) == (400.0, 73.17)

    def test_it_still_needs_the_metricas_view(self, client, admin_auth_headers, db, rol_admin, tienda) -> None:
        _grant(db, rol_admin, "tplink.solo")
        db.commit()

        assert client.get(URL, headers=admin_auth_headers).status_code == 403

    def test_no_tp_store_configured_fails_closed(self, client, admin_auth_headers, db, tp_solo) -> None:
        db.query(MlTiendaOficial).filter(MlTiendaOficial.clave == "tplink").delete()
        db.commit()

        assert client.get(URL, headers=admin_auth_headers).status_code == 503
        assert client.get(URL + "/export", headers=admin_auth_headers).status_code == 503


class TestNoGaussFigureAtAnyDepth:
    def test_no_response_and_no_csv_carries_a_gauss_key_or_amount(self, client, admin_auth_headers, tp_solo) -> None:
        bodies = [
            _get(client, admin_auth_headers),
            _get(client, admin_auth_headers, group_by="publication", publicidad="mla"),
            _get(client, admin_auth_headers, group_by="group", dimension="tienda"),
            _get(client, admin_auth_headers, "/products/11/publications"),
            _get(client, admin_auth_headers, "/group-nodes", path='["c:tplink"]', dimension="tienda"),
        ]
        for body in bodies:
            assert _all_keys(body) & GAUSS_DENY == set()
            text = json.dumps(body)
            assert [amount for amount in GAUSS_AMOUNTS if amount in text] == []

        for params in ({}, {"group_by": "group", "dimension": "tienda"}, {"publicidad": "mla"}):
            lines = _csv(client, admin_auth_headers, **params)
            assert "Total Gauss" not in lines[0]
            assert {"Total TP", "TP incompletas", "Markup %"} <= set(lines[0])
            flat = ";".join(";".join(line) for line in lines)
            assert [amount for amount in GAUSS_AMOUNTS_CSV if amount in flat] == []

    def test_the_csv_carries_the_tp_figures(self, client, admin_auth_headers, tp_solo) -> None:
        lines = _csv(client, admin_auth_headers)
        header = lines[0]
        router = {line[0]: line for line in lines[1:]}["Router AX55"]

        assert (router[header.index("Total TP")], router[header.index("Markup %")]) == ("73,17", "146,30")

    def test_sorting_by_total_gauss_is_refused(self, client, admin_auth_headers, tp_solo) -> None:
        assert client.get(URL, params={"sort": "total_gauss"}, headers=admin_auth_headers).status_code == 422


class TestNoPmAndOnlyTheTpGroupings:
    def test_a_pm_filter_is_refused_and_no_pm_facet_is_returned(self, client, admin_auth_headers, tp_solo) -> None:
        assert client.get(URL, params={"pms": "5"}, headers=admin_auth_headers).status_code == 422
        assert _get(client, admin_auth_headers)["facets"]["product"]["pms"] == []

    def test_the_pm_scope_does_not_apply(self, client, admin_auth_headers, tp_solo, monkeypatch) -> None:
        monkeypatch.setattr(pm_scope, "get_pares_marca_categoria_usuario", lambda db, user: [])

        assert set(_by_key(_get(client, admin_auth_headers))) == {"11", "12"}

    @pytest.mark.parametrize("dimension", ["marca", "categoria", "subcategoria", "pm"])
    def test_any_other_grouping_is_refused(self, client, admin_auth_headers, tp_solo, dimension) -> None:
        board = client.get(URL, params={"group_by": "group", "dimension": dimension}, headers=admin_auth_headers)
        nodes = client.get(
            URL + "/group-nodes", params={"path": '["x"]', "dimension": dimension}, headers=admin_auth_headers
        )
        export = client.get(
            URL + "/export", params={"group_by": "group", "dimension": dimension}, headers=admin_auth_headers
        )

        assert (board.status_code, nodes.status_code, export.status_code) == (422, 422, 422)

    def test_product_and_publication_views_are_allowed(self, client, admin_auth_headers, tp_solo) -> None:
        assert set(_by_key(_get(client, admin_auth_headers, group_by="publication"))) == {"MLA2", "MLA3"}


def test_a_user_without_tplink_solo_still_sees_every_store_and_gauss(
    client, admin_auth_headers, db, rol_admin, tienda
) -> None:
    _grant(db, rol_admin, "ml_metricas.ver", "ml_metricas.ver_ganancia")
    db.commit()

    body = _get(client, admin_auth_headers)

    assert _by_key(body)["11"]["gross"] == 400.0
    assert body["kpis"]["total_gauss"]["value"] == 95.49
    assert body["kpis"]["total_tp"] is None


class TestResolvedOncePerRequest:
    @pytest.mark.parametrize(
        "suffix, params",
        [
            ("", {}),
            ("/products/11/publications", {}),
            ("/group-nodes", {"path": '["c:tplink"]', "dimension": "tienda"}),
            ("/export", {}),
        ],
    )
    def test_tplink_solo_is_looked_up_once(
        self, client, admin_auth_headers, tp_solo, monkeypatch, suffix, params
    ) -> None:
        calls = []

        def spy(db, user):
            calls.append(user.id)
            return es_tplink_solo(db, user)

        monkeypatch.setattr(ml_metricas, "es_tplink_solo", spy)

        assert client.get(URL + suffix, params=params, headers=admin_auth_headers).status_code == 200
        assert len(calls) == 1


class _NoProductFacets(BaseModel):
    facets: dict = {"stores": {"2645": 1}}
    total_gauss: float = 31.13


def test_the_sanitizer_tolerates_a_body_without_product_facets() -> None:
    body = json.loads(ml_metricas._tp_solo_response(_NoProductFacets()).body)

    assert body == {"facets": {"stores": {"2645": 1}}}
