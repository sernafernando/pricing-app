"""List GET /pedidos filters: q_oc, creado_por_id, q_producto (separate from q_numero)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_oc import PedidoCompraOc
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.purchase_order_detail import PurchaseOrderDetail
from app.models.purchase_order_header import PurchaseOrderHeader
from app.core.security import get_password_hash
from app.models.tb_item import TBItem
from app.models.usuario import Usuario

BASE = "/api/administracion/compras"


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=1, nombre="Empresa Filtros", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(id=1, nombre="Prov Filtros", activo=True, origen=OrigenProveedor.ERP.value, supp_id=19)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def con_ver_oc():
    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            return_value=True,
        ),
        patch(
            "app.services.permisos_service.PermisosService.tiene_algun_permiso",
            return_value=True,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value={"administracion.ver_ordenes_compra"},
        ),
    ):
        yield


def _pedido(
    db,
    *,
    empresa: Empresa,
    proveedor: Proveedor,
    user: Usuario,
    numero: str,
    estado: str = "pagado",
    oc_poh_id: int | None = None,
    oc_bra_id: int = 45,
    oc_comp_id: int = 1,
) -> PedidoCompra:
    p = PedidoCompra(
        numero=numero,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("100"),
        estado=estado,
        creado_por_id=user.id,
        oc_comp_id=oc_comp_id if oc_poh_id is not None else None,
        oc_bra_id=oc_bra_id if oc_poh_id is not None else None,
        oc_poh_id=oc_poh_id,
    )
    db.add(p)
    db.flush()
    if oc_poh_id is not None:
        db.add(
            PedidoCompraOc(
                pedido_id=p.id,
                oc_comp_id=oc_comp_id,
                oc_bra_id=oc_bra_id,
                oc_poh_id=oc_poh_id,
            )
        )
        db.flush()
    return p


def _oc_line(
    db,
    *,
    poh_id: int,
    pod_id: int,
    item_id: int,
    item_code: str,
    item_desc: str,
    bra_id: int = 45,
    comp_id: int = 1,
) -> None:
    if db.get(PurchaseOrderHeader, (comp_id, bra_id, poh_id)) is None:
        db.add(
            PurchaseOrderHeader(
                comp_id=comp_id,
                bra_id=bra_id,
                poh_id=poh_id,
                supp_id=19,
                poh_total=Decimal("10"),
            )
        )
        db.flush()
    if db.get(TBItem, (comp_id, item_id)) is None:
        db.add(TBItem(comp_id=comp_id, item_id=item_id, item_code=item_code, item_desc=item_desc))
        db.flush()
    db.add(
        PurchaseOrderDetail(
            comp_id=comp_id,
            bra_id=bra_id,
            poh_id=poh_id,
            pod_id=pod_id,
            item_id=item_id,
            pod_qty=Decimal("1"),
            pod_confirmedqty=Decimal("0"),
            pod_isprocessed=False,
        )
    )
    db.flush()


def test_q_numero_does_not_match_oc_poh_id(client, auth_headers, db, empresa, proveedor, active_user, con_ver_oc):
    """Pedido number '503' must not collide with OC poh_id 503."""
    p_num = _pedido(db, empresa=empresa, proveedor=proveedor, user=active_user, numero="P-02-2026-00503")
    p_oc = _pedido(
        db,
        empresa=empresa,
        proveedor=proveedor,
        user=active_user,
        numero="P-02-2026-00281",
        oc_poh_id=503,
    )
    r = client.get(f"{BASE}/pedidos", headers=auth_headers, params={"q_numero": "503", "page_size": 50})
    assert r.status_code == 200, r.text
    ids = {i["id"] for i in r.json()["items"]}
    assert p_num.id in ids
    assert p_oc.id not in ids


def test_q_oc_exact_poh_id(client, auth_headers, db, empresa, proveedor, active_user, con_ver_oc):
    hit = _pedido(
        db,
        empresa=empresa,
        proveedor=proveedor,
        user=active_user,
        numero="P-OC-HIT",
        oc_poh_id=503,
    )
    _pedido(
        db,
        empresa=empresa,
        proveedor=proveedor,
        user=active_user,
        numero="P-OC-MISS",
        oc_poh_id=504,
    )
    r = client.get(f"{BASE}/pedidos", headers=auth_headers, params={"q_oc": "503"})
    assert r.status_code == 200, r.text
    assert {i["id"] for i in r.json()["items"]} == {hit.id}


def test_q_oc_rejects_non_digits(client, auth_headers, con_ver_oc):
    r = client.get(f"{BASE}/pedidos", headers=auth_headers, params={"q_oc": "45/503"})
    assert r.status_code == 422


def test_creado_por_id_filter(client, auth_headers, db, empresa, proveedor, active_user, con_ver_oc):
    other = Usuario(
        username="otro_creador",
        nombre="Otro Creador",
        email="otro@example.com",
        password_hash=get_password_hash("test-password"),
        activo=True,
        rol_id=active_user.rol_id,
    )
    db.add(other)
    db.flush()
    mine = _pedido(db, empresa=empresa, proveedor=proveedor, user=active_user, numero="P-MINE")
    _pedido(db, empresa=empresa, proveedor=proveedor, user=other, numero="P-OTHER")

    r = client.get(f"{BASE}/pedidos", headers=auth_headers, params={"creado_por_id": active_user.id})
    assert r.status_code == 200, r.text
    assert {i["id"] for i in r.json()["items"]} == {mine.id}

    pool = client.get(f"{BASE}/usuarios-filtro-creado-por", headers=auth_headers)
    assert pool.status_code == 200, pool.text
    pool_ids = {u["id"] for u in pool.json()}
    assert active_user.id in pool_ids
    assert other.id in pool_ids


def test_q_producto_matches_ean_and_desc(client, auth_headers, db, empresa, proveedor, active_user, con_ver_oc):
    hit = _pedido(
        db,
        empresa=empresa,
        proveedor=proveedor,
        user=active_user,
        numero="P-PROD-HIT",
        oc_poh_id=9001,
    )
    _pedido(
        db,
        empresa=empresa,
        proveedor=proveedor,
        user=active_user,
        numero="P-PROD-MISS",
        oc_poh_id=9002,
    )
    _oc_line(
        db,
        poh_id=9001,
        pod_id=1,
        item_id=70,
        item_code="1210002615013",
        item_desc="CAMARA IP WIFI TP LINK TAPO C200",
    )
    _oc_line(
        db,
        poh_id=9002,
        pod_id=1,
        item_id=30,
        item_code="4897098687376",
        item_desc="PLACA DE RED ETHERNET",
    )

    by_ean = client.get(f"{BASE}/pedidos", headers=auth_headers, params={"q_producto": "1210002615013"})
    assert by_ean.status_code == 200, by_ean.text
    assert {i["id"] for i in by_ean.json()["items"]} == {hit.id}

    by_name = client.get(f"{BASE}/pedidos", headers=auth_headers, params={"q_producto": "TAPO C200"})
    assert by_name.status_code == 200, by_name.text
    assert {i["id"] for i in by_name.json()["items"]} == {hit.id}


def test_q_producto_min_length(client, auth_headers, con_ver_oc):
    r = client.get(f"{BASE}/pedidos", headers=auth_headers, params={"q_producto": "a"})
    assert r.status_code == 422
