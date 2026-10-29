"""Router: what a brand bonus reaches (`GET /api/sell-in/bonos/{id}/alcance`), sell-in-sell-out T3c-4.

The bonus panel shows four groups, each capped (`limite`) with its full count:

- `alcanzadas`: the ACTIVE sell-in purchases the worker generated for the bonus;
- `pendientes`: operations of the brand without a supplier invoice date yet
  (brand known from what was received, `pedido_compra_ingresos`);
- `fuera_de_rango`: operations of the brand invoiced outside the bonus range
  (brand known from the invoiced-lines snapshot);
- `sin_aplicar`: operations of the brand invoiced INSIDE the range with no active
  generated purchase, with why (`motivo`): the worker's queued error, no brand line
  in the invoice, or still queued.

Cancelled/rejected operations never show. Only app tables are read.
SQLite test database, like `test_sell_in_bonos.py`.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_ingresos import PedidoCompraIngreso
from app.models.pedido_compra_linea_facturada import PedidoCompraLineaFacturada
from app.models.producto import ProductoERP, TipoMoneda
from app.models.proveedor import Proveedor
from app.models.sell_in import SellInBonoDirty, SellInBonoItem, SellInBonoMarca, SellInCompra, SellInCompraItem

BASE = "/api/sell-in/bonos"
INICIO = datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc)
TP, OTRA = 4512, 4513  # TP-LINK, MERCUSYS


@pytest.fixture()
def lector(db, rol_admin, admin_auth_headers, grant_permiso):
    grant_permiso(rol_admin, "sell_in.ver")
    return admin_auth_headers


@pytest.fixture()
def mundo(db, admin_user):
    productos = [
        ProductoERP(item_id=TP, codigo="SW-8", descripcion="Switch", marca="TP-LINK", costo=10.0),
        ProductoERP(item_id=OTRA, codigo="SW-16", descripcion="Switch", marca="MERCUSYS", costo=30.0),
    ]
    for row in productos:
        row.moneda_costo = TipoMoneda.USD
    empresa = Empresa(nombre="Gauss", activo=True, orden=0)
    proveedor = Proveedor(nombre="TP-Link Argentina")
    db.add_all([*productos, empresa, proveedor])
    db.flush()
    bono = SellInBonoMarca(
        marca="TP-LINK",
        monto_unit=Decimal("3.00"),
        moneda="USD",
        fecha_desde=date(2026, 10, 1),
        fecha_hasta=date(2026, 10, 31),
        usuario_id=admin_user.id,
    )
    db.add(bono)
    db.flush()
    contador = iter(range(1, 1000))

    def pedido(fecha_factura=None, estado="aprobado", numero_factura=None) -> PedidoCompra:
        n = next(contador)
        row = PedidoCompra(
            numero=f"P-{n:05d}",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="USD",
            monto=Decimal("1000"),
            estado=estado,
            tipo="mercaderia",
            numero_factura=numero_factura,
            fecha_factura=fecha_factura,
            creado_por_id=admin_user.id,
            created_at=INICIO + timedelta(days=n),
        )
        db.add(row)
        db.flush()
        return row

    def recibido(p: PedidoCompra, item_id: int, cantidad: str) -> None:
        db.add(
            PedidoCompraIngreso(
                pedido_id=p.id, item_id=item_id, cantidad_recibida=Decimal(cantidad), usuario_id=admin_user.id
            )
        )
        db.flush()

    def facturado(p: PedidoCompra, item_id: int, cantidad: int) -> None:
        db.add(PedidoCompraLineaFacturada(pedido_id=p.id, item_id=item_id, cantidad=cantidad))
        db.flush()

    def generada(p: PedidoCompra, cantidad: int, estado: str = "activa") -> SellInCompra:
        compra = SellInCompra(
            fecha_compra=p.fecha_factura,
            proveedor_id=proveedor.id,
            moneda="USD",
            monto_total=Decimal(cantidad) * Decimal("3.00"),
            tipo_cambio=Decimal("1450"),
            formula="por_unidad",
            estado=estado,
            usuario_id=admin_user.id,
            origen="bono_marca",
            bono_id=bono.id,
            bono_pedido_id=p.id,
        )
        db.add(compra)
        db.flush()
        db.add(
            SellInCompraItem(
                compra_id=compra.id,
                item_id=TP,
                cantidad=cantidad,
                costo_base_unit=Decimal("10"),
                monto_asignado=Decimal(cantidad) * Decimal("3.00"),
            )
        )
        db.flush()
        return compra

    return {"bono": bono, "pedido": pedido, "recibido": recibido, "facturado": facturado, "generada": generada}


def _alcance(client, headers, bono_id, **params):
    resp = client.get(f"{BASE}/{bono_id}/alcance", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_needs_sell_in_ver(client, auth_headers, mundo):
    assert client.get(f"{BASE}/{mundo['bono'].id}/alcance", headers=auth_headers).status_code == 403


def test_needs_authentication(client, mundo):
    assert client.get(f"{BASE}/{mundo['bono'].id}/alcance").status_code in (401, 403)


def test_unknown_bonus_is_404(client, lector, mundo):
    resp = client.get(f"{BASE}/999999/alcance", headers=lector)
    assert resp.status_code == 404


def test_alcanzadas_are_the_active_generated_purchases_with_units_and_amount(client, lector, mundo):
    p = mundo["pedido"](fecha_factura=date(2026, 10, 5), numero_factura="A-0003-00045871")
    compra = mundo["generada"](p, 80)
    anulada = mundo["pedido"](fecha_factura=date(2026, 10, 6))
    mundo["generada"](anulada, 5, estado="anulada")

    data = _alcance(client, lector, mundo["bono"].id)

    assert data["alcanzadas"]["total"] == 1
    assert data["alcanzadas"]["items"] == [
        {
            "compra_id": compra.id,
            "pedido_id": p.id,
            "numero": p.numero,
            "proveedor_nombre": "TP-Link Argentina",
            "numero_factura": "A-0003-00045871",
            "fecha_factura": "2026-10-05",
            "unidades": 80,
            "monto": "240.00",
            "moneda": "USD",
        }
    ]


def test_pendientes_are_brand_operations_without_invoice_date(client, lector, mundo):
    sin_factura = mundo["pedido"](numero_factura="A-0007-00012233")
    mundo["recibido"](sin_factura, TP, "120")
    mundo["recibido"](sin_factura, OTRA, "7")
    otra_marca = mundo["pedido"]()
    mundo["recibido"](otra_marca, OTRA, "3")
    cancelado = mundo["pedido"](estado="cancelado")
    mundo["recibido"](cancelado, TP, "9")
    facturado = mundo["pedido"](fecha_factura=date(2026, 10, 2))
    mundo["recibido"](facturado, TP, "4")

    data = _alcance(client, lector, mundo["bono"].id)

    assert data["pendientes"]["total"] == 1
    assert data["pendientes"]["items"] == [
        {
            "pedido_id": sin_factura.id,
            "numero": sin_factura.numero,
            "proveedor_nombre": "TP-Link Argentina",
            "numero_factura": "A-0007-00012233",
            "fecha_factura": None,
            "unidades": 120,
        }
    ]


def test_fuera_de_rango_are_brand_operations_invoiced_outside_the_range(client, lector, mundo):
    antes = mundo["pedido"](fecha_factura=date(2026, 9, 28))
    mundo["facturado"](antes, TP, 15)
    despues = mundo["pedido"](fecha_factura=date(2026, 11, 1))
    mundo["facturado"](despues, TP, 2)
    mundo["facturado"](despues, OTRA, 50)
    en_rango = mundo["pedido"](fecha_factura=date(2026, 10, 31))
    mundo["facturado"](en_rango, TP, 1)
    otra_marca = mundo["pedido"](fecha_factura=date(2026, 9, 1))
    mundo["facturado"](otra_marca, OTRA, 1)
    rechazado = mundo["pedido"](fecha_factura=date(2026, 9, 2), estado="rechazado")
    mundo["facturado"](rechazado, TP, 1)

    data = _alcance(client, lector, mundo["bono"].id)

    assert data["fuera_de_rango"]["total"] == 2
    # Latest invoice first; units are only the brand's.
    assert [(i["pedido_id"], i["fecha_factura"], i["unidades"]) for i in data["fuera_de_rango"]["items"]] == [
        (despues.id, "2026-11-01", 2),
        (antes.id, "2026-09-28", 15),
    ]


def test_each_group_is_capped_but_counts_everything(client, lector, mundo):
    pendientes = []
    for dia in range(1, 6):
        p = mundo["pedido"](fecha_factura=date(2026, 10, dia))
        mundo["generada"](p, dia)
        q = mundo["pedido"]()
        mundo["recibido"](q, TP, "1")
        pendientes.append(q)
        r = mundo["pedido"](fecha_factura=date(2026, 11, dia))
        mundo["facturado"](r, TP, 1)

    data = _alcance(client, lector, mundo["bono"].id, limite=2)

    assert data["limite"] == 2
    for grupo in ("alcanzadas", "pendientes", "fuera_de_rango"):
        assert data[grupo]["total"] == 5
        assert len(data[grupo]["items"]) == 2
    # Newest invoice first; pending ones newest operation first.
    assert [i["fecha_factura"] for i in data["alcanzadas"]["items"]] == ["2026-10-05", "2026-10-04"]
    assert [i["pedido_id"] for i in data["pendientes"]["items"]] == [pendientes[-1].id, pendientes[-2].id]


def test_fractional_received_units_round_half_up_like_the_prefill(client, lector, mundo):
    medio = mundo["pedido"]()
    mundo["recibido"](medio, TP, "2.5")
    debajo = mundo["pedido"]()
    mundo["recibido"](debajo, TP, "1.4")

    data = _alcance(client, lector, mundo["bono"].id)

    assert {i["pedido_id"]: i["unidades"] for i in data["pendientes"]["items"]} == {medio.id: 3, debajo.id: 1}


@pytest.mark.parametrize("limite", [0, 101])
def test_limite_is_bounded(client, lector, mundo, limite):
    resp = client.get(f"{BASE}/{mundo['bono'].id}/alcance", params={"limite": limite}, headers=lector)
    assert resp.status_code == 422


def _rescopear(db, bono, **campos) -> None:
    """Turns the world's brand bonus into another scope (T3e)."""
    bono.marca = None
    for campo, valor in campos.items():
        setattr(bono, campo, valor)
    db.flush()


def test_a_category_bonus_panel_lists_operations_of_that_category(client, lector, mundo, db):
    db.get(ProductoERP, OTRA).categoria = "Switches"
    _rescopear(db, mundo["bono"], alcance="categoria", categoria="Switches")
    pendiente = mundo["pedido"]()
    mundo["recibido"](pendiente, OTRA, "3")
    mundo["recibido"](pendiente, TP, "9")
    fuera = mundo["pedido"](fecha_factura=date(2026, 11, 2))
    mundo["facturado"](fuera, OTRA, 4)
    solo_tp = mundo["pedido"](fecha_factura=date(2026, 11, 3))
    mundo["facturado"](solo_tp, TP, 1)

    data = _alcance(client, lector, mundo["bono"].id)

    assert [(i["pedido_id"], i["unidades"]) for i in data["pendientes"]["items"]] == [(pendiente.id, 3)]
    assert [(i["pedido_id"], i["unidades"]) for i in data["fuera_de_rango"]["items"]] == [(fuera.id, 4)]


def test_a_models_bonus_panel_lists_operations_of_its_models(client, lector, mundo, db):
    _rescopear(db, mundo["bono"], alcance="modelos")
    db.add(SellInBonoItem(bono_id=mundo["bono"].id, item_id=OTRA))
    db.flush()
    fuera = mundo["pedido"](fecha_factura=date(2026, 9, 2))
    mundo["facturado"](fuera, OTRA, 6)
    mundo["facturado"](fuera, TP, 50)
    solo_tp = mundo["pedido"](fecha_factura=date(2026, 9, 3))
    mundo["facturado"](solo_tp, TP, 1)

    data = _alcance(client, lector, mundo["bono"].id)

    assert [(i["pedido_id"], i["unidades"]) for i in data["fuera_de_rango"]["items"]] == [(fuera.id, 6)]


def test_an_invoice_bonus_panel_lists_only_its_own_operation(client, lector, mundo, db):
    suyo = mundo["pedido"](fecha_factura=date(2026, 11, 2))
    mundo["facturado"](suyo, TP, 2)
    mundo["facturado"](suyo, OTRA, 3)
    otro = mundo["pedido"](fecha_factura=date(2026, 11, 3))
    mundo["facturado"](otro, TP, 1)
    _rescopear(db, mundo["bono"], alcance="factura", pedido_id=suyo.id)

    data = _alcance(client, lector, mundo["bono"].id)

    assert [(i["pedido_id"], i["unidades"]) for i in data["fuera_de_rango"]["items"]] == [(suyo.id, 5)]
    assert data["pendientes"]["total"] == 0


# --- sin_aplicar: invoiced inside the range, but no active generated purchase (T18 follow-up) ---------------


def _encolar(db, tipo: str, ref: int, attempts: int = 0, last_error: str | None = None) -> None:
    db.add(SellInBonoDirty(tipo=tipo, ref=ref, attempts=attempts, last_error=last_error))
    db.flush()


def _sin_aplicar(data) -> list[tuple]:
    return [(i["pedido_id"], i["unidades"], i["motivo"], i["intentos"]) for i in data["sin_aplicar"]["items"]]


def test_an_in_range_invoice_the_worker_parked_shows_with_its_error(client, lector, mundo, db):
    # Prod case: pedido 278, invoiced inside the range with 21 brand lines, worker parked it after 5 failures.
    p = mundo["pedido"](fecha_factura=date(2026, 10, 22), numero_factura="A-0001-00000278")
    mundo["facturado"](p, TP, 21)
    mundo["facturado"](p, OTRA, 4)
    _encolar(db, "pedido", p.id, attempts=5, last_error="value too long for type character varying(20)")

    data = _alcance(client, lector, mundo["bono"].id)

    assert data["sin_aplicar"]["total"] == 1
    assert data["sin_aplicar"]["items"] == [
        {
            "pedido_id": p.id,
            "numero": p.numero,
            "proveedor_nombre": "TP-Link Argentina",
            "numero_factura": "A-0001-00000278",
            "fecha_factura": "2026-10-22",
            "unidades": 21,
            "motivo": "value too long for type character varying(20)",
            "intentos": 5,
            "es_error": True,
        }
    ]
    # It is in no other group.
    assert data["alcanzadas"]["total"] == data["pendientes"]["total"] == data["fuera_de_rango"]["total"] == 0


def test_only_operations_without_an_active_generated_purchase_show(client, lector, mundo):
    aplicada = mundo["pedido"](fecha_factura=date(2026, 10, 3))
    mundo["facturado"](aplicada, TP, 2)
    mundo["generada"](aplicada, 2)
    anulada = mundo["pedido"](fecha_factura=date(2026, 10, 4))
    mundo["facturado"](anulada, TP, 3)
    mundo["generada"](anulada, 3, estado="anulada")
    cancelada = mundo["pedido"](fecha_factura=date(2026, 10, 5), estado="cancelado")
    mundo["facturado"](cancelada, TP, 1)
    otra_marca = mundo["pedido"](fecha_factura=date(2026, 10, 6))
    mundo["facturado"](otra_marca, OTRA, 9)

    data = _alcance(client, lector, mundo["bono"].id)

    assert _sin_aplicar(data) == [(anulada.id, 3, "En cola", None)]


def test_an_invoice_with_no_brand_lines_says_so(client, lector, mundo):
    # Received brand units, invoice date in range, but the invoiced snapshot has no line of the brand.
    p = mundo["pedido"](fecha_factura=date(2026, 10, 10))
    mundo["recibido"](p, TP, "12")
    mundo["facturado"](p, OTRA, 5)

    data = _alcance(client, lector, mundo["bono"].id)

    assert _sin_aplicar(data) == [(p.id, 0, "Sin líneas de la marca en la factura", None)]


def test_a_parked_bonus_key_explains_every_operation_and_the_error_is_capped(client, lector, mundo, db):
    p = mundo["pedido"](fecha_factura=date(2026, 10, 12))
    mundo["facturado"](p, TP, 4)
    error = "psycopg2.errors.StringDataRightTruncation:   value too long\nDETAIL:  " + "x" * 400
    _encolar(db, "bono", mundo["bono"].id, attempts=5, last_error=error)

    data = _alcance(client, lector, mundo["bono"].id)

    [item] = data["sin_aplicar"]["items"]
    assert item["intentos"] == 5
    assert item["motivo"].startswith("psycopg2.errors.StringDataRightTruncation: value too long")
    assert "\n" not in item["motivo"]
    assert len(item["motivo"]) <= 200


def test_a_queued_key_without_error_is_still_en_cola(client, lector, mundo, db):
    p = mundo["pedido"](fecha_factura=date(2026, 10, 12))
    mundo["facturado"](p, TP, 4)
    _encolar(db, "pedido", p.id)

    data = _alcance(client, lector, mundo["bono"].id)

    assert _sin_aplicar(data) == [(p.id, 4, "En cola", 0)]
    assert data["sin_aplicar"]["items"][0]["es_error"] is False


def test_a_category_bonus_names_the_category_when_the_invoice_has_none(client, lector, mundo, db):
    db.get(ProductoERP, OTRA).categoria = "Switches"
    _rescopear(db, mundo["bono"], alcance="categoria", categoria="Switches")
    p = mundo["pedido"](fecha_factura=date(2026, 10, 15))
    mundo["recibido"](p, OTRA, "2")
    mundo["facturado"](p, TP, 7)

    data = _alcance(client, lector, mundo["bono"].id)

    assert _sin_aplicar(data) == [(p.id, 0, "Sin líneas de la categoría en la factura", None)]


def test_a_bonus_error_wins_over_an_operation_key_queued_without_error(client, lector, mundo, db):
    p = mundo["pedido"](fecha_factura=date(2026, 10, 12))
    mundo["facturado"](p, TP, 4)
    _encolar(db, "pedido", p.id)
    _encolar(db, "bono", mundo["bono"].id, attempts=3, last_error="bonus failed")

    data = _alcance(client, lector, mundo["bono"].id)

    assert _sin_aplicar(data) == [(p.id, 4, "bonus failed", 3)]
    assert data["sin_aplicar"]["items"][0]["es_error"] is True


def test_a_cancelled_bonus_has_nothing_left_to_apply(client, lector, mundo, db):
    p = mundo["pedido"](fecha_factura=date(2026, 10, 12))
    mundo["facturado"](p, TP, 4)
    mundo["bono"].estado = "anulada"
    db.commit()

    data = _alcance(client, lector, mundo["bono"].id)

    assert data["sin_aplicar"] == {"total": 0, "items": []}


def test_a_cost_bonus_reaches_sales_not_purchases_so_its_purchase_groups_are_empty(client, lector, mundo, db):
    """T25d: a 'costo_venta' bonus generates no purchase; the brand's operations are not its own."""
    bono = mundo["bono"]
    bono.base, bono.tipo, bono.monto_unit, bono.porcentaje, bono.moneda = (
        "costo_venta",
        "porcentaje",
        None,
        Decimal("2.71"),
        "ARS",
    )
    db.flush()
    pendiente = mundo["pedido"]()
    mundo["recibido"](pendiente, TP, "5")
    for fecha in (date(2026, 9, 1), date(2026, 10, 5)):
        p = mundo["pedido"](fecha_factura=fecha)
        mundo["facturado"](p, TP, 3)

    data = _alcance(client, lector, bono.id)

    vacio = {"total": 0, "items": []}
    assert {k: data[k] for k in ("alcanzadas", "pendientes", "fuera_de_rango", "sin_aplicar")} == {
        "alcanzadas": vacio,
        "pendientes": vacio,
        "fuera_de_rango": vacio,
        "sin_aplicar": vacio,
    }
