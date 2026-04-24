"""Integration tests de los endpoints de vinculación de factura (Batch I).

Cubre:
  - GET /pedidos/{id}/facturas-candidatas
  - POST /pedidos/{id}/vincular-factura (sin ajuste + con ajuste + 403 sin permiso + 400 sin motivo)
  - POST /pedidos/{id}/desvincular-factura

Los tests usan la vista SQLite ad-hoc creada por el fixture `_crear_vista`
(mismo patrón que `test_erp_matching_service.py` — Alembic no corre en SQLite).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.commercial_transaction import CommercialTransaction
from app.models.compra_evento import CompraEvento
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.tb_sale_document import SaleDocument

BASE = "/api/administracion/compras"


_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS v_facturas_compra_vigentes AS
SELECT
    ct.ct_transaction,
    ct.comp_id,
    ct.bra_id,
    ct.supp_id,
    ct.ct_docnumber,
    ct.ct_total,
    ct.curr_id_transaction,
    ct.ct_date,
    ct.sd_id,
    sd.sd_desc,
    sd.hacc_group,
    sd.sd_plusorminus,
    'FACTURA' AS clasificacion
FROM tb_commercial_transactions ct
JOIN tb_sale_document sd ON sd.sd_id = ct.sd_id
WHERE sd.sd_ispurchase = 1
  AND sd.sd_isannulment = 0
  AND sd.sd_ispackinglist = 0
  AND sd.sd_isquotation = 0
  AND ct.supp_id IS NOT NULL
  AND ct.ct_docnumber IS NOT NULL;
"""


@pytest.fixture(autouse=True)
def _crear_vista(db):
    db.execute(text("DROP VIEW IF EXISTS v_facturas_compra_vigentes"))
    db.execute(text(_VIEW_SQL))


@pytest.fixture
def con_todos_los_permisos():
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
def con_gestionar_pero_sin_ajustar_monto():
    """Tiene gestionar_ordenes_compra pero NO ajustar_monto_pedido."""

    def _fake(self, user, codigo):
        if codigo == "administracion.ajustar_monto_pedido":
            return False
        return True

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
    e = Empresa(id=1, nombre="EmpresaVinc", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=77,
        nombre="PROV_E2E",
        supp_id=77,
        comp_id=1,
        activo=True,
        origen=OrigenProveedor.ERP.value,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def sd_factura(db) -> SaleDocument:
    sd = SaleDocument(
        sd_id=101,
        sd_desc="Factura",
        sd_ispurchase=True,
        sd_isinbalance=True,
        sd_istaxable=True,
        sd_plusorminus=1,
        hacc_group=7001,
    )
    db.add(sd)
    db.flush()
    return sd


@pytest.fixture
def pedido(db, empresa, proveedor, active_user) -> PedidoCompra:
    p = PedidoCompra(
        numero="P-E2E-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("1000"),
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


def _mk_ct(db, *, ct_transaction, supp_id, ct_total, docnum="DOC123"):
    ct = CommercialTransaction(
        ct_transaction=ct_transaction,
        comp_id=1,
        bra_id=1,
        supp_id=supp_id,
        ct_docNumber=docnum,
        sd_id=101,
        ct_total=ct_total,
        ct_date=datetime(2026, 4, 15, 10, 0, 0),
        ct_isCancelled=False,
    )
    db.add(ct)
    db.flush()
    return ct


# ══════════════════════════════════════════════════════════════════════════
# GET /pedidos/{id}/facturas-candidatas
# ══════════════════════════════════════════════════════════════════════════


class TestFacturasCandidatas:
    def test_lista_vacia_si_no_hay_cts(self, client, auth_headers, pedido, sd_factura, con_todos_los_permisos):
        r = client.get(
            f"{BASE}/pedidos/{pedido.id}/facturas-candidatas",
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json() == []

    def test_devuelve_facturas_del_supp(
        self, client, auth_headers, db, pedido, proveedor, sd_factura, con_todos_los_permisos
    ):
        _mk_ct(db, ct_transaction=111, supp_id=proveedor.supp_id, ct_total=Decimal("500"))
        _mk_ct(db, ct_transaction=112, supp_id=proveedor.supp_id, ct_total=Decimal("750"), docnum="D2")
        # otro supp → NO debe aparecer
        _mk_ct(db, ct_transaction=113, supp_id=999, ct_total=Decimal("999"), docnum="D3")

        r = client.get(
            f"{BASE}/pedidos/{pedido.id}/facturas-candidatas",
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        cts = {row["ct_transaction"] for row in data}
        assert cts == {111, 112}

    def test_excluye_cts_ya_vinculadas_a_otros_pedidos(
        self,
        client,
        auth_headers,
        db,
        empresa,
        proveedor,
        pedido,
        sd_factura,
        active_user,
        con_todos_los_permisos,
    ):
        _mk_ct(db, ct_transaction=201, supp_id=proveedor.supp_id, ct_total=Decimal("100"))
        _mk_ct(db, ct_transaction=202, supp_id=proveedor.supp_id, ct_total=Decimal("200"), docnum="D2")
        # otro pedido ya vinculado a 202
        p2 = PedidoCompra(
            numero="P-E2E-00002",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("200"),
            estado="aprobado",
            ct_transaction_id=202,
            creado_por_id=active_user.id,
        )
        db.add(p2)
        db.flush()

        r = client.get(
            f"{BASE}/pedidos/{pedido.id}/facturas-candidatas",
            headers=auth_headers,
        )
        cts = {row["ct_transaction"] for row in r.json()}
        assert cts == {201}


# ══════════════════════════════════════════════════════════════════════════
# POST /pedidos/{id}/vincular-factura
# ══════════════════════════════════════════════════════════════════════════


class TestVincularFacturaEndpoint:
    def test_happy_sin_ajuste(self, client, auth_headers, db, pedido, proveedor, sd_factura, con_todos_los_permisos):
        _mk_ct(db, ct_transaction=300, supp_id=proveedor.supp_id, ct_total=Decimal("1000"))

        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-factura",
            headers=auth_headers,
            json={"ct_transaction": 300, "ajustar_monto": False},
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ct_transaction_id"] == 300

    def test_happy_con_ajuste_aumento(
        self, client, auth_headers, db, pedido, proveedor, sd_factura, con_todos_los_permisos
    ):
        _mk_ct(db, ct_transaction=301, supp_id=proveedor.supp_id, ct_total=Decimal("1200"))

        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-factura",
            headers=auth_headers,
            json={
                "ct_transaction": 301,
                "ajustar_monto": True,
                "nuevo_monto": "1200",
                "motivo_ajuste": "TC variable al pagar",
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ct_transaction_id"] == 301
        assert Decimal(data["monto"]) == Decimal("1200")

    def test_ajuste_sin_permiso_403(
        self,
        client,
        auth_headers,
        db,
        pedido,
        proveedor,
        sd_factura,
        con_gestionar_pero_sin_ajustar_monto,
    ):
        _mk_ct(db, ct_transaction=302, supp_id=proveedor.supp_id, ct_total=Decimal("1100"))

        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-factura",
            headers=auth_headers,
            json={
                "ct_transaction": 302,
                "ajustar_monto": True,
                "nuevo_monto": "1100",
                "motivo_ajuste": "diff",
            },
        )
        assert r.status_code == 403, r.text

    def test_ajuste_sin_motivo_400(
        self, client, auth_headers, db, pedido, proveedor, sd_factura, con_todos_los_permisos
    ):
        _mk_ct(db, ct_transaction=303, supp_id=proveedor.supp_id, ct_total=Decimal("1100"))

        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-factura",
            headers=auth_headers,
            json={
                "ct_transaction": 303,
                "ajustar_monto": True,
                "nuevo_monto": "1100",
                # motivo_ajuste omitido
            },
        )
        assert r.status_code == 400, r.text

    def test_ajuste_sin_nuevo_monto_400(
        self, client, auth_headers, db, pedido, proveedor, sd_factura, con_todos_los_permisos
    ):
        _mk_ct(db, ct_transaction=304, supp_id=proveedor.supp_id, ct_total=Decimal("1100"))

        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-factura",
            headers=auth_headers,
            json={
                "ct_transaction": 304,
                "ajustar_monto": True,
                "motivo_ajuste": "x",
            },
        )
        assert r.status_code == 400, r.text

    def test_ajuste_sin_imputaciones_update_directo_sin_mov_cc(
        self, client, auth_headers, db, pedido, proveedor, sd_factura, con_todos_los_permisos
    ):
        """Sub-batch 4: pedido sin imputaciones → UPDATE directo SIN mov CC."""
        _mk_ct(db, ct_transaction=305, supp_id=proveedor.supp_id, ct_total=Decimal("1500"))
        count_movs_antes = db.query(CCProveedorMovimiento).count()

        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-factura",
            headers=auth_headers,
            json={
                "ct_transaction": 305,
                "ajustar_monto": True,
                "nuevo_monto": "1500",
                "motivo_ajuste": "monto real factura",
            },
        )
        assert r.status_code == 200, r.text
        assert Decimal(r.json()["monto"]) == Decimal("1500")

        # El movimiento CC NO debe haberse creado (UPDATE directo).
        count_movs_despues = db.query(CCProveedorMovimiento).count()
        assert count_movs_despues == count_movs_antes

        # El evento registrado debe ser `monto_actualizado_sin_imputaciones`.
        eventos = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_PEDIDO,
                CompraEvento.entidad_id == pedido.id,
                CompraEvento.tipo == "monto_actualizado_sin_imputaciones",
            )
            .all()
        )
        assert len(eventos) == 1
        assert eventos[0].payload["tenia_imputaciones_vivas"] is False

    def test_ajuste_con_imputaciones_genera_mov_cc(
        self,
        client,
        auth_headers,
        db,
        pedido,
        proveedor,
        sd_factura,
        active_user,
        con_todos_los_permisos,
    ):
        """Sub-batch 4: pedido CON imputaciones vigentes → ajuste compensatorio CC."""
        _mk_ct(db, ct_transaction=306, supp_id=proveedor.supp_id, ct_total=Decimal("1800"))

        # Seedeo imputación viva al pedido (simulando una OP ya aplicada).
        imp = Imputacion(
            origen_tipo="orden_pago",
            origen_id=1,
            destino_tipo="pedido_compra",
            destino_id=pedido.id,
            monto_imputado=Decimal("500"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            es_reversal=False,
            creado_por_id=active_user.id,
        )
        db.add(imp)
        db.flush()

        count_movs_antes = db.query(CCProveedorMovimiento).count()

        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/vincular-factura",
            headers=auth_headers,
            json={
                "ct_transaction": 306,
                "ajustar_monto": True,
                "nuevo_monto": "1800",  # antes 1000, diferencia 800
                "motivo_ajuste": "factura llegó mayor al pedido",
            },
        )
        assert r.status_code == 200, r.text

        # Movimiento CC SÍ se creó (ajuste compensatorio append-only).
        count_movs_despues = db.query(CCProveedorMovimiento).count()
        assert count_movs_despues == count_movs_antes + 1

        # El evento registrado debe ser el clásico.
        eventos = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_PEDIDO,
                CompraEvento.entidad_id == pedido.id,
                CompraEvento.tipo == "monto_ajustado_por_factura",
            )
            .all()
        )
        assert len(eventos) == 1
        assert eventos[0].payload["tenia_imputaciones_vivas"] is True


# ══════════════════════════════════════════════════════════════════════════
# POST /pedidos/{id}/desvincular-factura
# ══════════════════════════════════════════════════════════════════════════


class TestDesvincularFacturaEndpoint:
    def test_desvincula_ok(self, client, auth_headers, db, pedido, con_todos_los_permisos):
        pedido.ct_transaction_id = 999
        db.flush()

        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/desvincular-factura",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["ct_transaction_id"] is None

    def test_sin_factura_400(self, client, auth_headers, pedido, con_todos_los_permisos):
        r = client.post(
            f"{BASE}/pedidos/{pedido.id}/desvincular-factura",
            headers=auth_headers,
        )
        assert r.status_code == 400
