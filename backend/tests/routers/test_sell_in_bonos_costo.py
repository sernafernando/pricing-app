"""Router: a sell-in bonus over the sale's cost (`base='costo_venta'`), sell-in-sell-out T25d (S30, S33).

Owner, 2026-10-29: "es para operaciones viejas que no tienen la factura cargada". A cost bonus is a % of the
product's costo SI (brand / category / models, no purchase of its own); `incluye_iva` (S33) only exists on it.
`base` never changes on an edit. Its generated amount and cap come from the costo SI purchase steps that carry it
(sell-in-costo-si T5 PR B, owner L26 "recalculalo"), not from purchases. Postgres test database (`_pg_app`): that
read is Postgres-only SQL.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.auditoria import Auditoria, TipoAccion
from app.models.costo_si import CostoSiFacturaTc, CostoSiPaso
from app.models.producto import ProductoERP, TipoMoneda
from app.models.sell_in import SellInBonoMarca, SellInCompra, SellInCompraItem
from app.models.tipo_cambio import TipoCambio
from tests.routers._pg_app import engine  # noqa: F401 - the fixture, by name
from tests.services._aprobacion import cargas_aprobadas  # noqa: F401 - the fixture, by name

# Postgres (`_pg_app`): a cost bonus reads what costo SI took off its invoices, Postgres-only SQL.
# Written before tacticals approval: a load is approved right away (`_aprobacion.cargas_aprobadas`).
pytestmark = [pytest.mark.postgres, pytest.mark.usefixtures("cargas_aprobadas")]

BASE = "/api/sell-in/bonos"


@pytest.fixture()
def productos(db):
    rows = [ProductoERP(item_id=4512, codigo="SW-8", descripcion="Switch", marca="TP-LINK", costo=10.0)]
    for row in rows:
        row.moneda_costo = TipoMoneda.USD
    db.add_all(rows)
    db.flush()
    return rows


@pytest.fixture()
def gestor(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, "sell_in.ver")
    grant_permiso(rol_admin, "sell_in.gestionar")
    return admin_auth_headers


def _costo(**overrides) -> dict:
    body = {
        "base": "costo_venta",
        "alcance": "marca",
        "marca": "TP-LINK",
        "tipo": "porcentaje",
        "porcentaje": "2.71",
        "moneda": "ARS",
        "fecha_desde": "2026-01-01",
        "fecha_hasta": "2026-12-31",
    }
    body.update(overrides)
    return body


def _factura(**overrides) -> dict:
    body = {"marca": "TP-LINK", "monto_unit": "2.50", "moneda": "USD", "fecha_desde": "2026-10-01"}
    body.update({"fecha_hasta": "2026-12-31", "descripcion": "Acuerdo Q4"})
    body.update(overrides)
    return body


def _message(resp) -> str:
    message = resp.json()["error"]["message"]
    assert isinstance(message, str) and message
    return message


def _crear(client, headers, body: dict) -> dict:
    resp = client.post(BASE, json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _paso(db, orden: int, fecha: date, cantidad: int, costo: str, sell_ins: list, tc: str | None = None) -> None:
    """A costo SI purchase step of the USD product 4512: `cantidad` units at net `costo` USD, the sell ins it got.
    `tc` is the invoice's own rate, a PM correction (`costo_si_factura_tc`), where costo SI and its caps read it."""
    if tc is not None:
        db.add(CostoSiFacturaTc(ct_transaction=1000 + orden, tipo_cambio=Decimal(tc)))
    db.add(
        CostoSiPaso(
            item_id=4512,
            orden=orden,
            tipo="compra",
            fecha=fecha,
            ct_transaction=1000 + orden,
            cantidad=cantidad,
            costo_neto_usd=Decimal(costo),
            sell_ins=[{"origen": o, "ref": r, "porcentaje": p} for o, r, p in sell_ins],
            stock_antes=0,
            stock_base=0,
            stock_despues=cantidad,
            tipo_cambio=None if tc is None else Decimal(tc),
            moneda="USD",
        )
    )
    db.flush()


def test_create_stores_a_cost_bonus_and_returns_its_fields(client, gestor, productos, db):
    data = _crear(client, gestor, _costo(incluye_iva=True, offset_origen_id=9))

    assert (data["base"], data["incluye_iva"], data["offset_origen_id"]) == ("costo_venta", True, None)
    bono = db.get(SellInBonoMarca, data["id"])
    # `offset_origen_id` is set by the offsets migration script only, never from the API.
    assert (bono.base, bono.incluye_iva, bono.offset_origen_id) == ("costo_venta", True, None)


def test_create_defaults_to_an_invoice_bonus_without_vat(client, gestor, productos):
    data = _crear(client, gestor, _factura())

    assert (data["base"], data["incluye_iva"], data["offset_origen_id"]) == ("factura", False, None)


def test_a_cost_bonus_may_be_an_ars_amount_per_unit(client, gestor, productos, db):
    # Tacticals T1: a fixed ARS amount per sold unit on the sale's cost, never above it (`bonos_costo.unitario`).
    data = _crear(client, gestor, _costo(tipo="por_unidad", porcentaje=None, monto_unit="5.00", incluye_iva=True))

    bono = db.get(SellInBonoMarca, data["id"])
    assert (bono.base, bono.tipo, bono.monto_unit, bono.porcentaje, bono.incluye_iva) == (
        "costo_venta",
        "por_unidad",
        Decimal("5.00"),
        None,
        True,
    )


@pytest.mark.parametrize(
    "body,fragment",
    [
        (_costo(moneda="USD"), "ars"),
        (_costo(tipo="por_unidad", porcentaje=None, monto_unit="5.00", moneda="USD"), "ars"),
        (_costo(alcance="factura", marca=None, pedido_id=1), "factura"),
        (_factura(incluye_iva=True), "iva"),
    ],
)
def test_invalid_cost_bonus_combinations_are_422(client, gestor, productos, db, body, fragment):
    resp = client.post(BASE, json=body, headers=gestor)

    assert resp.status_code == 422
    assert fragment in _message(resp).lower()
    assert db.query(SellInBonoMarca).count() == 0


@pytest.mark.parametrize(
    "creado,nueva",
    [(_costo(), "factura"), (_factura(), "costo_venta")],
)
def test_the_base_cannot_change_on_edit(client, gestor, productos, db, creado, nueva):
    data = _crear(client, gestor, creado)
    cuerpo = _costo(base=nueva) if nueva == "costo_venta" else _factura(base=nueva)

    resp = client.put(f"{BASE}/{data['id']}", json=cuerpo, headers=gestor)

    assert resp.status_code == 422
    assert "dos veces" in _message(resp)
    assert db.get(SellInBonoMarca, data["id"]).base == creado.get("base", "factura")


def test_an_edit_without_base_keeps_it_and_validates_against_it(client, gestor, productos, db):
    data = _crear(client, gestor, _costo())
    sin_base = {k: v for k, v in _costo().items() if k != "base"}

    kept = client.put(f"{BASE}/{data['id']}", json={**sin_base, "porcentaje": "3.00"}, headers=gestor)
    assert kept.status_code == 200, kept.text
    assert (kept.json()["base"], kept.json()["porcentaje"]) == ("costo_venta", "3.0000")

    usd = client.put(f"{BASE}/{data['id']}", json={**sin_base, "moneda": "USD"}, headers=gestor)
    assert usd.status_code == 422
    assert "ars" in _message(usd).lower()


def test_incluye_iva_is_editable_on_a_cost_bonus_kept_when_absent_and_audited(client, gestor, productos, db):
    data = _crear(client, gestor, _costo())

    resp = client.put(f"{BASE}/{data['id']}", json=_costo(incluye_iva=True), headers=gestor)
    assert resp.status_code == 200, resp.text
    assert resp.json()["incluye_iva"] is True
    sin_iva = {k: v for k, v in _costo().items() if k != "incluye_iva"}
    assert client.put(f"{BASE}/{data['id']}", json=sin_iva, headers=gestor).json()["incluye_iva"] is True

    assert db.get(SellInBonoMarca, data["id"]).incluye_iva is True
    [creado] = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_BONO_CREADO).all()
    assert (creado.valores_nuevos["base"], creado.valores_nuevos["incluye_iva"]) == ("costo_venta", False)
    assert creado.valores_nuevos["offset_origen_id"] is None
    primero = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_IN_BONO_EDITADO).first()
    assert (primero.valores_anteriores["incluye_iva"], primero.valores_nuevos["incluye_iva"]) == (False, True)


def test_incluye_iva_on_an_invoice_bonus_edit_is_422(client, gestor, productos):
    data = _crear(client, gestor, _factura())

    resp = client.put(f"{BASE}/{data['id']}", json=_factura(incluye_iva=True), headers=gestor)

    assert resp.status_code == 422
    assert "iva" in _message(resp).lower()


def test_a_cost_bonus_reports_what_its_invoices_got_in_costo_si_and_its_cap(client, gestor, productos, db):
    """L26: what a cost bonus generated is what costo SI took off the invoices of its period, in its currency."""
    data = _crear(client, gestor, _costo(porcentaje="2", tope_unidades=10, tope_monto="8000.00"))
    otro = _crear(client, gestor, _costo(porcentaje="5"))
    # An ARS invoice: 3 x USD 40 x 2% = USD 2.40, at the invoice's own rate 1000 = ARS 2400.
    _paso(db, 1, date(2026, 3, 1), 3, "40", [("bono", data["id"], "2.0000"), ("bono", otro["id"], "5.0000")], tc="1000")
    # A USD invoice has no rate of its own: 4 x USD 50 x 2% = USD 4, at the last rate on or before its date (1100).
    _paso(db, 2, date(2026, 4, 1), 4, "50", [("bono", data["id"], "2.0000")])
    db.add_all(
        [
            TipoCambio(fecha=date(2026, 3, 31), moneda="USD", compra=1050, venta=1100),
            TipoCambio(fecha=date(2026, 4, 2), moneda="USD", compra=9000, venta=9999),
        ]
    )
    # A Compras sell in with the same number, and an invoice only the other bonus reached, never count.
    _paso(db, 3, date(2026, 5, 1), 9, "50", [("compra", data["id"], "10.0000"), ("bono", otro["id"], "5.0000")])
    db.flush()

    got = client.get(f"{BASE}/{data['id']}", headers=gestor).json()
    [listed] = [f for f in client.get(BASE, headers=gestor).json()["items"] if f["id"] == data["id"]]

    for fila in (got, listed):
        assert {
            k: fila[k]
            for k in (
                "compras_activas",
                "unidades",
                "monto_generado",
                "montos_generados",
                "tope_unidades_restantes",
                "tope_monto_restante",
            )
        } == {
            "compras_activas": 0,
            "unidades": 7,
            "monto_generado": "6800.00",
            "montos_generados": [{"moneda": "ARS", "monto": "6800.00"}],
            "tope_unidades_restantes": 3,
            "tope_monto_restante": "1200.00",
        }


def test_the_stock_on_hand_a_cost_bonus_landed_on_counts_toward_what_it_used(client, gestor, productos, db):
    """L41: the 6 units on hand when the bonus starts (the start step) use 6 of its 10-unit cap before the invoice's 4,
    so what it used and the cap left never drift from what costo SI took: 6 x 40 x 2 % + 4 x 50 x 2 % = USD 8.80."""
    data = _crear(client, gestor, _costo(porcentaje="2", tope_unidades=10))
    db.add(
        CostoSiPaso(
            item_id=4512,
            orden=0,
            tipo="inicio",
            fecha=date(2026, 3, 1),
            cantidad=6,
            costo_neto_usd=Decimal("40"),
            sell_ins=[{"origen": "bono", "ref": data["id"], "porcentaje": "2.0000"}],
            stock_antes=6,
            stock_base=6,
            stock_despues=6,
            moneda="USD",
        )
    )
    _paso(db, 1, date(2026, 3, 2), 4, "50", [("bono", data["id"], "2.0000")], tc="1000")
    db.add(TipoCambio(fecha=date(2026, 2, 28), moneda="USD", compra=900, venta=1000))
    db.flush()

    got = client.get(f"{BASE}/{data['id']}", headers=gestor).json()

    assert (got["unidades"], got["monto_generado"], got["tope_unidades_restantes"]) == (10, "8800.00", 0)


def test_a_units_cap_that_ran_out_inside_an_invoice_counts_only_its_cap(client, gestor, productos, db):
    """Costo SI cut the cap inside the second invoice (its % covers only what was left): units stop at the cap.
    Sell in incident S1: a % with no money cap reads in its steps' currency (the USD product's), never converted."""
    data = _crear(client, gestor, _costo(porcentaje="1", tope_unidades=4))
    _paso(db, 1, date(2026, 3, 1), 3, "40", [("bono", data["id"], "1.0000")], tc="1000")
    # 1 unit of 4 was left: 1% on a quarter of the invoice.
    _paso(db, 2, date(2026, 4, 1), 4, "50", [("bono", data["id"], "0.2500")], tc="1000")

    got = client.get(f"{BASE}/{data['id']}", headers=gestor).json()

    # 3 x USD 40 x 1% = USD 1.20 + 4 x USD 50 x 0.25% = USD 0.50 (it was ARS 1,700 at each invoice's 1000).
    assert (got["unidades"], got["monto_generado"], got["moneda_generado"], got["tope_unidades_restantes"]) == (
        4,
        "1.70",
        "USD",
        0,
    )
    assert (got["moneda"], got["montos_generados"]) == ("ARS", [{"moneda": "USD", "monto": "1.70"}])


def test_a_usd_invoice_is_valued_at_the_rate_its_caps_used_so_the_cap_left_does_not_drift(
    client, gestor, productos, db
):
    """Review (1): a USD invoice of a USD product keeps no rate on its step, but the bonus's ARS cap was used up at the
    invoice's own rate (the PM correction, `aplicar_topes`), not at the day's rate."""
    data = _crear(client, gestor, _costo(porcentaje="2", tope_monto="10000.00"))
    db.add_all(
        [
            CostoSiFacturaTc(ct_transaction=1001, tipo_cambio=Decimal("1200")),
            TipoCambio(fecha=date(2026, 3, 31), moneda="USD", compra=1050, venta=1100),
        ]
    )
    # 4 x USD 50 x 2% = USD 4, at the invoice's own 1200 = ARS 4800 (at the day's 1100 it would be ARS 4400).
    _paso(db, 1, date(2026, 4, 1), 4, "50", [("bono", data["id"], "2.0000")])

    got = client.get(f"{BASE}/{data['id']}", headers=gestor).json()

    assert (got["monto_generado"], got["tope_monto_restante"]) == ("4800.00", "5200.00")


def test_a_money_cap_that_ran_out_inside_an_invoice_counts_only_the_units_it_covered(client, gestor, productos, db):
    """Review (2): ARS 600 of the cap was left for an invoice worth ARS 4000 of bonus: 0.6 of its 4 units."""
    data = _crear(client, gestor, _costo(porcentaje="2", tope_monto="3000.00"))
    # 3 x USD 40 x 2% x 1000 = ARS 2400.
    _paso(db, 1, date(2026, 3, 1), 3, "40", [("bono", data["id"], "2.0000")], tc="1000")
    # ARS 600 = USD 0.60 of a USD 200 invoice: 0.3%.
    _paso(db, 2, date(2026, 4, 1), 4, "50", [("bono", data["id"], "0.3000")], tc="1000")

    got = client.get(f"{BASE}/{data['id']}", headers=gestor).json()

    assert (got["unidades"], got["monto_generado"], got["tope_monto_restante"]) == (4, "3000.00", "0.00")


def test_a_per_unit_cost_bonus_counts_the_units_its_capped_amount_covered(client, gestor, productos, db):
    """An ARS 100 per unit bonus capped at ARS 200, on 3 units of USD 50 at 1000: 2 of them."""
    data = _crear(client, gestor, _costo(tipo="por_unidad", porcentaje=None, monto_unit="100", tope_monto="200.00"))
    # ARS 200 of an ARS 150000 invoice.
    _paso(db, 1, date(2026, 3, 1), 3, "50", [("bono", data["id"], "0.1333")], tc="1000")

    got = client.get(f"{BASE}/{data['id']}", headers=gestor).json()

    assert (got["unidades"], got["monto_generado"]) == (2, "199.95")


def test_a_cost_bonus_with_vat_counts_every_unit_of_an_uncapped_invoice(client, gestor, productos, db):
    """2.42% with VAT is 2% net of the product's 21%: an invoice that got 2% got it on all its units."""
    data = _crear(client, gestor, _costo(porcentaje="2.42", incluye_iva=True, tope_unidades=10))
    _paso(db, 1, date(2026, 3, 1), 3, "40", [("bono", data["id"], "2.0000")], tc="1000")

    got = client.get(f"{BASE}/{data['id']}", headers=gestor).json()

    assert (got["unidades"], got["tope_unidades_restantes"]) == (3, 7)


def test_an_invoice_bonus_response_is_unchanged(client, gestor, productos, admin_user, db):
    data = _crear(client, gestor, _factura(tope_unidades=10))
    compra = SellInCompra(
        fecha_compra=date(2026, 10, 10),
        moneda="USD",
        monto_total=Decimal("10.00"),
        tipo_cambio=Decimal("1450"),
        formula="por_unidad",
        estado="activa",
        usuario_id=admin_user.id,
        origen="bono_marca",
        bono_id=data["id"],
    )
    db.add(compra)
    db.flush()
    db.add(
        SellInCompraItem(
            compra_id=compra.id, item_id=4512, cantidad=4, costo_base_unit=Decimal("10"), monto_asignado="10.00"
        )
    )
    db.flush()
    # A costo SI step never counts for an invoice bonus: its purchases do.
    _paso(db, 1, date(2026, 10, 15), 50, "10", [("bono", data["id"], "50.0000")], tc="1000")

    got = client.get(f"{BASE}/{data['id']}", headers=gestor).json()

    assert {k: v for k, v in got.items() if k not in ("created_at", "updated_at")} == {
        "id": data["id"],
        "alcance": "marca",
        "marca": "TP-LINK",
        "categoria": None,
        "modelos": [],
        "pedido_id": None,
        "pedido_numero": None,
        "tipo": "por_unidad",
        "monto_unit": "2.50",
        "porcentaje": None,
        "moneda": "USD",
        "fecha_desde": "2026-10-01",
        "fecha_hasta": "2026-12-31",
        "descripcion": "Acuerdo Q4",
        "estado": "activa",
        "usuario_id": admin_user.id,
        "tactical_id": None,  # added by tacticals approval (S6): a standalone bonus has no tactical
        "compras_activas": 1,
        "unidades": 4,
        "monto_generado": "10.00",
        "moneda_generado": "USD",  # added by sell in incident S1: the currency `monto_generado` is in
        "montos_generados": [{"moneda": "USD", "monto": "10.00"}],
        "tope_unidades": 10,
        "tope_monto": None,
        "tope_unidades_restantes": 6,
        "tope_monto_restante": None,
        "base": "factura",
        "incluye_iva": False,
        "acumulable": True,
        "offset_origen_id": None,
    }


def test_a_page_mixing_bonuses_reports_a_cost_bonus_without_sales_as_nothing_generated(
    client, gestor, productos, admin_user, db
):
    factura = _crear(client, gestor, _factura(tope_unidades=10))
    costo = _crear(client, gestor, _costo(tope_unidades=10, tope_monto="500.00"))
    compra = SellInCompra(
        fecha_compra=date(2026, 10, 10),
        moneda="USD",
        monto_total=Decimal("10.00"),
        tipo_cambio=Decimal("1450"),
        formula="por_unidad",
        estado="activa",
        usuario_id=admin_user.id,
        origen="bono_marca",
        bono_id=factura["id"],
    )
    db.add(compra)
    db.flush()
    db.add(
        SellInCompraItem(
            compra_id=compra.id, item_id=4512, cantidad=4, costo_base_unit=Decimal("10"), monto_asignado="10.00"
        )
    )
    db.flush()
    campos = (
        "compras_activas",
        "unidades",
        "monto_generado",
        "montos_generados",
        "tope_unidades_restantes",
        "tope_monto_restante",
    )

    filas = {f["id"]: {k: f[k] for k in campos} for f in client.get(BASE, headers=gestor).json()["items"]}

    assert filas == {
        costo["id"]: {
            "compras_activas": 0,
            "unidades": 0,
            "monto_generado": "0.00",
            "montos_generados": [],
            "tope_unidades_restantes": 10,
            "tope_monto_restante": "500.00",
        },
        factura["id"]: {
            "compras_activas": 1,
            "unidades": 4,
            "monto_generado": "10.00",
            "montos_generados": [{"moneda": "USD", "monto": "10.00"}],
            "tope_unidades_restantes": 6,
            "tope_monto_restante": None,
        },
    }


def test_a_cost_bonus_takes_the_acumulable_flag_too(client, gestor, productos, db):
    """T27b (S36): every sell-in bonus carries it, the % of cost ones included."""
    data = _crear(client, gestor, _costo(acumulable=False))

    assert data["acumulable"] is False
    resp = client.put(f"{BASE}/{data['id']}", json=_costo(acumulable=True), headers=gestor)
    assert resp.status_code == 200, resp.text
    assert resp.json()["acumulable"] is True
