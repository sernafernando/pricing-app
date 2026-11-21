"""The Tienda listing's markups are over costo SI (sell-in-costo-si T3 PR 6). Spec: handoffs/sell-in-costo-si-feature.md
S13 ("costo SI is THE cost for everything"), D1 (markups over costo SI), D4 ("el precio de una venta no se toca, ni de
las publicaciones"), owner L18 (costo SI in the product's cost currency) and the interface's §7 (an unknown cost is
None, never 0 and never a USD figure taken as pesos).

Scope of this file: the instalment markups and the markup of a manual Gremio price (an override stores the PRICE, so
only its markup follows the cost). The base of the computed Gremio / Sugerido prices waits for the owner (plan
handoffs/sell-in-costo-si-t3-pr6-plan.md), so no price is asserted here beyond "an override price stays as stored".

Method: product X has list cost USD 100 and costo SI USD 80; its twin T has list cost USD 80 and no costo SI. Both are
otherwise identical, so every markup of X must equal T's. Same for the ARS pair A (list 60000, costo SI 50000) and B
(list 50000). U has costo SI USD 80 but the reader found no USD rate: its markups are unknown. The reader
(`lote.actuales`) is tested on Postgres by PR 1; here it answers costo SI for X, A and U and the list cost ('lista',
Q1) for the rest. Invented data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.precio_gremio_override import PrecioGremioOverride
from app.models.producto import ProductoERP, ProductoPricing
from app.models.tipo_cambio import TipoCambio
from app.services.costo_si import lote
from tests.costo_si_lista import actuales_lista
from tests.integration.test_productos_tienda_orden import _guard_incompatible_raw_sql

import app.models.item_cost_list_history  # noqa: F401
import app.models.commercial_transaction  # noqa: F401
import app.models.tb_supplier  # noqa: F401

X, T, A, B, U = 9701, 9702, 9703, 9704, 9705
TC = 1000.0
CUOTAS = ("markup_3_cuotas", "markup_6_cuotas", "markup_9_cuotas", "markup_12_cuotas")
GREMIO_MANUAL = (110_000.0, 133_100.0)  # sin / con IVA


def _costo_si(item_id: int, costo: str, moneda: str, tc) -> lote.Costo:
    tc = Decimal(str(tc)) if tc else None
    return lote.Costo(
        item_id,
        Decimal(costo),
        moneda,
        lote.FUENTE_COSTO_SI,
        date(2026, 11, 1),
        tc if moneda == "USD" else None,
        lote.en_pesos(Decimal(costo), moneda, tc),
    )


@pytest.fixture()
def lector(monkeypatch):
    def actuales(db, item_ids, *, tipo_cambio=None):
        out = actuales_lista(db, item_ids, tipo_cambio=tipo_cambio)
        tc = tipo_cambio or TC
        si = {X: _costo_si(X, "80", "USD", tc), A: _costo_si(A, "50000", "ARS", tc), U: _costo_si(U, "80", "USD", None)}
        return {i: si.get(i, c) for i, c in out.items()}

    monkeypatch.setattr(lote, "actuales", actuales)


@pytest.fixture()
def catalogo(db, lector):
    _guard_incompatible_raw_sql(db)
    for item_id, costo, moneda in (
        (X, 100, "USD"),
        (T, 80, "USD"),
        (A, 60_000, "ARS"),
        (B, 50_000, "ARS"),
        (U, 100, "USD"),
    ):
        db.add(
            ProductoERP(
                item_id=item_id,
                codigo=f"TCSI-{item_id}",
                descripcion="Producto",
                marca="MARCA",
                costo=costo,
                moneda_costo=moneda,
                iva=21.0,
                envio=0.0,
                activo=True,
            )
        )
    db.flush()
    for item_id in (X, T, A, B, U):
        db.add(
            ProductoPricing(
                item_id=item_id,
                precio_lista_ml=150_000.0,
                precio_3_cuotas=160_000.0,
                precio_6_cuotas=170_000.0,
                precio_9_cuotas=180_000.0,
                precio_12_cuotas=190_000.0,
            )
        )
        db.add(
            PrecioGremioOverride(
                item_id=item_id,
                precio_gremio_sin_iva_manual=GREMIO_MANUAL[0],
                precio_gremio_con_iva_manual=GREMIO_MANUAL[1],
            )
        )
    db.add(TipoCambio(fecha=date.today(), moneda="USD", compra=TC, venta=TC))
    version = ComisionVersion(nombre="Test", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=12.0))
    db.commit()


def _listar(client, auth_headers) -> dict:
    response = client.get("/api/productos/tienda?page=1&page_size=20", headers=auth_headers)
    assert response.status_code == 200, response.text
    return {p["item_id"]: p for p in response.json()["productos"]}


@pytest.mark.parametrize("con_si, gemelo", [(X, T), (A, B)], ids=["usd", "ars"])
def test_instalment_markups_are_over_costo_si(client, auth_headers, catalogo, con_si, gemelo):
    filas = _listar(client, auth_headers)

    for campo in CUOTAS:
        assert filas[gemelo][campo] is not None, campo
        assert filas[con_si][campo] == pytest.approx(filas[gemelo][campo]), campo


@pytest.mark.parametrize("con_si, gemelo", [(X, T), (A, B)], ids=["usd", "ars"])
def test_a_manual_gremio_price_stays_and_its_markup_is_over_costo_si(client, auth_headers, catalogo, con_si, gemelo):
    filas = _listar(client, auth_headers)

    # D4: the stored price is what the listing shows, whatever the cost.
    assert (filas[con_si]["precio_gremio_sin_iva"], filas[con_si]["precio_gremio_con_iva"]) == GREMIO_MANUAL
    assert filas[con_si]["tiene_override_gremio"] is True
    # (110000 / 1.065) / cost in pesos - 1: 80000 for the USD pair, 50000 for the ARS one (never x the rate, L18)
    costo_ars = {T: 80_000, B: 50_000}[gemelo]
    esperado = (GREMIO_MANUAL[0] / 1.065 / costo_ars - 1) * 100
    assert filas[gemelo]["markup_gremio"] == pytest.approx(esperado, abs=0.01)
    assert filas[con_si]["markup_gremio"] == pytest.approx(esperado, abs=0.01)


def test_a_costo_si_without_pesos_gives_no_markup(client, auth_headers, catalogo):
    fila = _listar(client, auth_headers)[U]

    # §7: USD 80 with no rate is unknown in pesos, never 80 pesos and never the list cost
    for campo in (*CUOTAS, "markup_gremio"):
        assert fila[campo] is None, campo
    assert (fila["precio_gremio_sin_iva"], fila["precio_gremio_con_iva"]) == GREMIO_MANUAL
