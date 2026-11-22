"""`/api/costo-si/sospechosas` (owner L29): the review list of purchases held out of costo SI for a suspicious price,
its pending count, and a reviewer's accept / keep-excluded decision. Reading needs `sell_in.ver`, deciding also needs
`costo_si.revisar`. Spec: odd/tasks/costo-si-compras-sospechosas.md S4. Invented data (item 23 / invoice 00128199 is
the prod case the feature pins)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.models.commercial_transaction import CommercialTransaction
from app.models.costo_si import CostoSiCompraSospechosa
from app.models.tb_item import TBItem

URL = "/api/costo-si/sospechosas"
CT = 935025


@pytest.fixture()
def ver(rol_ventas, grant_permiso) -> None:
    grant_permiso(rol_ventas, "sell_in.ver")


@pytest.fixture()
def revisar(rol_ventas, grant_permiso, ver) -> None:
    grant_permiso(rol_ventas, "costo_si.revisar")


def _sospechosa(db, ct: int = CT, estado: str = "pendiente", fecha: date = date(2026, 10, 27), item: int = 23) -> int:
    fila = CostoSiCompraSospechosa(
        item_id=item,
        ct_transaction=ct,
        fecha=fecha,
        cantidad=312,
        precio=Decimal("0.00971"),
        moneda="USD",
        referencia=Decimal("13.53550"),
        fuente_ref="costo_si",
        ratio=Decimal("0.000717"),
        estado=estado,
        detectada_at=datetime(2026, 11, 22, 6, 0),
    )
    db.add(fila)
    db.flush()
    return fila.id


@pytest.fixture()
def caso(db) -> int:
    db.add(TBItem(comp_id=1, item_id=23, item_code="TL-WA850RE", item_desc="EXTENSOR DE RANGO WIFI TP LINK"))
    db.add(CommercialTransaction(ct_transaction=CT, ct_docNumber="00128199"))
    sid = _sospechosa(db)
    _sospechosa(db, ct=CT + 1, estado="excluida", fecha=date(2026, 10, 2))
    db.commit()
    return sid


def test_lists_the_item_23_case_with_its_invoice_and_product(client, ver, caso, auth_headers) -> None:
    body = client.get(URL, params={"estado": "pendiente"}, headers=auth_headers).json()

    assert [
        (
            f["id"],
            f["item_id"],
            f["codigo"],
            f["descripcion"],
            f["factura"],
            f["fecha"],
            f["cantidad"],
            f["precio"],
            f["moneda"],
            f["referencia"],
            f["fuente_ref"],
            f["ratio"],
            f["estado"],
            f["revisor"],
        )
        for f in body
    ] == [
        (
            caso,
            23,
            "TL-WA850RE",
            "EXTENSOR DE RANGO WIFI TP LINK",
            "00128199",
            "2026-10-27",
            312,
            "0.00971",
            "USD",
            "13.53550",
            "costo_si",
            "0.000717",
            "pendiente",
            None,
        )
    ]


def test_lists_every_state_newest_invoice_first_and_counts_the_pending(client, ver, caso, auth_headers) -> None:
    todas = client.get(URL, headers=auth_headers).json()
    resumen = client.get(f"{URL}/resumen", headers=auth_headers).json()

    assert [(f["ct_transaction"], f["estado"]) for f in todas] == [(CT, "pendiente"), (CT + 1, "excluida")]
    assert client.get(URL, params={"desde": "2026-10-10"}, headers=auth_headers).json()[0]["ct_transaction"] == CT
    assert len(client.get(URL, params={"desde": "2026-10-10"}, headers=auth_headers).json()) == 1
    assert resumen == {"pendientes": 1}


def test_an_unknown_state_filter_is_refused(client, ver, caso, auth_headers) -> None:
    assert client.get(URL, params={"estado": "otro"}, headers=auth_headers).status_code == 422


def test_reading_needs_sell_in_ver(client, caso, auth_headers) -> None:
    assert client.get(URL, headers=auth_headers).status_code == 403
    assert client.get(f"{URL}/resumen", headers=auth_headers).status_code == 403


def test_accepting_records_the_reviewer_and_the_decision(client, revisar, caso, auth_headers, active_user, db) -> None:
    resp = client.post(f"{URL}/{caso}/aceptar", json={"precio": "0.00971", "nota": "Verificado"}, headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert (body["estado"], body["revisado_por"], body["revisor"], body["nota"]) == (
        "aceptada",
        active_user.id,
        "Test User",
        "Verificado",
    )
    assert body["revisado_at"] is not None
    db.expire_all()
    assert db.get(CostoSiCompraSospechosa, caso).estado == "aceptada"
    assert client.get(f"{URL}/resumen", headers=auth_headers).json() == {"pendientes": 0}


def test_keeping_it_excluded_records_the_decision(client, revisar, caso, auth_headers, db) -> None:
    resp = client.post(f"{URL}/{caso}/excluir", json={"precio": "0.00971"}, headers=auth_headers)

    assert (resp.status_code, resp.json()["estado"], resp.json()["nota"]) == (200, "excluida", None)
    db.expire_all()
    assert db.get(CostoSiCompraSospechosa, caso).estado == "excluida"


def test_deciding_needs_costo_si_revisar(client, ver, caso, auth_headers, db) -> None:
    for accion in ("aceptar", "excluir"):
        resp = client.post(f"{URL}/{caso}/{accion}", json={"precio": "0.00971"}, headers=auth_headers)
        assert resp.status_code == 403
    db.expire_all()
    assert db.get(CostoSiCompraSospechosa, caso).estado == "pendiente"


def test_an_unknown_row_is_404(client, revisar, caso, auth_headers) -> None:
    resp = client.post(f"{URL}/999999/aceptar", json={"precio": "0.00971"}, headers=auth_headers)

    assert resp.status_code == 404


def test_a_row_whose_price_changed_since_it_was_seen_is_refused(client, revisar, caso, auth_headers, db) -> None:
    resp = client.post(f"{URL}/{caso}/aceptar", json={"precio": "0.01050"}, headers=auth_headers)

    assert resp.status_code == 409
    db.expire_all()
    assert db.get(CostoSiCompraSospechosa, caso).estado == "pendiente"


def test_the_product_breakdown_still_answers_on_its_own_path(client, ver, auth_headers) -> None:
    """`/sospechosas` is declared before `/{item_id}`: a product id still reaches the breakdown."""
    assert client.get("/api/costo-si/7101", headers=auth_headers).status_code == 200
