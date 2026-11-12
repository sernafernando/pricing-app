"""Partial arribo/retiro progress — separate from control tandas."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_arribo_progreso import PedidoCompraArriboProgreso
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.purchase_order_detail import PurchaseOrderDetail
from app.models.purchase_order_header import PurchaseOrderHeader
from app.schemas.recepcion import ArriboProgresoLineaRequest, RegistrarArriboProgresoRequest
from app.services import recepcion_service


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=21, nombre="EmpresaArribo", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=77,
        nombre="PROV_ARRIBO",
        supp_id=77,
        comp_id=1,
        activo=True,
        origen=OrigenProveedor.ERP.value,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def pedido_oc(db, empresa, proveedor, active_user) -> PedidoCompra:
    p = PedidoCompra(
        numero="P-ARRIBO-001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("10000"),
        estado="pagado",
        requiere_envio=True,
        oc_comp_id=1,
        oc_bra_id=1,
        oc_poh_id=8001,
        creado_por_id=active_user.id,
        responsable_id=active_user.id,
    )
    db.add(p)
    db.flush()
    db.add(PurchaseOrderHeader(comp_id=1, bra_id=1, poh_id=8001, supp_id=77, poh_total=Decimal("10000")))
    db.add(
        PurchaseOrderDetail(
            comp_id=1,
            bra_id=1,
            poh_id=8001,
            pod_id=1,
            stor_id=1,
            item_id=101,
            pod_qty=Decimal("100"),
            pod_confirmedqty=Decimal("0"),
            pod_isprocessed=False,
        )
    )
    db.add(
        PurchaseOrderDetail(
            comp_id=1,
            bra_id=1,
            poh_id=8001,
            pod_id=2,
            stor_id=1,
            item_id=102,
            pod_qty=Decimal("40"),
            pod_confirmedqty=Decimal("0"),
            pod_isprocessed=False,
        )
    )
    db.flush()
    return p


def test_parcial_queda_en_por_recibir(db, pedido_oc, active_user):
    result = recepcion_service.registrar_arribo_progreso(
        db,
        pedido_oc,
        active_user,
        RegistrarArriboProgresoRequest(lineas=[ArriboProgresoLineaRequest(pod_id=1, cantidad=Decimal("30"))]),
    )
    assert result.cerrado is False
    assert result.estado_nuevo == "pagado"
    assert result.arribo_en_curso is True
    assert pedido_oc.estado == "pagado"
    assert db.query(PedidoCompraArriboProgreso).filter_by(pedido_id=pedido_oc.id).count() == 1


def test_cubrir_total_no_cierra_solo_guardar(db, pedido_oc, active_user):
    result = recepcion_service.registrar_arribo_progreso(
        db,
        pedido_oc,
        active_user,
        RegistrarArriboProgresoRequest(
            lineas=[
                ArriboProgresoLineaRequest(pod_id=1, cantidad=Decimal("100")),
                ArriboProgresoLineaRequest(pod_id=2, cantidad=Decimal("40")),
            ]
        ),
    )
    assert result.cerrado is False
    assert pedido_oc.estado == "pagado"
    assert all(l.pendiente_arribo == 0 for l in result.lineas)


def test_one_click_confirmar_sin_progreso(db, pedido_oc, active_user):
    """Without partial rows, confirmar still closes (legacy one-click arrival)."""
    closed = recepcion_service.confirmar_arribo_con_oc(db, pedido_oc, active_user)
    assert closed.estado_nuevo == "recibido"
    assert pedido_oc.estado == "recibido"


def test_marcar_completo_con_progreso_parcial_requiere_cobertura(db, pedido_oc, active_user):
    recepcion_service.registrar_arribo_progreso(
        db,
        pedido_oc,
        active_user,
        RegistrarArriboProgresoRequest(lineas=[ArriboProgresoLineaRequest(pod_id=1, cantidad=Decimal("30"))]),
    )
    with pytest.raises(HTTPException) as exc:
        recepcion_service.confirmar_arribo_con_oc(db, pedido_oc, active_user)
    assert exc.value.status_code == 409

    recepcion_service.registrar_arribo_progreso(
        db,
        pedido_oc,
        active_user,
        RegistrarArriboProgresoRequest(
            lineas=[
                ArriboProgresoLineaRequest(pod_id=1, cantidad=Decimal("70")),
                ArriboProgresoLineaRequest(pod_id=2, cantidad=Decimal("40")),
            ]
        ),
    )
    closed = recepcion_service.confirmar_arribo_con_oc(db, pedido_oc, active_user)
    assert closed.estado_nuevo == "recibido"
    assert pedido_oc.estado == "recibido"


def test_over_arribo_409(db, pedido_oc, active_user):
    with pytest.raises(HTTPException) as exc:
        recepcion_service.registrar_arribo_progreso(
            db,
            pedido_oc,
            active_user,
            RegistrarArriboProgresoRequest(lineas=[ArriboProgresoLineaRequest(pod_id=1, cantidad=Decimal("101"))]),
        )
    assert exc.value.status_code == 409


def test_deshacer_recibido_wipe_progreso(db, pedido_oc, active_user):
    recepcion_service.registrar_arribo_progreso(
        db,
        pedido_oc,
        active_user,
        RegistrarArriboProgresoRequest(
            lineas=[
                ArriboProgresoLineaRequest(pod_id=1, cantidad=Decimal("100")),
                ArriboProgresoLineaRequest(pod_id=2, cantidad=Decimal("40")),
            ]
        ),
    )
    recepcion_service.confirmar_arribo_con_oc(db, pedido_oc, active_user)
    assert pedido_oc.estado == "recibido"
    assert db.query(PedidoCompraArriboProgreso).filter_by(pedido_id=pedido_oc.id).count() >= 1

    recepcion_service.deshacer_recibido(db, pedido_oc, active_user)
    assert pedido_oc.estado == "pagado"
    assert db.query(PedidoCompraArriboProgreso).filter_by(pedido_id=pedido_oc.id).count() == 0
