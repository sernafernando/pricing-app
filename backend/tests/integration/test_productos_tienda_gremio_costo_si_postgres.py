"""Tienda's Gremio and Sugerido prices are over costo SI (sell-in-costo-si T3 PR 6, owner L20: "los precios de gremio
y sugerido toman costo si"), with the real reader on Postgres: the listed prices and the SQL sort keys
`precio_gremio` / `precio_sugerido`, which must order by the same numbers the page shows.

Data (invented): G1 USD list 100 with costo SI USD 40; G2 USD list 90, no costo SI (its list cost, Q1); G3 ARS list
60000 with costo SI ARS 50000 (never x the rate, L18). Every product: Gremio 20%, Sugerido 5%, clásica 30%; USD 1000.
Over the list cost the Gremio order is G3 < G2 < G1; over costo SI it is G1 < G3 < G2.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.markup_tienda import MarkupTiendaProducto
from app.models.producto import ProductoERP, ProductoPricing
from app.models.tipo_cambio import TipoCambio
from app.services.pricing_calculator import obtener_constantes_pricing
from tests.integration.test_productos_costo_si_postgres import _paso, _tables, client, permisos, pg  # noqa: F401
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

G1, G2, G3 = 6401, 6402, 6403
TC = 1000.0
GREMIO, SUGERIDO, CLASICA = 20.0, 5.0, 30.0
COSTO_SI_ARS = {G1: 40_000.0, G2: 90_000.0, G3: 50_000.0}


@pytest.fixture(scope="module")
def pg_engine_costo_si() -> Iterator[Engine]:
    with throwaway_schema("tienda_gremio_costo_si", _tables()) as engine:
        yield engine


@pytest.fixture()
def mundo(pg: Session) -> None:  # noqa: F811
    pg.add(TipoCambio(moneda="USD", fecha=date(2026, 1, 1), compra=TC, venta=TC))
    version = ComisionVersion(nombre="Test", fecha_desde=date(2000, 1, 1), activo=True)
    pg.add(version)
    pg.flush()
    pg.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=12.0))
    for item_id, moneda, costo in ((G1, "USD", 100.0), (G2, "USD", 90.0), (G3, "ARS", 60_000.0)):
        pg.add(
            ProductoERP(
                item_id=item_id,
                codigo=f"G{item_id}",
                descripcion=f"Producto {item_id}",
                marca="DEMO",
                costo=costo,
                moneda_costo=moneda,
                iva=21.0,
                envio=0.0,
                stock=5,
                activo=True,
            )
        )
        pg.add(ProductoPricing(item_id=item_id, markup_calculado=CLASICA))
        pg.add(MarkupTiendaProducto(item_id=item_id, markup_porcentaje=GREMIO, markup_sugerido=SUGERIDO, activo=True))
    pg.flush()
    _paso(pg, G1, date(2026, 10, 1), "40.00000")
    _paso(pg, G3, date(2026, 10, 1), "50000.00000", moneda="ARS")
    pg.flush()


def _tienda(client: TestClient, **params) -> list[dict]:  # noqa: F811
    response = client.get("/api/productos/tienda", params={"page_size": 50, **params})
    assert response.status_code == 200, response.text
    return response.json()["productos"]


def test_gremio_and_sugerido_are_priced_over_costo_si(client, mundo, pg) -> None:  # noqa: F811
    factor = 1 + obtener_constantes_pricing(pg).get("varios", 6.5) / 100
    filas = {p["item_id"]: p for p in _tienda(client)}

    for item, costo in COSTO_SI_ARS.items():
        assert filas[item]["precio_gremio_sin_iva"] == pytest.approx(costo * factor * (1 + GREMIO / 100)), item
        sugerido = costo * factor * (1 + (CLASICA + SUGERIDO) / 100)
        assert filas[item]["precio_sugerido_sin_iva"] == pytest.approx(sugerido), item


@pytest.mark.parametrize("campo", ["precio_gremio", "precio_sugerido"])
def test_the_sort_follows_the_prices_the_page_shows(client, mundo, campo) -> None:  # noqa: F811
    asc = _tienda(client, orden_campos=campo, orden_direcciones="asc")
    desc = _tienda(client, orden_campos=campo, orden_direcciones="desc")

    assert [p["item_id"] for p in asc] == [G1, G3, G2]
    assert [p["item_id"] for p in desc] == [G2, G3, G1]
    precios = [p[f"{campo}_sin_iva"] for p in asc]
    assert precios == sorted(precios)


@pytest.mark.parametrize("campo", ["precio_gremio", "precio_sugerido"])
def test_the_sort_reads_the_costo_si_once_and_never_in_the_count(client, mundo, pg, campo) -> None:  # noqa: F811
    """The whole-catalogue costo SI read is the sort's cost (timed on prod, PR 6): one set-based read joined to the
    page, and none in the total, which the sort's at-most-one-row joins never change."""
    from sqlalchemy import event

    sentencias: list[str] = []

    def _anotar(conn, cursor, sentencia, *args) -> None:
        sentencias.append(sentencia)

    bind = pg.get_bind()
    event.listen(bind, "before_cursor_execute", _anotar)
    try:
        response = client.get(
            "/api/productos/tienda", params={"page_size": 2, "orden_campos": campo, "orden_direcciones": "asc"}
        )
    finally:
        event.remove(bind, "before_cursor_execute", _anotar)

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 3
    con_costo_si = [s for s in sentencias if "csi_tienda" in s]
    assert len(con_costo_si) == 1
    assert re.search(r"LIMIT %\(\w+\)s(\s+OFFSET %\(\w+\)s)?\s*$", con_costo_si[0])  # the page, not the count


def test_the_clasica_markup_shown_is_over_each_products_own_cost(client, mundo, pg) -> None:  # noqa: F811
    """Same ML price, different cost: after the pricing recompute (`recalcular_markups_guardados`, what the drain's
    `despues.pricing` runs) the listing's clásica `markup` differs, each over its own costo SI (or list cost, Q1),
    and both give the same ML net: cost x (1 + markup) is one number."""
    from app.services import recalcular_markups_service as rms

    for item in (G1, G2):
        pg.query(ProductoPricing).filter_by(item_id=item).update({"precio_lista_ml": 150_000.0})
    pg.flush()
    assert rms.recalcular_markups_guardados(pg, [G1, G2]) == []
    pg.flush()

    filas = {p["item_id"]: p for p in _tienda(client)}
    m1, m2 = filas[G1]["markup"], filas[G2]["markup"]

    assert m1 is not None and m2 is not None
    assert m1 > m2  # costo SI 40000 vs list 90000 at the same price
    assert COSTO_SI_ARS[G1] * (1 + m1 / 100) == pytest.approx(COSTO_SI_ARS[G2] * (1 + m2 / 100), rel=1e-3)


def test_the_deploy_estimate_measures_these_very_prices(client, mundo, pg) -> None:  # noqa: F811
    """`app.scripts.costo_si_tienda_estimacion` (the read-only prod estimate) prices exactly as the listing: before
    over the list cost, after over costo SI; Sugerido after the clásica markup is rewritten over costo SI keeps the
    ML price, so only the extra Sugerido % moves: varios x Sugerido% x (list - costo SI)."""
    from app.scripts.costo_si_tienda_estimacion import estimar

    factor = 1 + obtener_constantes_pricing(pg).get("varios", 6.5) / 100
    listado = {p["item_id"]: p for p in _tienda(client)}
    lista = {G1: 100_000.0, G2: 90_000.0, G3: 60_000.0}
    filas = {f.item_id: f for f in estimar(pg)}

    for item, si in COSTO_SI_ARS.items():
        f = filas[item]
        assert f.gremio_antes == pytest.approx(lista[item] * factor * (1 + GREMIO / 100)), item
        assert f.gremio_despues == pytest.approx(listado[item]["precio_gremio_sin_iva"]), item
        assert f.clasica_sin_recalculo is (item != G2), item  # no ML price here: the drain cannot rewrite it
        caida = factor * SUGERIDO / 100 * (lista[item] - si)
        assert f.sugerido_antes - f.sugerido_despues == pytest.approx(caida), item
    assert (filas[G1].fuente, filas[G2].fuente) == ("costo_si", "lista")


def test_the_estimate_needs_its_url_and_never_runs_without_it(tmp_path, monkeypatch, capsys) -> None:
    from app.scripts import costo_si_tienda_estimacion as script

    monkeypatch.delenv(script.URL_ENV, raising=False)

    assert script.main(["--out", str(tmp_path)]) == 2
    assert script.URL_ENV in capsys.readouterr().err
