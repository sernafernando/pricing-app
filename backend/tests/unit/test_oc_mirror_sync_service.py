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

    seen_params: list[dict] = []

    def _fake_fetch(params):
        seen_params.append(dict(params))
        if params.get("strScriptLabel") == "scriptPurchaseOrderHeader":
            # Simulate exclusive pohID floor: caller must pass poh_id-1.
            floor = int(params.get("pohID") or -1)
            return [header_row] if header_row["poh_id"] > floor else []
        return [detail_row]

    with patch.object(oc_mirror_sync_service, "_fetch_gbp", side_effect=_fake_fetch):
        synced = oc_mirror_sync_service.sync_ocs_for_pedido(db, pedido_id=pedido.id)
    db.flush()
    header_calls = [p for p in seen_params if p.get("strScriptLabel") == "scriptPurchaseOrderHeader"]
    assert header_calls and header_calls[0]["pohID"] == 499
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


@pytest.mark.parametrize("estado", ["controlado", "con_faltantes"])
def test_sync_blocked_after_deposito_control(db, empresa, proveedor, active_user, estado: str) -> None:
    pedido = _pedido(db, empresa, proveedor, active_user)
    pedido.estado = estado
    db.flush()
    with patch.object(oc_mirror_sync_service, "_fetch_gbp") as fetch:
        with pytest.raises(HTTPException) as exc:
            oc_mirror_sync_service.sync_ocs_for_pedido(db, pedido_id=pedido.id)
    assert exc.value.status_code == 409
    assert "control de depósito" in str(exc.value.detail)
    fetch.assert_not_called()


def test_sync_allowed_when_recibido_pending_control(db, empresa, proveedor, active_user) -> None:
    pedido = _pedido(db, empresa, proveedor, active_user)
    pedido.estado = "recibido"
    db.flush()
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
    assert len(synced) == 1


def test_sync_header_pohid_exclusive_floor_finds_target(db, empresa, proveedor, active_user) -> None:
    """Header script returns poh_id > pohID; exact triple still syncs (P-02-2026-00281 case)."""
    pedido = _pedido(db, empresa, proveedor, active_user)
    # Re-point to the live-broken triple shape (1,45,503).
    pedido.oc_poh_id = 503
    db.query(PedidoCompraOc).filter_by(pedido_id=pedido.id).update({"oc_poh_id": 503})
    db.flush()

    target = {
        "comp_id": 1,
        "bra_id": 45,
        "poh_id": 503,
        "supp_id": 19,
        "poh_total": 140634975.89,
        "poh_cd": "2026-11-10T15:41:08",
    }
    neighbor = {
        "comp_id": 1,
        "bra_id": 45,
        "poh_id": 504,
        "supp_id": 219,
        "poh_total": 1,
        "poh_cd": "2026-11-11T12:43:16",
    }

    def _fake_fetch(params):
        if params.get("strScriptLabel") == "scriptPurchaseOrderHeader":
            floor = int(params["pohID"])
            return [r for r in (target, neighbor) if r["poh_id"] > floor]
        return [
            {
                "comp_id": 1,
                "bra_id": 45,
                "poh_id": 503,
                "pod_id": 25823,
                "item_id": 628,
                "pod_qty": 150,
            }
        ]

    with patch.object(oc_mirror_sync_service, "_fetch_gbp", side_effect=_fake_fetch):
        synced = oc_mirror_sync_service.sync_ocs_for_pedido(db, pedido_id=pedido.id)
    assert synced[0]["oc_poh_id"] == 503
    assert db.query(PurchaseOrderHeader).filter_by(comp_id=1, bra_id=45, poh_id=503).one()
    assert db.query(PurchaseOrderHeader).filter_by(poh_id=504).count() == 0


def test_sync_updates_item_id_on_same_pod(db, empresa, proveedor, active_user) -> None:
    """Same pod_id with a new item_id must overwrite the mirror row."""
    pedido = _pedido(db, empresa, proveedor, active_user)
    db.add(
        PurchaseOrderDetail(
            comp_id=1,
            bra_id=45,
            poh_id=500,
            pod_id=7,
            item_id=100,
            pod_qty=Decimal("3"),
            pod_confirmedqty=Decimal("0"),
            pod_isprocessed=False,
        )
    )
    db.flush()

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
        "item_id": 999,
        "pod_qty": 3,
        "pod_confirmedQTY": 0,
        "pod_isProcessed": False,
    }

    def _fake_fetch(params):
        if params.get("strScriptLabel") == "scriptPurchaseOrderHeader":
            return [header_row]
        return [detail_row]

    with patch.object(oc_mirror_sync_service, "_fetch_gbp", side_effect=_fake_fetch):
        synced = oc_mirror_sync_service.sync_ocs_for_pedido(db, pedido_id=pedido.id)
    db.flush()
    assert synced[0]["detail"]["updated"] == 1
    detail = db.query(PurchaseOrderDetail).filter_by(comp_id=1, bra_id=45, poh_id=500, pod_id=7).one()
    assert int(detail.item_id) == 999


def test_sync_deletes_stale_pods_when_gbp_replaces_item_line(db, empresa, proveedor, active_user) -> None:
    """Item swap in GBP that retires pod_id must drop the old mirror row."""
    pedido = _pedido(db, empresa, proveedor, active_user)
    db.add(
        PurchaseOrderDetail(
            comp_id=1,
            bra_id=45,
            poh_id=500,
            pod_id=10,
            item_id=100,
            pod_qty=Decimal("5"),
            pod_confirmedqty=Decimal("0"),
            pod_isprocessed=False,
        )
    )
    db.flush()

    header_row = {
        "comp_id": 1,
        "bra_id": 45,
        "poh_id": 500,
        "supp_id": 99,
        "poh_total": 1500,
        "poh_cd": "2026-03-10T12:00:00",
    }
    new_line = {
        "comp_id": 1,
        "bra_id": 45,
        "poh_id": 500,
        "pod_id": 99,
        "item_id": 777,
        "pod_qty": 5,
        "pod_confirmedQTY": 0,
        "pod_isProcessed": False,
    }

    def _fake_fetch(params):
        if params.get("strScriptLabel") == "scriptPurchaseOrderHeader":
            return [header_row]
        return [new_line]

    with patch.object(oc_mirror_sync_service, "_fetch_gbp", side_effect=_fake_fetch):
        synced = oc_mirror_sync_service.sync_ocs_for_pedido(db, pedido_id=pedido.id)
    db.flush()
    assert synced[0]["detail"]["created"] == 1
    assert synced[0]["detail"]["deleted"] == 1
    rows = db.query(PurchaseOrderDetail).filter_by(comp_id=1, bra_id=45, poh_id=500).all()
    assert len(rows) == 1
    assert int(rows[0].pod_id) == 99
    assert int(rows[0].item_id) == 777
