"""Integration tests — PR4 multi-OC (add-not-replace + controlado iff all OCs).

Covers:
  - POST /vincular-oc inserts a relation row without replacing the first link
  - duplicate triple → 409
  - servicio → 409
  - partial triple → 422
  - controlado only when every linked OC is controlled
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_oc import PedidoCompraOc
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.purchase_order_detail import PurchaseOrderDetail
from app.models.purchase_order_header import PurchaseOrderHeader
from app.schemas.recepcion import IngresoLinea, RegistrarIngresosRequest
from app.services import recepcion_service

BASE = "/api/administracion/compras"


@pytest.fixture
def con_permiso_oc():
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


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=10, nombre="EmpresaMultiOC", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=42,
        nombre="PROV_MULTI_OC",
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
        numero="P-MOC-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("5000"),
        estado="aprobado",
        tipo="mercaderia",
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


def _err(response) -> str:
    body = response.json()
    err = body.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or "")
    detail = body.get("detail", "")
    if isinstance(detail, str):
        return detail
    return str(detail)


def _mk_oc(db, *, poh_id: int, supp_id: int, pod_id: int, qty: float = 10.0) -> None:
    db.add(
        PurchaseOrderHeader(
            comp_id=1,
            bra_id=1,
            poh_id=poh_id,
            supp_id=supp_id,
            poh_total=Decimal("10000"),
        )
    )
    db.add(
        PurchaseOrderDetail(
            comp_id=1,
            bra_id=1,
            poh_id=poh_id,
            pod_id=pod_id,
            stor_id=1,
            item_id=100 + pod_id,
            pod_qty=Decimal(str(qty)),
            pod_confirmedqty=Decimal("0"),
            pod_isprocessed=False,
        )
    )
    db.flush()


def _link_rows(db, pedido_id: int) -> list[tuple[int, int, int]]:
    rows = db.query(PedidoCompraOc).filter(PedidoCompraOc.pedido_id == pedido_id).order_by(PedidoCompraOc.id).all()
    return [(int(r.oc_comp_id), int(r.oc_bra_id), int(r.oc_poh_id)) for r in rows]


class TestVincularOcMulti:
    def test_add_not_replace_keeps_first_triple(self, client, auth_headers, db, pedido, proveedor, con_permiso_oc):
        _mk_oc(db, poh_id=100, supp_id=proveedor.supp_id, pod_id=1)
        _mk_oc(db, poh_id=200, supp_id=proveedor.supp_id, pod_id=2)

        first = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-oc",
            json={"oc_comp_id": 1, "oc_bra_id": 1, "oc_poh_id": 100},
            headers=auth_headers,
        )
        assert first.status_code == 200, first.text

        second = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-oc",
            json={"oc_comp_id": 1, "oc_bra_id": 1, "oc_poh_id": 200},
            headers=auth_headers,
        )
        assert second.status_code == 200, second.text

        db.refresh(pedido)
        assert pedido.oc_comp_id == 1
        assert pedido.oc_bra_id == 1
        assert pedido.oc_poh_id == 100
        assert _link_rows(db, pedido.id) == [(1, 1, 100), (1, 1, 200)]

        body = second.json()
        poh_ids = {item["oc_poh_id"] for item in body.get("ocs") or []}
        assert poh_ids == {100, 200}

    def test_duplicate_triple_409(self, client, auth_headers, db, pedido, proveedor, con_permiso_oc):
        _mk_oc(db, poh_id=12345, supp_id=proveedor.supp_id, pod_id=1)
        first = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-oc",
            json={"oc_comp_id": 1, "oc_bra_id": 1, "oc_poh_id": 12345},
            headers=auth_headers,
        )
        assert first.status_code == 200, first.text

        dup = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-oc",
            json={"oc_comp_id": 1, "oc_bra_id": 1, "oc_poh_id": 12345},
            headers=auth_headers,
        )
        assert dup.status_code == 409
        assert _link_rows(db, pedido.id) == [(1, 1, 12345)]

    def test_servicio_409(self, client, auth_headers, db, pedido, proveedor, con_permiso_oc):
        pedido.tipo = "servicio"
        db.flush()
        _mk_oc(db, poh_id=777, supp_id=proveedor.supp_id, pod_id=1)

        candidatas = client.get(
            f"{BASE}/pedidos/{pedido.id}/oc-candidatas",
            headers=auth_headers,
        )
        assert candidatas.status_code == 200
        assert candidatas.json() == []

        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-oc",
            json={"oc_comp_id": 1, "oc_bra_id": 1, "oc_poh_id": 777},
            headers=auth_headers,
        )
        assert r.status_code == 409
        assert _link_rows(db, pedido.id) == []
        header_poh = db.execute(
            text("SELECT oc_poh_id FROM pedidos_compra WHERE id = :id"),
            {"id": pedido.id},
        ).scalar()
        assert header_poh is None

    def test_partial_triple_422(self, client, auth_headers, pedido, con_permiso_oc):
        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-oc",
            json={"oc_comp_id": 1, "oc_bra_id": 1},
            headers=auth_headers,
        )
        assert r.status_code == 422
        assert "oc_comp_id, oc_bra_id, and oc_poh_id must all be provided" in (_err(r) + str(r.json()))

    def test_403_sin_permiso(self, client, auth_headers, pedido, sin_permiso_oc):
        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-oc",
            json={"oc_comp_id": 1, "oc_bra_id": 1, "oc_poh_id": 12345},
            headers=auth_headers,
        )
        assert r.status_code == 403

    def test_404_pedido_inexistente(self, client, auth_headers, con_permiso_oc):
        r = client.post(
            f"{BASE}/pedidos/9999/vincular-oc",
            json={"oc_comp_id": 1, "oc_bra_id": 1, "oc_poh_id": 12345},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_404_oc_no_existe(self, client, auth_headers, pedido, con_permiso_oc):
        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-oc",
            json={"oc_comp_id": 1, "oc_bra_id": 1, "oc_poh_id": 99999},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_409_supplier_mismatch(self, client, auth_headers, db, pedido, con_permiso_oc):
        _mk_oc(db, poh_id=55555, supp_id=999, pod_id=1)
        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-oc",
            json={"oc_comp_id": 1, "oc_bra_id": 1, "oc_poh_id": 55555},
            headers=auth_headers,
        )
        assert r.status_code == 409
        assert "supplier mismatch" in _err(r).lower()


class TestControladoIffAllOcs:
    def test_one_of_two_open_stays_non_terminal(self, db, empresa, proveedor, active_user):
        p = PedidoCompra(
            numero="P-MOC-CTRL-1",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("8000"),
            estado="recibido",
            tipo="mercaderia",
            creado_por_id=active_user.id,
        )
        db.add(p)
        db.flush()
        _mk_oc(db, poh_id=100, supp_id=proveedor.supp_id, pod_id=1, qty=10.0)
        _mk_oc(db, poh_id=200, supp_id=proveedor.supp_id, pod_id=2, qty=5.0)
        db.add(PedidoCompraOc(pedido_id=p.id, oc_comp_id=1, oc_bra_id=1, oc_poh_id=100))
        db.add(PedidoCompraOc(pedido_id=p.id, oc_comp_id=1, oc_bra_id=1, oc_poh_id=200))
        p.oc_comp_id = 1
        p.oc_bra_id = 1
        p.oc_poh_id = 100
        db.flush()

        result = recepcion_service.registrar_ingresos(
            db,
            p,
            active_user,
            RegistrarIngresosRequest(
                lineas=[IngresoLinea(pod_id=1, cantidad_recibida=Decimal("10"))],
            ),
        )
        assert result.estado_nuevo != "controlado"
        assert p.estado == "recibido"

    def test_one_of_three_open_stays_recibido_or_faltantes(self, db, empresa, proveedor, active_user):
        p = PedidoCompra(
            numero="P-MOC-CTRL-3",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("12000"),
            estado="recibido",
            tipo="mercaderia",
            creado_por_id=active_user.id,
        )
        db.add(p)
        db.flush()
        _mk_oc(db, poh_id=100, supp_id=proveedor.supp_id, pod_id=1, qty=10.0)
        _mk_oc(db, poh_id=200, supp_id=proveedor.supp_id, pod_id=2, qty=5.0)
        _mk_oc(db, poh_id=300, supp_id=proveedor.supp_id, pod_id=3, qty=8.0)
        db.add(PedidoCompraOc(pedido_id=p.id, oc_comp_id=1, oc_bra_id=1, oc_poh_id=100))
        db.add(PedidoCompraOc(pedido_id=p.id, oc_comp_id=1, oc_bra_id=1, oc_poh_id=200))
        db.add(PedidoCompraOc(pedido_id=p.id, oc_comp_id=1, oc_bra_id=1, oc_poh_id=300))
        p.oc_comp_id = 1
        p.oc_bra_id = 1
        p.oc_poh_id = 100
        db.flush()

        result = recepcion_service.registrar_ingresos(
            db,
            p,
            active_user,
            RegistrarIngresosRequest(
                lineas=[IngresoLinea(pod_id=1, cantidad_recibida=Decimal("10"))],
            ),
        )
        assert result.estado_nuevo != "controlado"
        assert p.estado == "recibido" or p.estado.startswith("faltantes")

    def test_last_oc_completes_controlado(self, db, empresa, proveedor, active_user):
        p = PedidoCompra(
            numero="P-MOC-CTRL-2",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("8000"),
            estado="recibido",
            tipo="mercaderia",
            creado_por_id=active_user.id,
        )
        db.add(p)
        db.flush()
        _mk_oc(db, poh_id=100, supp_id=proveedor.supp_id, pod_id=1, qty=10.0)
        _mk_oc(db, poh_id=200, supp_id=proveedor.supp_id, pod_id=2, qty=5.0)
        db.add(PedidoCompraOc(pedido_id=p.id, oc_comp_id=1, oc_bra_id=1, oc_poh_id=100))
        db.add(PedidoCompraOc(pedido_id=p.id, oc_comp_id=1, oc_bra_id=1, oc_poh_id=200))
        p.oc_comp_id = 1
        p.oc_bra_id = 1
        p.oc_poh_id = 100
        db.flush()

        first = recepcion_service.registrar_ingresos(
            db,
            p,
            active_user,
            RegistrarIngresosRequest(
                lineas=[IngresoLinea(pod_id=1, cantidad_recibida=Decimal("10"))],
            ),
        )
        assert first.estado_nuevo != "controlado"

        last = recepcion_service.registrar_ingresos(
            db,
            p,
            active_user,
            RegistrarIngresosRequest(
                lineas=[IngresoLinea(pod_id=2, cantidad_recibida=Decimal("5"))],
            ),
        )
        assert last.estado_nuevo == "controlado"
        assert p.estado == "controlado"
