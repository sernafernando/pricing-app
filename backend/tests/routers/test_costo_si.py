"""`GET /api/costo-si/{item_id}` (sell-in-costo-si T2, S10, S11): the costo SI in force on a date with its breakdown;
a combo answers its components' costo SI x quantity. Invented data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.combo_componente import ComboComponente
from app.models.costo_si import CostoSiPaso

URL = "/api/costo-si"
PRODUCTO, OTRO, COMBO = 7101, 7102, 7103


@pytest.fixture()
def ver_sell_in(rol_ventas, grant_permiso) -> None:
    grant_permiso(rol_ventas, "sell_in.ver")


def _paso(db, item_id: int, orden: int, fecha: date, promedio: str, **extra) -> None:
    db.add(
        CostoSiPaso(
            item_id=item_id,
            orden=orden,
            tipo="inicio" if orden == 0 else "compra",
            fecha=fecha,
            ct_transaction=None if orden == 0 else 90_000 + orden,
            cantidad=extra.get("cantidad", 10),
            costo_neto_usd=Decimal(extra.get("neto", promedio)),
            sell_ins=extra.get("sell_ins", []),
            sell_in_pct=Decimal(extra.get("pct", "0")),
            costo_neto_neto_usd=Decimal(extra.get("nn", promedio)),
            stock_antes=extra.get("antes", 0),
            stock_base=extra.get("antes", 0),
            stock_despues=extra.get("despues", 10),
            promedio_usd=Decimal(promedio),
            en_compras=False,
        )
    )


@pytest.fixture()
def historia(db) -> None:
    _paso(db, PRODUCTO, 0, date(2026, 10, 1), "25.00000", cantidad=200, antes=200, despues=200)
    _paso(
        db,
        PRODUCTO,
        1,
        date(2026, 10, 20),
        "23.81667",
        cantidad=100,
        neto="22",
        nn="21.45",
        pct="2.5",
        antes=200,
        despues=300,
        sell_ins=[{"origen": "compra", "ref": 3, "porcentaje": "2.5"}],
    )
    _paso(db, OTRO, 0, date(2026, 10, 1), "4.00000")
    db.add(ComboComponente(combo_item_id=COMBO, componente_item_id=PRODUCTO, cantidad=Decimal(2)))
    db.add(ComboComponente(combo_item_id=COMBO, componente_item_id=OTRO, cantidad=Decimal(1)))
    db.commit()


def test_returns_the_value_in_force_on_the_date_and_the_whole_breakdown(client, ver_sell_in, historia, auth_headers):
    body = client.get(f"{URL}/{PRODUCTO}", params={"fecha": "2026-11-20"}, headers=auth_headers).json()

    assert body["costo_si_usd"] == "23.81667"
    assert body["vigente_desde"] == "2026-10-20"
    assert body["es_combo"] is False
    assert [(p["tipo"], p["promedio_usd"]) for p in body["pasos"]] == [("inicio", "25.00000"), ("compra", "23.81667")]
    compra = body["pasos"][1]
    assert (compra["costo_neto_usd"], compra["sell_in_pct"], compra["costo_neto_neto_usd"]) == (
        "22.00000",
        "2.5000",
        "21.45000",
    )
    assert (compra["stock_antes"], compra["stock_despues"]) == (200, 300)
    assert compra["sell_ins"] == [{"origen": "compra", "ref": 3, "porcentaje": "2.5"}]


def test_a_date_before_the_purchase_reads_the_start_value(client, ver_sell_in, historia, auth_headers):
    body = client.get(f"{URL}/{PRODUCTO}", params={"fecha": "2026-10-19"}, headers=auth_headers).json()

    assert (body["costo_si_usd"], body["vigente_desde"]) == ("25.00000", "2026-10-01")


def test_a_combo_is_its_components_costo_si_times_their_quantity(client, ver_sell_in, historia, auth_headers):
    """S11 (L4.9): "el x2 es el costo de una unidad x la cantidad"."""
    body = client.get(f"{URL}/{COMBO}", params={"fecha": "2026-11-20"}, headers=auth_headers).json()

    assert body["es_combo"] is True
    assert body["pasos"] == []
    assert body["costo_si_usd"] == "51.63334"  # 2 x 23.81667 + 4
    assert [(c["item_id"], c["costo_si_usd"]) for c in body["componentes"]] == [
        (PRODUCTO, "23.81667"),
        (OTRO, "4.00000"),
    ]


def test_a_product_without_any_sell_in_has_no_costo_si(client, ver_sell_in, historia, auth_headers):
    body = client.get(f"{URL}/999", headers=auth_headers).json()

    assert (body["costo_si_usd"], body["pasos"]) == (None, [])


def test_needs_the_sell_in_permission(client, historia, auth_headers):
    assert client.get(f"{URL}/{PRODUCTO}", headers=auth_headers).status_code == 403
