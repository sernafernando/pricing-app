"""Integration tests — Slice 1: OC link endpoints (Batch J).

Covers:
  - GET  /pedidos/{id}/oc-candidatas
  - POST /pedidos/{id}/vincular-oc
  - DELETE /pedidos/{id}/desvincular-oc
  - GET  /pedidos/{id}/orden-compra/detalle

TDD: tests written BEFORE the endpoints existed (OC-S1.5, OC-S1.6, OC-S1.7).
All tests should be RED (404 / ImportError) until OC-S1.8/9/10 are implemented.

Mirrors pattern of test_compras_vincular_factura_endpoints.py.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.purchase_order_detail import PurchaseOrderDetail
from app.models.purchase_order_header import PurchaseOrderHeader
from app.models.tb_storage import TbStorage

BASE = "/api/administracion/compras"


# ──────────────────────────────────────────────────────────────────────────
# Permission fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def con_permiso_oc():
    """Patch PermisosService so all permission checks pass."""
    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            return_value=True,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value=set(),
        ),
    ):
        yield


@pytest.fixture
def sin_permiso_oc():
    """Patch PermisosService so gestionar_ordenes_compra is denied."""

    def _fake(self, user, codigo):
        return False

    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            new=_fake,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value=set(),
        ),
    ):
        yield


# ──────────────────────────────────────────────────────────────────────────
# Domain fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=10, nombre="EmpresaOC", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=42,
        nombre="PROV_OC",
        supp_id=42,
        comp_id=1,
        activo=True,
        origen=OrigenProveedor.ERP.value,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def pedido(db, empresa, proveedor, active_user) -> PedidoCompra:
    p = PedidoCompra(
        numero="P-OC-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("5000"),
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


def _mk_oc_header(db, *, poh_id: int, supp_id: int, comp_id: int = 1, bra_id: int = 1, total: float = 10000.0):
    """Create a PurchaseOrderHeader row for tests."""
    h = PurchaseOrderHeader(
        comp_id=comp_id,
        bra_id=bra_id,
        poh_id=poh_id,
        supp_id=supp_id,
        poh_total=Decimal(str(total)),
    )
    db.add(h)
    db.flush()
    return h


def _mk_oc_detail(
    db,
    *,
    poh_id: int,
    pod_id: int,
    comp_id: int = 1,
    bra_id: int = 1,
    stor_id: int = 1,
    item_id: int = 101,
    qty: float = 100.0,
    is_processed: bool = False,
):
    """Create a PurchaseOrderDetail row for tests."""
    d = PurchaseOrderDetail(
        comp_id=comp_id,
        bra_id=bra_id,
        poh_id=poh_id,
        pod_id=pod_id,
        stor_id=stor_id,
        item_id=item_id,
        pod_qty=Decimal(str(qty)),
        pod_confirmedqty=Decimal("0"),
        pod_isprocessed=is_processed,
    )
    db.add(d)
    db.flush()
    return d


def _mk_storage(db, *, comp_id: int = 1, stor_id: int = 1, stor_desc: str = "Depósito Principal"):
    """Create a TbStorage row for tests."""
    s = TbStorage(comp_id=comp_id, stor_id=stor_id, stor_desc=stor_desc)
    db.add(s)
    db.flush()
    return s


# ══════════════════════════════════════════════════════════════════════════
# GET /pedidos/{id}/oc-candidatas (OC-S1.5)
# ══════════════════════════════════════════════════════════════════════════


class TestOcCandidatas:
    def test_oc_candidatas_filtra_por_supp_id_y_criterio_pendiente(
        self, client, auth_headers, db, pedido, proveedor, con_permiso_oc
    ):
        """REQ-OC-002: only pending OCs for the correct supplier are returned."""
        # Pending OC (unprocessed line)
        _mk_oc_header(db, poh_id=1001, supp_id=proveedor.supp_id)
        _mk_oc_detail(db, poh_id=1001, pod_id=1, is_processed=False)
        # Non-pending OC (all lines processed)
        _mk_oc_header(db, poh_id=1002, supp_id=proveedor.supp_id)
        _mk_oc_detail(db, poh_id=1002, pod_id=2, is_processed=True)

        r = client.get(f"{BASE}/pedidos/{pedido.id}/oc-candidatas", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        poh_ids = [item["oc_poh_id"] for item in data]
        assert 1001 in poh_ids
        assert 1002 not in poh_ids

    def test_oc_candidatas_excluye_oc_no_pendiente(self, client, auth_headers, db, pedido, proveedor, con_permiso_oc):
        """REQ-OC-002, AD2: OC with all lines processed is excluded."""
        _mk_oc_header(db, poh_id=2001, supp_id=proveedor.supp_id)
        _mk_oc_detail(db, poh_id=2001, pod_id=10, is_processed=True)

        r = client.get(f"{BASE}/pedidos/{pedido.id}/oc-candidatas", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == []

    def test_oc_candidatas_excluye_ya_vinculada_a_otro_pedido(
        self, client, auth_headers, db, empresa, proveedor, pedido, active_user, con_permiso_oc
    ):
        """REQ-OC-002: OC already linked to another pedido is excluded."""
        _mk_oc_header(db, poh_id=3001, supp_id=proveedor.supp_id)
        _mk_oc_detail(db, poh_id=3001, pod_id=20, is_processed=False)
        # Link OC 3001 to another pedido
        p2 = PedidoCompra(
            numero="P-OC-00002",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            estado="aprobado",
            creado_por_id=active_user.id,
            oc_comp_id=1,
            oc_bra_id=1,
            oc_poh_id=3001,
        )
        db.add(p2)
        db.flush()

        r = client.get(f"{BASE}/pedidos/{pedido.id}/oc-candidatas", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == []

    def test_oc_candidatas_retorna_lista_vacia_sin_ocs(self, client, auth_headers, pedido, con_permiso_oc):
        """REQ-OC-002: empty list when no pending OCs."""
        r = client.get(f"{BASE}/pedidos/{pedido.id}/oc-candidatas", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == []

    def test_oc_candidatas_403_sin_permiso(self, client, auth_headers, pedido, sin_permiso_oc):
        """REQ-OC-010: 403 without gestionar_ordenes_compra."""
        r = client.get(f"{BASE}/pedidos/{pedido.id}/oc-candidatas", headers=auth_headers)
        assert r.status_code == 403

    def test_oc_candidatas_404_pedido_inexistente(self, client, auth_headers, con_permiso_oc):
        """REQ-OC-012: 404 for non-existent pedido_id."""
        r = client.get(f"{BASE}/pedidos/9999/oc-candidatas", headers=auth_headers)
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════
# POST /pedidos/{id}/vincular-oc (OC-S1.6)
# ══════════════════════════════════════════════════════════════════════════


class TestVincularOC:
    def test_vincular_oc_setea_3_cols(self, client, auth_headers, db, pedido, proveedor, con_permiso_oc):
        """REQ-OC-003: successful link sets all 3 OC columns."""
        _mk_oc_header(db, poh_id=12345, supp_id=proveedor.supp_id)
        _mk_oc_detail(db, poh_id=12345, pod_id=1, is_processed=False)

        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-oc",
            json={"oc_comp_id": 1, "oc_bra_id": 1, "oc_poh_id": 12345},
            headers=auth_headers,
        )
        assert r.status_code == 200
        db.refresh(pedido)
        assert pedido.oc_poh_id == 12345
        assert pedido.oc_comp_id == 1
        assert pedido.oc_bra_id == 1

    def test_vincular_oc_409_ya_vinculado(self, client, auth_headers, db, pedido, proveedor, con_permiso_oc):
        """REQ-OC-003: 409 if pedido already has a linked OC."""
        _mk_oc_header(db, poh_id=100, supp_id=proveedor.supp_id)
        _mk_oc_detail(db, poh_id=100, pod_id=1, is_processed=False)
        _mk_oc_header(db, poh_id=200, supp_id=proveedor.supp_id)
        _mk_oc_detail(db, poh_id=200, pod_id=2, is_processed=False)

        pedido.oc_comp_id = 1
        pedido.oc_bra_id = 1
        pedido.oc_poh_id = 100
        db.flush()

        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-oc",
            json={"oc_comp_id": 1, "oc_bra_id": 1, "oc_poh_id": 200},
            headers=auth_headers,
        )
        assert r.status_code == 409
        assert "Unlink first" in r.json()["error"]["message"]

    def test_vincular_oc_404_oc_no_existe(self, client, auth_headers, pedido, con_permiso_oc):
        """REQ-OC-003: 404 when OC does not exist in ERP."""
        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-oc",
            json={"oc_comp_id": 1, "oc_bra_id": 1, "oc_poh_id": 99999},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_vincular_oc_409_proveedor_mismatch(self, client, auth_headers, db, pedido, con_permiso_oc):
        """REQ-OC-003: 409 when OC belongs to a different supplier."""
        _mk_oc_header(db, poh_id=55555, supp_id=999)  # different supp_id
        _mk_oc_detail(db, poh_id=55555, pod_id=1, is_processed=False)

        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-oc",
            json={"oc_comp_id": 1, "oc_bra_id": 1, "oc_poh_id": 55555},
            headers=auth_headers,
        )
        assert r.status_code == 409
        assert "supplier mismatch" in r.json()["error"]["message"].lower()

    def test_vincular_oc_403_sin_permiso(self, client, auth_headers, pedido, sin_permiso_oc):
        """REQ-OC-010: 403 without permission."""
        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-oc",
            json={"oc_comp_id": 1, "oc_bra_id": 1, "oc_poh_id": 12345},
            headers=auth_headers,
        )
        assert r.status_code == 403

    def test_vincular_oc_404_pedido_inexistente(self, client, auth_headers, con_permiso_oc):
        """REQ-OC-012: 404 for non-existent pedido."""
        r = client.post(
            f"{BASE}/pedidos/9999/vincular-oc",
            json={"oc_comp_id": 1, "oc_bra_id": 1, "oc_poh_id": 12345},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_desvincular_oc_limpia_3_cols(self, client, auth_headers, db, pedido, proveedor, con_permiso_oc):
        """REQ-OC-004: DELETE clears the 3 OC columns."""
        _mk_oc_header(db, poh_id=77777, supp_id=proveedor.supp_id)
        pedido.oc_comp_id = 1
        pedido.oc_bra_id = 1
        pedido.oc_poh_id = 77777
        db.flush()

        r = client.delete(
            f"{BASE}/pedidos/{pedido.id}/desvincular-oc",
            headers=auth_headers,
        )
        assert r.status_code == 204
        db.refresh(pedido)
        assert pedido.oc_poh_id is None
        assert pedido.oc_comp_id is None
        assert pedido.oc_bra_id is None

    def test_desvincular_oc_409_sin_oc_vinculada(self, client, auth_headers, pedido, con_permiso_oc):
        """REQ-OC-004: 409 when pedido has no linked OC."""
        r = client.delete(
            f"{BASE}/pedidos/{pedido.id}/desvincular-oc",
            headers=auth_headers,
        )
        assert r.status_code == 409
        assert "no linked OC" in r.json()["error"]["message"]

    def test_desvincular_oc_403_sin_permiso(self, client, auth_headers, db, pedido, proveedor, sin_permiso_oc):
        """REQ-OC-010: 403 without permission."""
        pedido.oc_comp_id = 1
        pedido.oc_bra_id = 1
        pedido.oc_poh_id = 77777
        db.flush()
        r = client.delete(
            f"{BASE}/pedidos/{pedido.id}/desvincular-oc",
            headers=auth_headers,
        )
        assert r.status_code == 403

    def test_relink_via_desvincular_vincular(self, client, auth_headers, db, pedido, proveedor, con_permiso_oc):
        """REQ-OC-005: re-link works via DELETE + POST."""
        _mk_oc_header(db, poh_id=100, supp_id=proveedor.supp_id)
        _mk_oc_detail(db, poh_id=100, pod_id=1, is_processed=False)
        _mk_oc_header(db, poh_id=200, supp_id=proveedor.supp_id)
        _mk_oc_detail(db, poh_id=200, pod_id=2, is_processed=False)

        pedido.oc_comp_id = 1
        pedido.oc_bra_id = 1
        pedido.oc_poh_id = 100
        db.flush()

        r1 = client.delete(f"{BASE}/pedidos/{pedido.id}/desvincular-oc", headers=auth_headers)
        assert r1.status_code == 204

        r2 = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-oc",
            json={"oc_comp_id": 1, "oc_bra_id": 1, "oc_poh_id": 200},
            headers=auth_headers,
        )
        assert r2.status_code == 200
        db.refresh(pedido)
        assert pedido.oc_poh_id == 200


# ══════════════════════════════════════════════════════════════════════════
# GET /pedidos/{id}/orden-compra/detalle (OC-S1.7)
# ══════════════════════════════════════════════════════════════════════════


class TestOrdenCompraDetalle:
    def test_orden_compra_detalle_retorna_lineas_por_deposito(
        self, client, auth_headers, db, pedido, proveedor, con_permiso_oc
    ):
        """REQ-OC-006, EC-01: breakdown returns all lines without collapsing."""
        # Link OC to pedido
        _mk_oc_header(db, poh_id=12345, supp_id=proveedor.supp_id)
        _mk_storage(db, comp_id=1, stor_id=1, stor_desc="Depósito A")
        _mk_storage(db, comp_id=1, stor_id=2, stor_desc="Depósito B")
        _mk_oc_detail(db, poh_id=12345, pod_id=1, stor_id=1, item_id=5001, qty=40.0)
        _mk_oc_detail(db, poh_id=12345, pod_id=2, stor_id=2, item_id=5001, qty=60.0)
        _mk_oc_detail(db, poh_id=12345, pod_id=3, stor_id=1, item_id=5002, qty=20.0)

        pedido.oc_comp_id = 1
        pedido.oc_bra_id = 1
        pedido.oc_poh_id = 12345
        db.flush()

        r = client.get(f"{BASE}/pedidos/{pedido.id}/orden-compra/detalle", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert len(data["lines"]) == 3
        pod_ids = {line["pod_id"] for line in data["lines"]}
        assert pod_ids == {1, 2, 3}

    def test_orden_compra_detalle_409_sin_oc_vinculada(self, client, auth_headers, pedido, con_permiso_oc):
        """REQ-OC-006: 409 when pedido has no linked OC."""
        r = client.get(f"{BASE}/pedidos/{pedido.id}/orden-compra/detalle", headers=auth_headers)
        assert r.status_code == 409
        assert "no linked oc" in r.json()["error"]["message"].lower()

    def test_orden_compra_detalle_403_sin_permiso(self, client, auth_headers, pedido, sin_permiso_oc):
        """REQ-OC-010: 403 without permission."""
        r = client.get(f"{BASE}/pedidos/{pedido.id}/orden-compra/detalle", headers=auth_headers)
        assert r.status_code == 403

    def test_orden_compra_detalle_no_escribe_erp(self, client, auth_headers, db, pedido, proveedor, con_permiso_oc):
        """REQ-OC-011: GET detalle never writes to ERP tables."""
        _mk_oc_header(db, poh_id=99000, supp_id=proveedor.supp_id)
        _mk_oc_detail(db, poh_id=99000, pod_id=1, qty=10.0)

        pedido.oc_comp_id = 1
        pedido.oc_bra_id = 1
        pedido.oc_poh_id = 99000
        db.flush()

        count_before = db.execute(text("SELECT COUNT(*) FROM tb_purchase_order_detail")).scalar()

        client.get(f"{BASE}/pedidos/{pedido.id}/orden-compra/detalle", headers=auth_headers)

        count_after = db.execute(text("SELECT COUNT(*) FROM tb_purchase_order_detail")).scalar()
        assert count_before == count_after
