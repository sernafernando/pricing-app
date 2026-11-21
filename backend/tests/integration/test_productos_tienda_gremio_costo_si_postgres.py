"""Tienda's Gremio and Sugerido prices are over costo SI (sell-in-costo-si T3 PR 6, owner L20: "los precios de gremio
y sugerido toman costo si"), with the real reader on Postgres: the listed prices and the SQL sort keys
`precio_gremio` / `precio_sugerido`, which must order by the same numbers the page shows.

Data (invented): G1 USD list 100 with costo SI USD 40; G2 USD list 90, no costo SI (its list cost, Q1); G3 ARS list
60000 with costo SI ARS 50000 (never x the rate, L18). Every product: Gremio 20%, Sugerido 5%, clásica 30%; USD 1000.
Over the list cost the Gremio order is G3 < G2 < G1; over costo SI it is G1 < G3 < G2.
"""

from __future__ import annotations

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
