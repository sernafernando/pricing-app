"""On-demand OC mirror sync from gbp-parser into tb_purchase_order_*."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_oc import PedidoCompraOc
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.purchase_order_detail import PurchaseOrderDetail
from app.models.purchase_order_header import PurchaseOrderHeader
from app.models.usuario import Usuario
from app.services import oc_mirror_sync_service


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=1, nombre="Empresa Sync OC", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(id=1, nombre="Acme Sync", activo=True, origen=OrigenProveedor.ERP.value, supp_id=99)
    db.add(prov)
    db.flush()
    return prov


def _pedido(db, empresa: Empresa, proveedor: Proveedor, user: Usuario) -> PedidoCompra:
    pedido = PedidoCompra(
        numero="P-01-2026-00999",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("100.00"),
        estado="pagado",
        creado_por_id=user.id,
        oc_comp_id=1,
        oc_bra_id=45,
        oc_poh_id=500,
    )
    db.add(pedido)
    db.flush()
    db.add(PedidoCompraOc(pedido_id=pedido.id, oc_comp_id=1, oc_bra_id=45, oc_poh_id=500))
    db.flush()
    return pedido


def test_sync_requires_linked_oc(db, empresa, proveedor, active_user) -> None:
    pedido = PedidoCompra(
        numero="P-01-2026-00998",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("10.00"),
        estado="pagado",
        creado_por_id=active_user.id,
    )
    db.add(pedido)
    db.flush()
    with pytest.raises(HTTPException) as exc:
        oc_mirror_sync_service.sync_ocs_for_pedido(db, pedido_id=pedido.id)
    assert exc.value.status_code == 409


def test_sync_upserts_header_and_detail(db, empresa, proveedor, active_user) -> None:
    pedido = _pedido(db, empresa, proveedor, active_user)
    header_row = {
        "comp_id": 1,
        "bra_id": 45,
        "poh_id": 500,
        "supp_id": 99,
        "poh_total": 1500,
        "poh_cd": "2026-03-10T12:00:00",
    }
    detail_row = {
        "comp_id": 1,
        "bra_id": 45,
        "poh_id": 500,
        "pod_id": 7,
        "item_id": 100,
        "pod_qty": 3,
        "pod_confirmedQTY": 1,
        "pod_isProcessed": False,
    }

    def _fake_fetch(params):
        if params.get("strScriptLabel") == "scriptPurchaseOrderHeader":
            return [header_row]
        return [detail_row]

    with patch.object(oc_mirror_sync_service, "_fetch_gbp", side_effect=_fake_fetch):
        synced = oc_mirror_sync_service.sync_ocs_for_pedido(db, pedido_id=pedido.id)
    db.flush()
    assert len(synced) == 1
    assert synced[0]["detail_lines"] == 1
    assert db.query(PurchaseOrderHeader).filter_by(comp_id=1, bra_id=45, poh_id=500).one()
    detail = db.query(PurchaseOrderDetail).filter_by(comp_id=1, bra_id=45, poh_id=500, pod_id=7).one()
    assert int(detail.item_id) == 100
    assert float(detail.pod_qty) == 3.0


def test_sync_404_when_gbp_header_missing(db, empresa, proveedor, active_user) -> None:
    _pedido(db, empresa, proveedor, active_user)
    with patch.object(oc_mirror_sync_service, "_fetch_gbp", return_value=[]):
        with pytest.raises(HTTPException) as exc:
            oc_mirror_sync_service.sync_ocs_for_pedido(db, pedido_id=1)
    assert exc.value.status_code == 404
