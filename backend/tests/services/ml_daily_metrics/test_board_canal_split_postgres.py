# ruff: noqa: F811 -- the imported pytest fixtures are test parameters
"""vpf-metricas-canal-fe T1 (C3): the Métricas ML board's gates per canal and what it adds when canal != ml.

- S5 (L23), verbatim: "fuera needs ver_metricas_pdf only, ml needs ml_metricas.ver, todo needs both."
- S6 (L24): Total Gauss / markup / cost figures: ml needs ml_metricas.ver_ganancia; fuera needs
  ventas_fuera.ver_ganancia; todo needs both.
- C3: rows[].canal, kpis.fuera, kpis.por_canal and kpis.gross.series_por_canal (todo only), facets.alerts.sin_producto
  with alerts=sin_producto, facets.empresa_documentos. canal=ml answers as before (pinned by
  `test_ml_metricas_board_canal_router`).

Real Postgres through the HTTP API, on the fixtures of `test_board_canal_postgres` (every document, product and amount
INVENTED; "today" 2026-09-30, default period 2026-09-01..30).
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timezone

import pytest

from app.models.venta_fuera_pdf import VentaFueraPdfCarga
from tests.services.ml_daily_metrics.test_board_canal_postgres import (  # noqa: F401 -- fixtures
    CABLE,
    EMPRESA,
    LIBRO,
    MONITOR,
    PERMISOS,
    URL,
    VENDEDOR,
    Ln,
    _client,
    _doc,
    _env,
    _get,
    _libro,
    _ml_sale,
    _monitor,
    _products,
    _rows,
    client,
    conn,
    db,
    fuera_engine,
)

pytestmark = pytest.mark.postgres

VER_ML, VER_FUERA = "ml_metricas.ver", "ventas_fuera.ver_metricas_pdf"
GAN_ML, GAN_FUERA = "ml_metricas.ver_ganancia", "ventas_fuera.ver_ganancia"
OTRA = "OTRA EMPRESA SRL"


def _endpoints() -> list[tuple[str, dict]]:
    return [
        (URL, {}),
        (URL, {"group_by": "group", "dimension": "marca"}),
        (f"{URL}/group-nodes", {"dimension": "marca", "path": json.dumps(["MARCAUNO"])}),
        (f"{URL}/export", {}),
        (f"{URL}/envios", {}),
        (f"{URL}/products/{MONITOR}/publications", {}),
    ]


def _endpoints_ml_todo() -> list[tuple[str, dict]]:
    """`_endpoints` plus the board by publication: ML-only, so canal=fuera refuses it (422) before any gate."""
    return [*_endpoints(), (URL, {"group_by": "publication"})]


def _seed_todo(db) -> None:
    """MONITOR sold by ML and por fuera ("ambos"), LIBRO only by ML, a cable without product only por fuera."""
    _products(db)
    _ml_sale(db, MONITOR, "MLA9001", date(2026, 9, 5), gross="200", tg="30", costo="100")
    _ml_sale(db, LIBRO, "MLA9002", date(2026, 9, 6), gross="200", tg="30", costo="100")
    _doc(db, date(2026, 9, 10), "1210", [_monitor("1000", "800")])
    _doc(db, date(2026, 9, 12), "121", [Ln("100", "50", codigo=CABLE, articulo="Cable Ejemplo")])


class TestGatePorCanal:
    """S5 on every board endpoint."""

    @pytest.mark.parametrize(("path", "params"), _endpoints())
    def test_the_pdf_permission_alone_opens_canal_fuera(self, conn, db, monkeypatch, path, params) -> None:
        _seed_todo(db)

        resp = _client(conn, monkeypatch, {VER_FUERA}).get(path, params={**params, "canal": "fuera"})

        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize("canal", ["ml", "todo"])
    @pytest.mark.parametrize(("path", "params"), _endpoints_ml_todo())
    def test_without_ml_metricas_ver_ml_and_todo_are_403(self, conn, db, monkeypatch, path, params, canal) -> None:
        resp = _client(conn, monkeypatch, {VER_FUERA, GAN_FUERA}).get(path, params={**params, "canal": canal})

        assert resp.status_code == 403
        assert VER_ML in resp.text

    def test_without_canal_the_pdf_permission_alone_is_403(self, conn, monkeypatch) -> None:
        assert _client(conn, monkeypatch, {VER_FUERA}).get(URL).status_code == 403

    @pytest.mark.parametrize("canal", ["fuera", "todo"])
    def test_tplink_solo_stays_403(self, conn, monkeypatch, canal) -> None:
        resp = _client(conn, monkeypatch, PERMISOS | {"tplink.solo"}).get(URL, params={"canal": canal})

        assert resp.status_code == 403
        assert "tplink.solo" in resp.text


def _margin_shown(c, canal: str) -> bool:
    """Whether every board endpoint of `canal` shows the margin, asserting they all agree."""
    board = _get(c, canal=canal)
    grouped = _get(c, canal=canal, group_by="group", dimension="marca")
    nodes = _get(c, f"{URL}/group-nodes", canal=canal, dimension="marca", path=json.dumps(["MARCAUNO"]))
    header = next(
        csv.reader(io.StringIO(c.get(f"{URL}/export", params={"canal": canal}).text.lstrip("﻿")), delimiter=";")
    )
    sort = c.get(URL, params={"canal": canal, "sort": "markup"}).status_code
    shown = [
        board["can_see_margin"],
        board["kpis"]["total_gauss"]["value"] is not None,
        board["rows"][0]["total_gauss"] is not None,
        grouped["rows"][0]["total_gauss"] is not None,
        nodes["rows"][0]["total_gauss"] is not None,
        "Total Gauss" in header,
        sort == 200,
    ]
    assert len(set(shown)) == 1, shown
    return shown[0]


class TestMargenPorCanal:
    """S6 on the board, the group view, its nodes, the export and the margin sort."""

    @pytest.mark.parametrize(
        ("canal", "ganancia", "visible"),
        [
            ("fuera", {GAN_FUERA}, True),
            ("fuera", {GAN_ML}, False),
            ("todo", {GAN_ML, GAN_FUERA}, True),
            ("todo", {GAN_ML}, False),
            ("todo", {GAN_FUERA}, False),
            ("ml", {GAN_ML}, True),
            ("ml", {GAN_FUERA}, False),
        ],
    )
    def test_the_margin_follows_the_canal_permission(self, conn, db, monkeypatch, canal, ganancia, visible) -> None:
        _seed_todo(db)
        c = _client(conn, monkeypatch, {VER_ML, VER_FUERA} | ganancia)

        assert _margin_shown(c, canal) is visible

    def test_the_403_names_the_canal_permission(self, conn, db, monkeypatch) -> None:
        _seed_todo(db)

        resp = _client(conn, monkeypatch, {VER_FUERA, GAN_ML}).get(URL, params={"canal": "fuera", "sort": "markup"})

        assert resp.status_code == 403
        assert GAN_FUERA in resp.text


class TestCanalDeLaFila:
    def test_todo_rows_say_where_their_sales_come_from(self, client, db) -> None:
        _seed_todo(db)

        rows = _rows(_get(client, canal="todo"))

        assert {t: r["canal"] for t, r in rows.items()} == {
            "Monitor Ejemplo 24": "ambos",
            "Libro Ejemplo": "ml",
            "Cable Ejemplo": "fuera",
        }

    def test_fuera_rows_are_fuera_and_ml_rows_carry_no_canal(self, client, db) -> None:
        _seed_todo(db)

        assert {r["canal"] for r in _get(client, canal="fuera")["rows"]} == {"fuera"}
        assert all("canal" not in r for r in _get(client, canal="ml")["rows"])

    def test_group_rows_and_their_nodes_carry_it(self, client, db) -> None:
        _seed_todo(db)

        grouped = _get(client, canal="todo", group_by="group", dimension="marca")
        nodes = _get(client, f"{URL}/group-nodes", canal="todo", dimension="marca", path=json.dumps(["MARCAUNO"]))
        ml_nodes = _get(client, f"{URL}/group-nodes", canal="ml", dimension="marca", path=json.dumps(["MARCAUNO"]))

        assert {r["title"]: r["canal"] for r in grouped["rows"]}["MarcaUno"] == "ambos"
        assert [r["canal"] for r in nodes["rows"]] == ["ambos"]
        assert all("canal" not in r for r in ml_nodes["rows"])

    def test_todo_by_publication_answers(self, conn, db, monkeypatch) -> None:
        """Publication rows are ML publications (the ML lines only): canal "ml", and nothing por fuera in the strip."""
        _seed_todo(db)
        c = _client(conn, monkeypatch, {VER_ML, VER_FUERA, GAN_ML, GAN_FUERA})

        resp = c.get(URL, params={"canal": "todo", "group_by": "publication"})

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert sorted(r["mla"] for r in body["rows"]) == ["MLA9001", "MLA9002"]
        assert {r["canal"] for r in body["rows"]} == {"ml"}
        kpis = body["kpis"]
        assert kpis["por_canal"]["fuera"] == {"units": 0, "gross": 0.0, "margin": 0.0, "markup_pct": None}
        assert kpis["por_canal"]["ml"]["gross"] == kpis["gross"]["value"] == 400.0
        assert not any(kpis["gross"]["series_por_canal"]["fuera"])
        assert kpis["gross"]["series_por_canal"]["ml"] == kpis["gross"]["series"]
        assert (kpis["fuera"]["comprobantes"], kpis["fuera"]["sin_producto"]["lineas"]) == (0, 0)


class TestCostoDeLaFila:
    """C5: rows[].costo when canal != ml -- the row's period cost with the chosen `costo` for its fuera lines and the
    ML cost for its ML lines; null without the S6 margin permission and for the rows without product."""

    def test_todo_rows_add_both_channels_costs(self, client, db) -> None:
        _seed_todo(db)

        rows = _rows(_get(client, canal="todo"))
        costo = _rows(_get(client, canal="todo", costo="costo"))

        # Monitor: ML 100 + fuera 800 x 1.065 (costo_d) = 952, or 100 + 800 with costo.
        assert {t: r["costo"] for t, r in rows.items()} == {
            "Monitor Ejemplo 24": 952.0,
            "Libro Ejemplo": 100.0,
            "Cable Ejemplo": None,
        }
        assert costo["Monitor Ejemplo 24"]["costo"] == 900.0

    def test_fuera_rows_and_the_group_view_carry_it(self, client, db) -> None:
        _seed_todo(db)

        fuera = _rows(_get(client, canal="fuera"))
        nodes = _get(client, f"{URL}/group-nodes", canal="todo", dimension="marca", path=json.dumps(["MARCAUNO"]))
        grouped = _get(client, canal="todo", group_by="group", dimension="marca")

        assert {t: r["costo"] for t, r in fuera.items()} == {"Monitor Ejemplo 24": 852.0, "Cable Ejemplo": None}
        assert [r["costo"] for r in nodes["rows"]] == [952.0]
        assert {r["title"]: r["costo"] for r in grouped["rows"]}["MarcaUno"] == 952.0

    @pytest.mark.parametrize(("canal", "ganancia"), [("fuera", {GAN_ML}), ("todo", {GAN_ML}), ("todo", {GAN_FUERA})])
    def test_null_without_the_canal_profit_view(self, conn, db, monkeypatch, canal, ganancia) -> None:
        _seed_todo(db)
        c = _client(conn, monkeypatch, {VER_ML, VER_FUERA} | ganancia)

        assert {r["costo"] for r in _get(c, canal=canal)["rows"]} == {None}

    def test_the_ml_board_has_no_costo(self, client, db) -> None:
        _seed_todo(db)

        assert all("costo" not in r for r in _get(client, canal="ml")["rows"])


class TestKpisFuera:
    def _seed(self, db) -> None:
        _products(db)
        # CHEQUE 30 D: book (10.5%) and a manual freight (21%) -> (2210 + 121) x 1.04; the 84 surcharge apart.
        _doc(
            db,
            date(2026, 9, 10),
            "2424.24",
            [_libro("2000", "1500"), Ln("100", "40", articulo="Flete Ejemplo")],
            condicion="CHEQUE 30 D",
            recargo="84",
        )
        _doc(db, date(2026, 9, 11), "-1210", [_monitor("-1000", "-800", cantidad="-1")], tipo="Nc")
        for empresa, vendedor, creado in ((EMPRESA, None, 20), (OTRA, "Vendedor Dos", 25)):
            db.add(
                VentaFueraPdfCarga(
                    empresa=empresa,
                    vendedor=vendedor,
                    desde=date(2026, 9, 1),
                    hasta=date(2026, 9, 15),
                    archivo_detallado="detallada.pdf",
                    documentos=0,
                    reemplazados=0,
                    avisos=[],
                    created_at=datetime(2026, 9, creado, 12, 0, tzinfo=timezone.utc),
                )
            )
        db.flush()

    def test_the_fuera_block(self, client, db) -> None:
        self._seed(db)

        fuera = _get(client, canal="fuera")["kpis"]["fuera"]

        assert (fuera["comprobantes"], fuera["recargo_cheque"]) == (2, 84.0)
        assert fuera["por_tipo"] == [
            {"tipo": "Fc", "letra": "A", "cantidad": 1},
            {"tipo": "Nc", "letra": "A", "cantidad": 1},
        ]
        assert fuera["sin_producto"] == {"lineas": 1, "monto": 121.0}
        # The other basis of costo_d is costo: (2000 - 1500) + (100 - 40) + (-1000 + 800) = 360 over 1540 - 800 = 740.
        assert fuera["otro_costo"] == {"costo": "costo", "margin": 360.0, "markup_pct": round(360 / 740 * 100, 1)}
        assert fuera["ultimo_pdf"] == {
            "created_at": "2026-09-25T12:00:00Z",
            "empresa": OTRA,
            "vendedor": "Vendedor Dos",
        }

    def test_it_follows_the_rows_the_board_keeps_and_the_empresa_filter(self, client, db) -> None:
        self._seed(db)

        libro = _get(client, canal="fuera", marcas="MarcaDos")["kpis"]["fuera"]
        empresa = _get(client, canal="fuera", empresas=EMPRESA, costo="costo")["kpis"]["fuera"]

        assert (libro["comprobantes"], libro["recargo_cheque"], libro["sin_producto"]["lineas"]) == (1, 84.0, 0)
        assert empresa["ultimo_pdf"]["empresa"] == EMPRESA
        assert empresa["otro_costo"]["costo"] == "costo_d"

    def test_the_other_cost_needs_the_fuera_profit_view(self, conn, db, monkeypatch) -> None:
        self._seed(db)

        fuera = _get(_client(conn, monkeypatch, {VER_FUERA}), canal="fuera")["kpis"]["fuera"]

        assert fuera["otro_costo"] == {"costo": "costo", "margin": None, "markup_pct": None}
        assert fuera["comprobantes"] == 2

    def test_no_upload_is_a_null_ultimo_pdf(self, client, db) -> None:
        _seed_todo(db)

        assert _get(client, canal="todo")["kpis"]["fuera"]["ultimo_pdf"] is None


class TestPorCanal:
    def test_todo_splits_the_strip_and_the_daily_venta_by_channel(self, client, db) -> None:
        _seed_todo(db)

        kpis = _get(client, canal="todo")["kpis"]

        # ML: 2 x (200, Total Gauss 30, cost 100). Fuera (costo_d): monitor 1000 - 852, cable 100 - 53.25.
        assert kpis["por_canal"] == {
            "ml": {"units": 2, "gross": 400.0, "margin": 60.0, "markup_pct": 30.0},
            "fuera": {"units": 2, "gross": 1331.0, "margin": 194.75, "markup_pct": round(194.75 / 905.25 * 100, 1)},
        }
        series = kpis["gross"]["series_por_canal"]
        assert (len(series["ml"]), len(series["fuera"])) == (30, 30)
        assert {i + 1: v for i, v in enumerate(series["ml"]) if v} == {5: 200.0, 6: 200.0}
        assert {i + 1: v for i, v in enumerate(series["fuera"]) if v} == {10: 1210.0, 12: 121.0}
        assert [a + b for a, b in zip(series["ml"], series["fuera"])] == kpis["gross"]["series"]

    def test_without_the_profit_view_the_split_has_no_margin(self, conn, db, monkeypatch) -> None:
        _seed_todo(db)

        por_canal = _get(_client(conn, monkeypatch, {VER_ML, VER_FUERA, GAN_ML}), canal="todo")["kpis"]["por_canal"]

        assert por_canal["ml"] == {"units": 2, "gross": 400.0, "margin": None, "markup_pct": None}

    def test_fuera_has_no_split_and_ml_has_no_fuera_block(self, client, db) -> None:
        _seed_todo(db)

        fuera = _get(client, canal="fuera")["kpis"]
        ml = _get(client, canal="ml")

        assert "por_canal" not in fuera and "series_por_canal" not in fuera["gross"]
        assert not {"fuera", "por_canal"} & set(ml["kpis"]) and "series_por_canal" not in ml["kpis"]["gross"]
        assert "empresa_documentos" not in ml["facets"] and "sin_producto" not in ml["facets"]["alerts"]


class TestSinProductoYEmpresas:
    def test_the_alert_counts_and_filters_the_rows_without_product(self, client, db) -> None:
        _seed_todo(db)

        body = _get(client, canal="todo")
        solo = _get(client, canal="todo", alerts="sin_producto")

        assert body["facets"]["alerts"]["sin_producto"] == 1
        assert _rows(body)["Cable Ejemplo"]["alerts"] == ["sin_producto"]
        assert list(_rows(solo)) == ["Cable Ejemplo"]

    def test_the_alert_is_not_the_ml_board_s(self, client, db) -> None:
        resp = client.get(URL, params={"canal": "ml", "alerts": "sin_producto"})

        assert resp.status_code == 422

    def test_documents_per_company_follow_the_period_and_the_vendedor_filter(self, client, db) -> None:
        _products(db)
        _doc(db, date(2026, 9, 10), "1210", [_monitor()])
        _doc(db, date(2026, 9, 11), "1210", [_monitor(), _monitor()])
        _doc(db, date(2026, 9, 12), "1210", [_monitor()], empresa=OTRA, vendedor="Vendedor Dos")
        _doc(db, date(2026, 8, 12), "1210", [_monitor()], empresa=OTRA, vendedor="Vendedor Dos")

        assert _get(client, canal="fuera")["facets"]["empresa_documentos"] == {EMPRESA: 2, OTRA: 1}
        narrowed = _get(client, canal="todo", vendedores="Vendedor Dos", empresas=EMPRESA)["facets"]
        assert narrowed["empresa_documentos"] == {OTRA: 1}

    def test_documents_per_salesperson_follow_the_period_and_the_empresa_filter(self, client, db) -> None:
        """C5 `facets.vendedor_documentos`: narrowed by the empresa filter, never by the vendedor one."""
        _products(db)
        _doc(db, date(2026, 9, 10), "1210", [_monitor()])
        _doc(db, date(2026, 9, 11), "1210", [_monitor(), _monitor()])
        _doc(db, date(2026, 9, 12), "1210", [_monitor()], empresa=OTRA, vendedor="Vendedor Dos")
        _doc(db, date(2026, 8, 12), "1210", [_monitor()], empresa=OTRA, vendedor="Vendedor Dos")

        assert _get(client, canal="fuera")["facets"]["vendedor_documentos"] == {VENDEDOR: 2, "Vendedor Dos": 1}
        narrowed = _get(client, canal="todo", vendedores="Vendedor Dos", empresas=EMPRESA)["facets"]
        assert narrowed["vendedor_documentos"] == {VENDEDOR: 2}
        assert "vendedor_documentos" not in _get(client, canal="ml")["facets"]
