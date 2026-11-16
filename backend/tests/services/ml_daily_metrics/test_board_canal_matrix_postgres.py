# ruff: noqa: F811 -- the imported pytest fixtures are test parameters
"""vpf-metricas-canal-fe T1: the S5 gate matrix on every board endpoint, S6 with no margin anywhere, and the C3 "Por
fuera" figures against the rows. Invented data only (test_board_canal_postgres fixtures)."""

from __future__ import annotations

import csv
import io
import json
from datetime import date

import pytest

from tests.services.ml_daily_metrics.test_board_canal_postgres import (  # noqa: F401 -- fixtures
    CABLE,
    LIBRO,
    MONITOR,
    URL,
    Ln,
    _client,
    _doc,
    _env,
    _libro,
    _ml_sale,
    _monitor,
    _products,
    conn,
    db,
    fuera_engine,
)

pytestmark = pytest.mark.postgres

VER_ML, VER_FUERA = "ml_metricas.ver", "ventas_fuera.ver_metricas_pdf"
GAN_ML, GAN_FUERA = "ml_metricas.ver_ganancia", "ventas_fuera.ver_ganancia"
TP = "tplink.solo"


def _seed(db) -> None:
    _products(db)
    _ml_sale(db, MONITOR, "MLA9001", date(2026, 9, 5), gross="200", tg="30", costo="100")
    _ml_sale(db, LIBRO, "MLA9002", date(2026, 9, 6), gross="300", tg="40", costo="150")
    _doc(db, date(2026, 9, 10), "1210", [_monitor("1000", "800")])
    _doc(
        db,
        date(2026, 9, 11),
        "2424.24",
        [_libro("2000", "1500"), Ln("100", "40", articulo="Flete Ejemplo")],
        condicion="CHEQUE 30 D",
        recargo="84",
    )
    _doc(db, date(2026, 9, 12), "121", [Ln("100", "50", codigo=CABLE, articulo="Cable Ejemplo")])
    _doc(db, date(2026, 9, 13), "-1210", [_monitor("-1000", "-800", cantidad="-1")], tipo="Nc")


def _endpoints():
    return [
        ("board", URL, {}),
        ("board_group", URL, {"group_by": "group", "dimension": "marca"}),
        ("board_pub", URL, {"group_by": "publication"}),
        ("nodes", f"{URL}/group-nodes", {"dimension": "marca", "path": json.dumps(["MarcaUno"])}),
        ("export", f"{URL}/export", {}),
        ("envios", f"{URL}/envios", {}),
        ("pubs", f"{URL}/products/{MONITOR}/publications", {}),
    ]


# ── S5 gate matrix on every endpoint ──

PERMSETS = {
    "none": set(),
    "ml": {VER_ML},
    "pdf": {VER_FUERA},
    "both": {VER_ML, VER_FUERA},
    "pdf_tp": {VER_FUERA, TP},
    "both_tp": {VER_ML, VER_FUERA, TP},
}


def _expected(perm: str, canal: str, name: str) -> int:
    ps = PERMSETS[perm]
    need = {"ml": {VER_ML}, "fuera": {VER_FUERA}, "todo": {VER_ML, VER_FUERA}}[canal]
    if canal == "fuera" and name == "board_pub":
        return 422  # the filter refuses fuera by publication before any gate (as before this change)
    if not need <= ps:
        return 403
    if TP in ps and canal != "ml":
        return 403
    return 200


@pytest.mark.parametrize("perm", list(PERMSETS))
def test_gate_matrix(conn, db, monkeypatch, perm) -> None:
    _seed(db)
    c = _client(conn, monkeypatch, PERMSETS[perm])
    bad = []
    for name, path, params in _endpoints():
        for canal in ("ml", "fuera", "todo"):
            r = c.get(path, params={**params, "canal": canal})
            exp = _expected(perm, canal, name)
            if TP in PERMSETS[perm] and canal == "ml":
                continue  # the TP lock needs a configured store group: not part of this probe
            if r.status_code != exp:
                bad.append((name, canal, r.status_code, exp, r.text[:200]))
    assert not bad, bad


def test_duplicate_canal_params_do_not_split_gate_and_filter(conn, db, monkeypatch) -> None:
    _seed(db)
    c = _client(conn, monkeypatch, {VER_FUERA})
    r1 = c.get(URL + "?canal=ml&canal=fuera")
    r2 = c.get(URL + "?canal=fuera&canal=ml")
    assert r2.status_code == 403
    if r1.status_code == 200:
        assert {row["canal"] for row in r1.json()["rows"]} <= {"fuera"}


# ── S6 margin per channel, export CSV contents ──


@pytest.mark.parametrize(
    ("canal", "perms"),
    [
        ("fuera", {VER_FUERA, GAN_ML}),
        ("fuera", {VER_FUERA}),
        ("todo", {VER_ML, VER_FUERA, GAN_ML}),
        ("todo", {VER_ML, VER_FUERA, GAN_FUERA}),
    ],
)
def test_no_margin_anywhere(conn, db, monkeypatch, canal, perms) -> None:
    _seed(db)
    c = _client(conn, monkeypatch, perms)
    ml_hidden_header = next(
        csv.reader(
            io.StringIO(
                _client(conn, monkeypatch, {VER_ML}).get(f"{URL}/export", params={"canal": "ml"}).text.lstrip("﻿")
            ),
            delimiter=";",
        )
    )
    text_csv = c.get(f"{URL}/export", params={"canal": canal}).text.lstrip("﻿")
    rows = list(csv.reader(io.StringIO(text_csv), delimiter=";"))
    assert rows[0] == ml_hidden_header
    board = c.get(URL, params={"canal": canal}).json()
    k = board["kpis"]
    assert board["can_see_margin"] is False
    assert k["fuera"]["otro_costo"]["margin"] is None and k["fuera"]["otro_costo"]["markup_pct"] is None
    if canal == "todo":
        assert all(
            k["por_canal"][ch]["margin"] is None and k["por_canal"][ch]["markup_pct"] is None for ch in ("ml", "fuera")
        )
    for row in board["rows"]:
        assert row["total_gauss"] is None and row["markup_pct"] is None, row
    nodes = c.get(f"{URL}/group-nodes", params={"canal": canal, "dimension": "marca", "path": json.dumps(["MarcaUno"])})
    assert nodes.status_code == 200
    for row in nodes.json()["rows"]:
        assert row["total_gauss"] is None and row["markup_pct"] is None, row
    for sort in ("markup", "total_gauss"):
        assert c.get(URL, params={"canal": canal, "sort": sort}).status_code == 403
    assert c.get(URL, params={"canal": canal, "costos_tp": "true"}).status_code == 403


# ── Money and consistency ──


def test_kpis_fuera_consistent_with_rows(conn, db, monkeypatch) -> None:
    _seed(db)
    c = _client(conn, monkeypatch, {VER_ML, VER_FUERA, GAN_ML, GAN_FUERA})
    fuera = c.get(URL, params={"canal": "fuera"}).json()
    todo = c.get(URL, params={"canal": "todo"}).json()
    kf = fuera["kpis"]["fuera"]
    # Documents: 4 (Fc x3 incl. cheque, Nc x1); cheque surcharge 84 apart.
    assert kf["comprobantes"] == 4 == sum(t["cantidad"] for t in kf["por_tipo"])
    assert kf["comprobantes"] == sum(fuera["facets"]["empresa_documentos"].values())
    assert kf["recargo_cheque"] == 84.0
    # The surcharge never enters Venta: Venta = lines with VAT (monitor 1210 - 1210, book 2210, flete 121, cable 121).
    assert round(sum(r["gross"] for r in fuera["rows"]), 2) == round(1210 - 1210 + 2210 + 121 + 121, 2)
    assert fuera["kpis"]["gross"]["value"] == round(sum(r["gross"] for r in fuera["rows"]), 2)
    sin = [r for r in fuera["rows"] if "sin_producto" in r["alerts"]]
    assert kf["sin_producto"]["monto"] == round(sum(r["gross"] for r in sin), 2)
    assert fuera["facets"]["alerts"]["sin_producto"] == len(sin)
    pc = todo["kpis"]["por_canal"]
    assert round(pc["ml"]["gross"] + pc["fuera"]["gross"], 2) == todo["kpis"]["gross"]["value"]
    assert pc["fuera"]["gross"] == fuera["kpis"]["gross"]["value"]
    s = todo["kpis"]["gross"]["series_por_canal"]
    assert [round(a + b, 2) for a, b in zip(s["ml"], s["fuera"])] == todo["kpis"]["gross"]["series"]
    assert set(s) == {"ml", "fuera"}
