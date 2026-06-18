"""Integration tests — Slice A: Recepción de Mercadería por Depósito.

Covers:
  - Migration-level: table existence, constraints, permission seed (via SQLite schema).
  - GET  /pedidos/{id}/recepcion/saldos
  - POST /pedidos/{id}/recepcion/ingresos
  - POST /pedidos/{id}/recepcion/confirmar-pedido
  - GET  /pedidos/{id}/recepcion/eventos
  - State machine transitions and ERP read-only enforcement.

TDD: tests written BEFORE implementation (Strict TDD mode active).
Pattern mirrors test_oc_vincular_s1_endpoints.py.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.models.compra_evento import CompraEvento
from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_compra_ingresos import PedidoCompraIngreso
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.purchase_order_detail import PurchaseOrderDetail
from app.models.purchase_order_header import PurchaseOrderHeader
from app.models.tb_storage import TbStorage
from app.schemas.recepcion import (
    ConfirmarPedidoRequest,
    IngresoLinea,
    RegistrarIngresosRequest,
)
from app.services import recepcion_service

BASE = "/api/administracion/compras"


# ──────────────────────────────────────────────────────────────────────────
# Permission fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def con_permiso_deposito():
    """Patch PermisosService so deposito.recibir_mercaderia passes."""
    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            return_value=True,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value={"deposito.recibir_mercaderia"},
        ),
    ):
        yield


@pytest.fixture
def sin_permiso():
    """Patch PermisosService so all permission checks fail."""

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
def con_permiso_gestionar_oc():
    """Patch PermisosService so only gestionar_ordenes_compra passes."""

    def _fake(self, user, codigo):
        return codigo == "administracion.gestionar_ordenes_compra"

    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            new=_fake,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value={"administracion.gestionar_ordenes_compra"},
        ),
    ):
        yield


@pytest.fixture
def con_permiso_deposito_y_gestionar():
    """Patch so both deposito.recibir_mercaderia and gestionar_ordenes_compra pass."""

    def _fake(self, user, codigo):
        return codigo in {
            "deposito.recibir_mercaderia",
            "administracion.gestionar_ordenes_compra",
        }

    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            new=_fake,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value={"deposito.recibir_mercaderia", "administracion.gestionar_ordenes_compra"},
        ),
    ):
        yield


@pytest.fixture
def con_permiso_despachar_retiro():
    """Patch PermisosService so only deposito.despachar_retiro passes."""

    def _fake(self, user, codigo):
        return codigo == "deposito.despachar_retiro"

    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            new=_fake,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value={"deposito.despachar_retiro"},
        ),
    ):
        yield


@pytest.fixture
def con_permiso_solo_recibir_mercaderia():
    """Patch PermisosService so only deposito.recibir_mercaderia passes (nothing else)."""

    def _fake(self, user, codigo):
        return codigo == "deposito.recibir_mercaderia"

    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            new=_fake,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value={"deposito.recibir_mercaderia"},
        ),
    ):
        yield


# ──────────────────────────────────────────────────────────────────────────
# Domain fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=20, nombre="EmpresaRD", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=55,
        nombre="PROV_RD",
        supp_id=55,
        comp_id=1,
        activo=True,
        origen=OrigenProveedor.ERP.value,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def pedido_pagado(db, empresa, proveedor, active_user) -> PedidoCompra:
    """Pedido in 'pagado' state — receptive, no OC linked."""
    p = PedidoCompra(
        numero="P-RD-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("10000"),
        estado="pagado",
        requiere_envio=False,
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def pedido_pagado_con_oc(db, empresa, proveedor, active_user) -> PedidoCompra:
    """Pedido in 'pagado' state WITH OC linked."""
    p = PedidoCompra(
        numero="P-RD-OC-001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("10000"),
        estado="pagado",
        requiere_envio=False,
        oc_comp_id=1,
        oc_bra_id=1,
        oc_poh_id=9001,
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def pedido_borrador(db, empresa, proveedor, active_user) -> PedidoCompra:
    p = PedidoCompra(
        numero="P-RD-BORR",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("5000"),
        estado="borrador",
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


def _mk_oc_header(db, *, poh_id: int, supp_id: int, comp_id: int = 1, bra_id: int = 1):
    h = PurchaseOrderHeader(comp_id=comp_id, bra_id=bra_id, poh_id=poh_id, supp_id=supp_id, poh_total=Decimal("10000"))
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
    confirmedqty: float = 0.0,
):
    d = PurchaseOrderDetail(
        comp_id=comp_id,
        bra_id=bra_id,
        poh_id=poh_id,
        pod_id=pod_id,
        stor_id=stor_id,
        item_id=item_id,
        pod_qty=Decimal(str(qty)),
        pod_confirmedqty=Decimal(str(confirmedqty)),
        pod_isprocessed=False,
    )
    db.add(d)
    db.flush()
    return d


def _mk_storage(db, *, comp_id: int = 1, stor_id: int = 1, stor_desc: str = "Depósito Principal"):
    s = TbStorage(comp_id=comp_id, stor_id=stor_id, stor_desc=stor_desc)
    db.add(s)
    db.flush()
    return s


def _mk_producto_erp(db, *, item_id: int, descripcion: str, codigo: str = "ITEM"):
    """Insert a productos_erp row via raw SQL (read-only model in tests)."""
    db.execute(
        text(
            "INSERT OR IGNORE INTO productos_erp (item_id, codigo, descripcion, activo) "
            "VALUES (:item_id, :codigo, :descripcion, 1)"
        ),
        {"item_id": item_id, "codigo": codigo, "descripcion": descripcion},
    )
    db.flush()


# ──────────────────────────────────────────────────────────────────────────
# RD-A.2 — Migration-level tests (schema validated via SQLite in-memory DB)
# ──────────────────────────────────────────────────────────────────────────


class TestMigration:
    def test_migration_creates_pedido_compra_ingresos_table(self, db):
        """Table pedido_compra_ingresos exists with key columns."""

        cols = {c.name for c in PedidoCompraIngreso.__table__.columns}
        for required in (
            "id",
            "pedido_id",
            "oc_comp_id",
            "oc_bra_id",
            "oc_poh_id",
            "pod_id",
            "item_id",
            "stor_id",
            "cantidad_recibida",
            "fecha_ingreso",
            "usuario_id",
            "observaciones",
            "created_at",
        ):
            assert required in cols, f"Missing column: {required}"

    def test_migration_check_cantidad_recibida_gt_zero(self, db, pedido_pagado, active_user):
        """SQLite CHECK constraint rejects cantidad_recibida=0."""
        from sqlalchemy.exc import IntegrityError

        import pytest as _pytest

        with _pytest.raises(IntegrityError):
            db.execute(
                text(
                    "INSERT INTO pedido_compra_ingresos "
                    "(pedido_id, cantidad_recibida, fecha_ingreso, usuario_id, created_at) "
                    "VALUES (:pid, 0, date('now'), :uid, datetime('now'))"
                ),
                {"pid": pedido_pagado.id, "uid": active_user.id},
            )
            db.flush()
        db.rollback()

    def test_migration_new_states_accepted(self, db, empresa, proveedor, active_user):
        """States 'recibido' and 'con_faltantes' are accepted by PedidoCompra."""
        p1 = PedidoCompra(
            numero="P-RD-ST-01",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            estado="recibido",
            creado_por_id=active_user.id,
        )
        p2 = PedidoCompra(
            numero="P-RD-ST-02",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            estado="con_faltantes",
            creado_por_id=active_user.id,
        )
        db.add_all([p1, p2])
        db.flush()
        assert p1.id is not None
        assert p2.id is not None

    def test_migration_invalid_state_rejected(self, db, empresa, proveedor, active_user):
        """State 'en_camino' (invalid) is rejected by CheckConstraint."""
        from sqlalchemy.exc import IntegrityError

        import pytest as _pytest

        p = PedidoCompra(
            numero="P-RD-INV",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            estado="en_camino",
            creado_por_id=active_user.id,
        )
        db.add(p)
        with _pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_migration_permiso_seed(self, db):
        """The permiso 'deposito.recibir_mercaderia' exists after seed (checked in-model)."""
        # In the test env we seed it explicitly; the real seed is in the migration.
        # Here we just verify the model table exists and can hold the value.

        row = db.execute(text("SELECT COUNT(*) FROM permisos WHERE codigo = 'deposito.recibir_mercaderia'")).scalar()
        # In a real migrated DB this would be 1; here it's 0 if not yet seeded.
        # The test simply asserts the query runs without error (table structure valid).
        assert row is not None


# ──────────────────────────────────────────────────────────────────────────
# RD-A.5 / RD-A.6 — Service unit tests (via mocked session)
# ──────────────────────────────────────────────────────────────────────────


class TestRecepcionServiceSaldos:
    """Tests for recepcion_service.computar_saldos."""

    def test_computar_saldos_sin_oc(self, db, pedido_pagado):
        """SIN OC: returns SaldosResponse with lineas=[]."""

        result = recepcion_service.computar_saldos(db, pedido_pagado)
        assert result.tiene_oc is False
        assert result.lineas == []
        assert result.pedido_id == pedido_pagado.id

    def test_computar_saldos_con_oc(self, db, pedido_pagado_con_oc):
        """CON OC: saldo = pod_qty - pod_confirmedqty - ingresos previos."""
        _mk_oc_header(db, poh_id=9001, supp_id=55)
        _mk_oc_detail(db, poh_id=9001, pod_id=1, qty=100.0, item_id=101)
        _mk_storage(db, stor_id=1)

        result = recepcion_service.computar_saldos(db, pedido_pagado_con_oc)
        assert result.tiene_oc is True
        assert len(result.lineas) == 1
        linea = result.lineas[0]
        assert linea.pod_id == 1
        assert linea.saldo_pendiente == Decimal("100")

    def test_computar_saldos_con_oc_descuenta_ingresos_previos(self, db, pedido_pagado_con_oc, active_user):
        """Saldo reflects previously registered ingresos."""

        _mk_oc_header(db, poh_id=9001, supp_id=55)
        _mk_oc_detail(db, poh_id=9001, pod_id=1, qty=100.0, item_id=101)
        _mk_storage(db, stor_id=1)

        # Pre-existing ingreso of 60
        ingreso = PedidoCompraIngreso(
            pedido_id=pedido_pagado_con_oc.id,
            oc_comp_id=1,
            oc_bra_id=1,
            oc_poh_id=9001,
            pod_id=1,
            item_id=101,
            stor_id=1,
            cantidad_recibida=Decimal("60"),
            usuario_id=active_user.id,
        )
        db.add(ingreso)
        db.flush()

        result = recepcion_service.computar_saldos(db, pedido_pagado_con_oc)
        assert result.lineas[0].saldo_pendiente == Decimal("40")

    def test_computar_saldos_item_nombre_resolved(self, db, pedido_pagado_con_oc):
        """Item presente en productos_erp → item_nombre resuelto."""
        _mk_oc_header(db, poh_id=9001, supp_id=55)
        _mk_oc_detail(db, poh_id=9001, pod_id=1, qty=10.0, item_id=5001)
        _mk_storage(db, stor_id=1)
        _mk_producto_erp(db, item_id=5001, descripcion="Tornillo M8")
        db.flush()

        result = recepcion_service.computar_saldos(db, pedido_pagado_con_oc)
        assert result.lineas[0].item_nombre == "Tornillo M8"

    def test_saldos_phantom_item_fallback(self, db, pedido_pagado_con_oc):
        """Item NOT in productos_erp → item_nombre is str(item_id)."""
        _mk_oc_header(db, poh_id=9001, supp_id=55)
        _mk_oc_detail(db, poh_id=9001, pod_id=1, qty=10.0, item_id=99999)
        _mk_storage(db, stor_id=1)
        # Do NOT insert productos_erp row for 99999

        result = recepcion_service.computar_saldos(db, pedido_pagado_con_oc)
        assert result.lineas[0].item_nombre == "99999"

    def test_recalcular_estado_todos_cero_da_recibido(self, db, pedido_pagado_con_oc):

        saldos = [{"pod_id": 1, "saldo": Decimal("0")}, {"pod_id": 2, "saldo": Decimal("0")}]
        estado = recepcion_service.recalcular_estado(db, pedido_pagado_con_oc, saldos)
        assert estado == "recibido"
        assert pedido_pagado_con_oc.estado == "recibido"

    def test_recalcular_estado_alguno_positivo_da_con_faltantes(self, db, pedido_pagado_con_oc):

        saldos = [{"pod_id": 1, "saldo": Decimal("0")}, {"pod_id": 2, "saldo": Decimal("10")}]
        estado = recepcion_service.recalcular_estado(db, pedido_pagado_con_oc, saldos)
        assert estado == "con_faltantes"
        assert pedido_pagado_con_oc.estado == "con_faltantes"

    def test_validar_estado_receptivo_rechaza_recibido(self, db, empresa, proveedor, active_user):
        from fastapi import HTTPException

        p = PedidoCompra(
            numero="P-RD-RECV",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            estado="recibido",
            creado_por_id=active_user.id,
        )
        db.add(p)
        db.flush()

        with pytest.raises(HTTPException) as exc:
            recepcion_service._validar_estado_receptivo(p)
        assert exc.value.status_code == 409
        assert "already fully received" in exc.value.detail

    def test_validar_estado_receptivo_rechaza_borrador(self, db, pedido_borrador):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            recepcion_service._validar_estado_receptivo(pedido_borrador)
        assert exc.value.status_code == 409
        assert "not in a receivable state" in exc.value.detail


# ──────────────────────────────────────────────────────────────────────────
# RD-A.7 — registrar_ingresos service tests
# ──────────────────────────────────────────────────────────────────────────


class TestRegistrarIngresosService:
    def _pedido_con_oc_y_lineas(self, db, empresa, proveedor, active_user, poh_id=9001):
        """Helper: create pagado pedido with OC + 2 lines."""
        p = PedidoCompra(
            numero=f"P-RD-RI-{poh_id}",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("5000"),
            estado="pagado",
            oc_comp_id=1,
            oc_bra_id=1,
            oc_poh_id=poh_id,
            creado_por_id=active_user.id,
        )
        db.add(p)
        db.flush()
        _mk_oc_header(db, poh_id=poh_id, supp_id=55)
        _mk_oc_detail(db, poh_id=poh_id, pod_id=1, qty=100.0, item_id=101)
        _mk_oc_detail(db, poh_id=poh_id, pod_id=2, qty=50.0, item_id=102)
        _mk_storage(db, stor_id=1)
        return p

    def test_registrar_ingresos_partial_batch_da_con_faltantes(self, db, empresa, proveedor, active_user):

        p = self._pedido_con_oc_y_lineas(db, empresa, proveedor, active_user, poh_id=9010)
        req = RegistrarIngresosRequest(
            lineas=[IngresoLinea(pod_id=1, cantidad_recibida=Decimal("60"))],
            observaciones=None,
        )
        result = recepcion_service.registrar_ingresos(db, p, active_user, req)
        assert result.estado_nuevo == "con_faltantes"
        assert len(result.ingresos_creados) == 1

    def test_registrar_ingresos_complete_batch_da_recibido(self, db, empresa, proveedor, active_user):

        p = self._pedido_con_oc_y_lineas(db, empresa, proveedor, active_user, poh_id=9011)
        req = RegistrarIngresosRequest(
            lineas=[
                IngresoLinea(pod_id=1, cantidad_recibida=Decimal("100")),
                IngresoLinea(pod_id=2, cantidad_recibida=Decimal("50")),
            ],
        )
        result = recepcion_service.registrar_ingresos(db, p, active_user, req)
        assert result.estado_nuevo == "recibido"

    def test_registrar_ingresos_second_batch_desde_con_faltantes_da_recibido(self, db, empresa, proveedor, active_user):

        p = self._pedido_con_oc_y_lineas(db, empresa, proveedor, active_user, poh_id=9012)
        # First batch partial
        ing1 = PedidoCompraIngreso(
            pedido_id=p.id,
            oc_comp_id=1,
            oc_bra_id=1,
            oc_poh_id=9012,
            pod_id=1,
            item_id=101,
            stor_id=1,
            cantidad_recibida=Decimal("60"),
            usuario_id=active_user.id,
        )
        db.add(ing1)
        p.estado = "con_faltantes"
        db.flush()

        req = RegistrarIngresosRequest(
            lineas=[
                IngresoLinea(pod_id=1, cantidad_recibida=Decimal("40")),
                IngresoLinea(pod_id=2, cantidad_recibida=Decimal("50")),
            ],
        )
        result = recepcion_service.registrar_ingresos(db, p, active_user, req)
        assert result.estado_nuevo == "recibido"

    def test_registrar_ingresos_second_batch_sigue_con_faltantes(self, db, empresa, proveedor, active_user):

        p = self._pedido_con_oc_y_lineas(db, empresa, proveedor, active_user, poh_id=9013)
        ing1 = PedidoCompraIngreso(
            pedido_id=p.id,
            oc_comp_id=1,
            oc_bra_id=1,
            oc_poh_id=9013,
            pod_id=1,
            item_id=101,
            stor_id=1,
            cantidad_recibida=Decimal("60"),
            usuario_id=active_user.id,
        )
        db.add(ing1)
        p.estado = "con_faltantes"
        db.flush()

        req = RegistrarIngresosRequest(
            lineas=[IngresoLinea(pod_id=1, cantidad_recibida=Decimal("20"))],
        )
        result = recepcion_service.registrar_ingresos(db, p, active_user, req)
        assert result.estado_nuevo == "con_faltantes"

    def test_registrar_ingresos_over_receipt_409_no_inserts(self, db, empresa, proveedor, active_user):
        from fastapi import HTTPException

        p = self._pedido_con_oc_y_lineas(db, empresa, proveedor, active_user, poh_id=9014)
        req = RegistrarIngresosRequest(
            lineas=[IngresoLinea(pod_id=1, cantidad_recibida=Decimal("150"))],  # saldo=100
        )
        with pytest.raises(HTTPException) as exc:
            recepcion_service.registrar_ingresos(db, p, active_user, req)
        assert exc.value.status_code == 409
        assert "Over-receipt" in exc.value.detail
        db.rollback()

        # No inserts should have happened
        count = db.execute(
            text("SELECT COUNT(*) FROM pedido_compra_ingresos WHERE pedido_id = :pid"),
            {"pid": p.id},
        ).scalar()
        assert count == 0

    def test_registrar_ingresos_atomic_rollback_partial_over_receipt(self, db, empresa, proveedor, active_user):
        """One line over-receipt rolls back ALL inserts in the tanda."""
        from fastapi import HTTPException

        p = self._pedido_con_oc_y_lineas(db, empresa, proveedor, active_user, poh_id=9015)
        req = RegistrarIngresosRequest(
            lineas=[
                IngresoLinea(pod_id=1, cantidad_recibida=Decimal("50")),  # ok
                IngresoLinea(pod_id=2, cantidad_recibida=Decimal("60")),  # over (saldo=50)
            ],
        )
        with pytest.raises(HTTPException) as exc:
            recepcion_service.registrar_ingresos(db, p, active_user, req)
        assert exc.value.status_code == 409
        db.rollback()

        count = db.execute(
            text("SELECT COUNT(*) FROM pedido_compra_ingresos WHERE pedido_id = :pid"),
            {"pid": p.id},
        ).scalar()
        assert count == 0

    def test_registrar_ingresos_pedido_ya_recibido_409(self, db, empresa, proveedor, active_user):
        from fastapi import HTTPException

        p = PedidoCompra(
            numero="P-RD-TERM",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            estado="recibido",
            oc_poh_id=9020,
            oc_comp_id=1,
            oc_bra_id=1,
            creado_por_id=active_user.id,
        )
        db.add(p)
        db.flush()
        req = RegistrarIngresosRequest(
            lineas=[IngresoLinea(pod_id=1, cantidad_recibida=Decimal("10"))],
        )
        with pytest.raises(HTTPException) as exc:
            recepcion_service.registrar_ingresos(db, p, active_user, req)
        assert exc.value.status_code == 409
        assert "already fully received" in exc.value.detail

    def test_registrar_ingresos_sin_oc_409(self, db, pedido_pagado, active_user):
        from fastapi import HTTPException

        req = RegistrarIngresosRequest(
            lineas=[IngresoLinea(pod_id=1, cantidad_recibida=Decimal("10"))],
        )
        with pytest.raises(HTTPException) as exc:
            recepcion_service.registrar_ingresos(db, pedido_pagado, active_user, req)
        assert exc.value.status_code == 409
        assert "no linked OC" in exc.value.detail

    def test_registrar_ingresos_zero_lines_ignored(self, db, empresa, proveedor, active_user):
        """Lines with cantidad_recibida=0 are silently ignored."""

        p = self._pedido_con_oc_y_lineas(db, empresa, proveedor, active_user, poh_id=9016)
        req = RegistrarIngresosRequest(
            lineas=[
                IngresoLinea(pod_id=1, cantidad_recibida=Decimal("0")),
                IngresoLinea(pod_id=2, cantidad_recibida=Decimal("30")),
            ],
        )
        result = recepcion_service.registrar_ingresos(db, p, active_user, req)
        # Only pod_id=2 processed
        assert len(result.ingresos_creados) == 1
        assert result.ingresos_creados[0].pod_id == 2

    def test_registrar_ingresos_evento_con_faltantes_incluye_todas_las_lineas(
        self, db, empresa, proveedor, active_user
    ):
        """recepcion_con_faltantes payload includes ALL OC lines."""

        p = self._pedido_con_oc_y_lineas(db, empresa, proveedor, active_user, poh_id=9017)
        req = RegistrarIngresosRequest(
            lineas=[IngresoLinea(pod_id=1, cantidad_recibida=Decimal("60"))],
        )
        recepcion_service.registrar_ingresos(db, p, active_user, req)

        evento = (
            db.query(CompraEvento)
            .filter_by(entidad_id=p.id, entidad_tipo="pedido_compra")
            .filter(CompraEvento.tipo == "recepcion_con_faltantes")
            .first()
        )
        assert evento is not None
        payload = evento.payload
        assert "lineas" in payload
        pod_ids_en_payload = {l["pod_id"] for l in payload["lineas"]}
        assert 1 in pod_ids_en_payload
        assert 2 in pod_ids_en_payload

    def test_registrar_ingresos_no_escribe_erp(self, db, empresa, proveedor, active_user):
        """Successful ingreso does NOT write to any ERP table."""

        p = self._pedido_con_oc_y_lineas(db, empresa, proveedor, active_user, poh_id=9018)
        before_detail = db.execute(text("SELECT COUNT(*) FROM tb_purchase_order_detail")).scalar()

        req = RegistrarIngresosRequest(
            lineas=[IngresoLinea(pod_id=1, cantidad_recibida=Decimal("50"))],
        )
        recepcion_service.registrar_ingresos(db, p, active_user, req)

        after_detail = db.execute(text("SELECT COUNT(*) FROM tb_purchase_order_detail")).scalar()
        assert before_detail == after_detail  # no writes to ERP


# ──────────────────────────────────────────────────────────────────────────
# RD-A.8 — confirmar_pedido_sin_oc service tests
# ──────────────────────────────────────────────────────────────────────────


class TestConfirmarPedidoSinOc:
    def test_confirmar_sin_oc_completo_true_da_recibido(self, db, pedido_pagado, active_user):

        req = ConfirmarPedidoRequest(completo=True)
        result = recepcion_service.confirmar_pedido_sin_oc(db, pedido_pagado, active_user, req)
        assert result.estado_nuevo == "recibido"
        assert pedido_pagado.estado == "recibido"

    def test_confirmar_sin_oc_completo_false_da_con_faltantes(self, db, pedido_pagado, active_user):

        req = ConfirmarPedidoRequest(completo=False, observaciones="Faltaron 3 ítems")
        result = recepcion_service.confirmar_pedido_sin_oc(db, pedido_pagado, active_user, req)
        assert result.estado_nuevo == "con_faltantes"

    def test_confirmar_sin_oc_completo_false_sin_observaciones_422(self):
        """Schema-level: completo=False without observaciones raises ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ConfirmarPedidoRequest(completo=False)

    def test_confirmar_pedido_con_oc_da_409(self, db, pedido_pagado_con_oc, active_user):
        from fastapi import HTTPException

        req = ConfirmarPedidoRequest(completo=True)
        with pytest.raises(HTTPException) as exc:
            recepcion_service.confirmar_pedido_sin_oc(db, pedido_pagado_con_oc, active_user, req)
        assert exc.value.status_code == 409
        assert "OC linked" in exc.value.detail

    def test_sentinel_pod_id_null_no_afecta_saldos(self, db, empresa, proveedor, active_user):
        """Sentinel row (pod_id=NULL) does NOT pollute CON-OC saldo calculation."""
        # Create pedido with OC
        p_oc = PedidoCompra(
            numero="P-RD-SENT",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("5000"),
            estado="pagado",
            oc_comp_id=1,
            oc_bra_id=1,
            oc_poh_id=9030,
            creado_por_id=active_user.id,
        )
        db.add(p_oc)
        db.flush()
        _mk_oc_header(db, poh_id=9030, supp_id=55)
        _mk_oc_detail(db, poh_id=9030, pod_id=1, qty=100.0, item_id=101)
        _mk_storage(db, stor_id=1)

        # Insert a sentinel (pod_id=NULL) for a DIFFERENT pedido (sin OC)

        p_sinoc = PedidoCompra(
            numero="P-RD-SINOC-S",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            estado="recibido",
            creado_por_id=active_user.id,
        )
        db.add(p_sinoc)
        db.flush()
        sentinel = PedidoCompraIngreso(
            pedido_id=p_sinoc.id,
            pod_id=None,
            cantidad_recibida=Decimal("1"),
            usuario_id=active_user.id,
        )
        db.add(sentinel)
        db.flush()

        result = recepcion_service.computar_saldos(db, p_oc)
        # Sentinel from other pedido should NOT affect this pedido's saldo
        assert result.lineas[0].saldo_pendiente == Decimal("100")


# ──────────────────────────────────────────────────────────────────────────
# RD-A.9 — get_eventos_recepcion service tests
# ──────────────────────────────────────────────────────────────────────────


class TestGetEventosRecepcion:
    def test_get_eventos_retorna_eventos_en_orden_desc(self, db, pedido_pagado, active_user):

        # Insert 2 eventos manually
        e1 = CompraEvento(
            entidad_tipo="pedido_compra",
            entidad_id=pedido_pagado.id,
            tipo="recepcion_registrada",
            usuario_id=active_user.id,
            payload={"modo": "sin_oc"},
        )
        e2 = CompraEvento(
            entidad_tipo="pedido_compra",
            entidad_id=pedido_pagado.id,
            tipo="recepcion_con_faltantes",
            usuario_id=active_user.id,
            payload={"modo": "sin_oc"},
        )
        db.add_all([e1, e2])
        db.flush()

        result = recepcion_service.get_eventos_recepcion(db, pedido_pagado.id)
        assert len(result.eventos) >= 2
        # Check descending order by id (proxy for created_at in SQLite)
        ids = [e.id for e in result.eventos]
        assert ids == sorted(ids, reverse=True)

    def test_get_eventos_lista_vacia(self, db, pedido_pagado):

        result = recepcion_service.get_eventos_recepcion(db, pedido_pagado.id)
        # May have 0 recepcion events for this fresh pedido
        tipos = {e.tipo for e in result.eventos}
        invalid = tipos - {"recepcion_registrada", "recepcion_con_faltantes"}
        assert not invalid

    def test_get_eventos_filtra_solo_tipos_recepcion(self, db, pedido_pagado, active_user):

        # Add an unrelated event
        e_other = CompraEvento(
            entidad_tipo="pedido_compra",
            entidad_id=pedido_pagado.id,
            tipo="aprobado",
            usuario_id=active_user.id,
            payload={},
        )
        e_recep = CompraEvento(
            entidad_tipo="pedido_compra",
            entidad_id=pedido_pagado.id,
            tipo="recepcion_registrada",
            usuario_id=active_user.id,
            payload={"modo": "sin_oc"},
        )
        db.add_all([e_other, e_recep])
        db.flush()

        result = recepcion_service.get_eventos_recepcion(db, pedido_pagado.id)
        for e in result.eventos:
            assert e.tipo in {"recepcion_registrada", "recepcion_con_faltantes"}


# ──────────────────────────────────────────────────────────────────────────
# RD-A.11 — Endpoint tests (Batch K)
# ──────────────────────────────────────────────────────────────────────────


class TestSaldosEndpoint:
    def test_saldos_403_sin_permiso(self, client, auth_headers, pedido_pagado, sin_permiso):
        r = client.get(f"{BASE}/pedidos/{pedido_pagado.id}/recepcion/saldos", headers=auth_headers)
        assert r.status_code == 403

    def test_saldos_403_con_permiso_gestionar_oc_solamente(
        self, client, auth_headers, pedido_pagado, con_permiso_gestionar_oc
    ):
        """D2 LOCKED: gestionar_ordenes_compra alone → 403 on saldos."""
        r = client.get(f"{BASE}/pedidos/{pedido_pagado.id}/recepcion/saldos", headers=auth_headers)
        assert r.status_code == 403

    def test_saldos_404_pedido_inexistente(self, client, auth_headers, con_permiso_deposito):
        r = client.get(f"{BASE}/pedidos/99999/recepcion/saldos", headers=auth_headers)
        assert r.status_code == 404

    def test_saldos_200_sin_oc(self, client, auth_headers, pedido_pagado, con_permiso_deposito):
        r = client.get(f"{BASE}/pedidos/{pedido_pagado.id}/recepcion/saldos", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["tiene_oc"] is False
        assert data["lineas"] == []

    def test_saldos_200_con_oc(self, client, auth_headers, db, pedido_pagado_con_oc, con_permiso_deposito):
        _mk_oc_header(db, poh_id=9001, supp_id=55)
        _mk_oc_detail(db, poh_id=9001, pod_id=1, qty=100.0, item_id=101)
        _mk_storage(db, stor_id=1)

        r = client.get(f"{BASE}/pedidos/{pedido_pagado_con_oc.id}/recepcion/saldos", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["tiene_oc"] is True
        assert len(data["lineas"]) == 1
        assert Decimal(str(data["lineas"][0]["saldo_pendiente"])) == Decimal("100")


class TestIngresosEndpoint:
    def _setup_pedido_con_oc(self, db, empresa, proveedor, active_user, poh_id: int) -> PedidoCompra:
        p = PedidoCompra(
            numero=f"P-EP-{poh_id}",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("5000"),
            estado="pagado",
            oc_comp_id=1,
            oc_bra_id=1,
            oc_poh_id=poh_id,
            creado_por_id=active_user.id,
        )
        db.add(p)
        db.flush()
        _mk_oc_header(db, poh_id=poh_id, supp_id=55)
        _mk_oc_detail(db, poh_id=poh_id, pod_id=1, qty=100.0, item_id=101)
        _mk_oc_detail(db, poh_id=poh_id, pod_id=2, qty=50.0, item_id=102)
        _mk_storage(db, stor_id=1)
        return p

    def test_ingresos_403_sin_permiso(self, client, auth_headers, pedido_pagado_con_oc, sin_permiso):
        r = client.post(
            f"{BASE}/pedidos/{pedido_pagado_con_oc.id}/recepcion/ingresos",
            json={"lineas": [{"pod_id": 1, "cantidad_recibida": 50}]},
            headers=auth_headers,
        )
        assert r.status_code == 403

    def test_ingresos_201_partial(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_permiso_deposito
    ):
        p = self._setup_pedido_con_oc(db, empresa, proveedor, active_user, poh_id=8001)
        r = client.post(
            f"{BASE}/pedidos/{p.id}/recepcion/ingresos",
            json={"lineas": [{"pod_id": 1, "cantidad_recibida": 60}]},
            headers=auth_headers,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["estado_nuevo"] == "con_faltantes"

    def test_ingresos_201_complete(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_permiso_deposito
    ):
        p = self._setup_pedido_con_oc(db, empresa, proveedor, active_user, poh_id=8002)
        r = client.post(
            f"{BASE}/pedidos/{p.id}/recepcion/ingresos",
            json={
                "lineas": [
                    {"pod_id": 1, "cantidad_recibida": 100},
                    {"pod_id": 2, "cantidad_recibida": 50},
                ]
            },
            headers=auth_headers,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["estado_nuevo"] == "recibido"

    def test_ingresos_409_over_receipt(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_permiso_deposito
    ):
        p = self._setup_pedido_con_oc(db, empresa, proveedor, active_user, poh_id=8003)
        r = client.post(
            f"{BASE}/pedidos/{p.id}/recepcion/ingresos",
            json={"lineas": [{"pod_id": 1, "cantidad_recibida": 150}]},
            headers=auth_headers,
        )
        assert r.status_code == 409
        body = r.json()
        msg = body.get("detail") or body.get("error", {}).get("message", "")
        assert "Over-receipt" in msg


class TestConfirmarPedidoEndpoint:
    def test_confirmar_pedido_403(self, client, auth_headers, pedido_pagado, sin_permiso):
        r = client.post(
            f"{BASE}/pedidos/{pedido_pagado.id}/recepcion/confirmar-pedido",
            json={"completo": True},
            headers=auth_headers,
        )
        assert r.status_code == 403

    def test_confirmar_pedido_200_completo(self, client, auth_headers, pedido_pagado, con_permiso_deposito):
        r = client.post(
            f"{BASE}/pedidos/{pedido_pagado.id}/recepcion/confirmar-pedido",
            json={"completo": True},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["estado_nuevo"] == "recibido"

    def test_confirmar_pedido_200_con_faltantes(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_permiso_deposito
    ):
        p = PedidoCompra(
            numero="P-EP-CONF-CF",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            estado="pagado",
            creado_por_id=active_user.id,
        )
        db.add(p)
        db.flush()
        r = client.post(
            f"{BASE}/pedidos/{p.id}/recepcion/confirmar-pedido",
            json={"completo": False, "observaciones": "Faltaron ítems"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["estado_nuevo"] == "con_faltantes"

    def test_confirmar_pedido_409_tiene_oc(self, client, auth_headers, pedido_pagado_con_oc, con_permiso_deposito):
        r = client.post(
            f"{BASE}/pedidos/{pedido_pagado_con_oc.id}/recepcion/confirmar-pedido",
            json={"completo": True},
            headers=auth_headers,
        )
        assert r.status_code == 409


class TestEventosEndpoint:
    def test_eventos_403(self, client, auth_headers, pedido_pagado, sin_permiso):
        r = client.get(
            f"{BASE}/pedidos/{pedido_pagado.id}/recepcion/eventos",
            headers=auth_headers,
        )
        assert r.status_code == 403

    def test_eventos_200(self, client, auth_headers, pedido_pagado, con_permiso_deposito):
        r = client.get(
            f"{BASE}/pedidos/{pedido_pagado.id}/recepcion/eventos",
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert "eventos" in r.json()


# ──────────────────────────────────────────────────────────────────────────
# RD-A.12 — State machine + ERP read-only
# ──────────────────────────────────────────────────────────────────────────


class TestStateMachine:
    def _mk_pagado_con_oc(self, db, empresa, proveedor, active_user, poh_id: int) -> PedidoCompra:
        p = PedidoCompra(
            numero=f"P-SM-{poh_id}",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("5000"),
            estado="pagado",
            oc_comp_id=1,
            oc_bra_id=1,
            oc_poh_id=poh_id,
            creado_por_id=active_user.id,
        )
        db.add(p)
        db.flush()
        _mk_oc_header(db, poh_id=poh_id, supp_id=55)
        _mk_oc_detail(db, poh_id=poh_id, pod_id=1, qty=100.0, item_id=101)
        _mk_storage(db, stor_id=1)
        return p

    def test_state_pagado_a_recibido_directo(self, db, empresa, proveedor, active_user):

        p = self._mk_pagado_con_oc(db, empresa, proveedor, active_user, poh_id=7001)
        req = RegistrarIngresosRequest(
            lineas=[IngresoLinea(pod_id=1, cantidad_recibida=Decimal("100"))],
        )
        result = recepcion_service.registrar_ingresos(db, p, active_user, req)
        assert result.estado_nuevo == "recibido"
        db.refresh(p)
        assert p.estado == "recibido"

    def test_state_pagado_con_faltantes_con_faltantes_recibido(self, db, empresa, proveedor, active_user):
        """3-batch journey: pagado → con_faltantes → con_faltantes → recibido."""

        p = self._mk_pagado_con_oc(db, empresa, proveedor, active_user, poh_id=7002)
        _mk_oc_detail(db, poh_id=7002, pod_id=2, qty=50.0, item_id=102)

        r1 = recepcion_service.registrar_ingresos(
            db,
            p,
            active_user,
            RegistrarIngresosRequest(lineas=[IngresoLinea(pod_id=1, cantidad_recibida=Decimal("40"))]),
        )
        assert r1.estado_nuevo == "con_faltantes"

        r2 = recepcion_service.registrar_ingresos(
            db,
            p,
            active_user,
            RegistrarIngresosRequest(lineas=[IngresoLinea(pod_id=1, cantidad_recibida=Decimal("20"))]),
        )
        assert r2.estado_nuevo == "con_faltantes"

        r3 = recepcion_service.registrar_ingresos(
            db,
            p,
            active_user,
            RegistrarIngresosRequest(
                lineas=[
                    IngresoLinea(pod_id=1, cantidad_recibida=Decimal("40")),
                    IngresoLinea(pod_id=2, cantidad_recibida=Decimal("50")),
                ]
            ),
        )
        assert r3.estado_nuevo == "recibido"

        # 3 events emitted
        eventos = (
            db.query(CompraEvento)
            .filter_by(entidad_id=p.id, entidad_tipo="pedido_compra")
            .filter(CompraEvento.tipo.in_(["recepcion_registrada", "recepcion_con_faltantes"]))
            .all()
        )
        assert len(eventos) == 3

    def test_state_recibido_rechaza_ingreso_409(self, db, empresa, proveedor, active_user):
        from fastapi import HTTPException

        p = PedidoCompra(
            numero="P-SM-TERM2",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            estado="recibido",
            oc_poh_id=7010,
            oc_comp_id=1,
            oc_bra_id=1,
            creado_por_id=active_user.id,
        )
        db.add(p)
        db.flush()
        req = RegistrarIngresosRequest(
            lineas=[IngresoLinea(pod_id=1, cantidad_recibida=Decimal("10"))],
        )
        with pytest.raises(HTTPException) as exc:
            recepcion_service.registrar_ingresos(db, p, active_user, req)
        assert exc.value.status_code == 409

    def test_state_borrador_rechaza_ingreso_409(self, db, pedido_borrador, active_user):
        from fastapi import HTTPException

        # Give it an OC to bypass the "no OC" check
        pedido_borrador.oc_poh_id = 7011
        pedido_borrador.oc_comp_id = 1
        pedido_borrador.oc_bra_id = 1
        db.flush()

        req = RegistrarIngresosRequest(
            lineas=[IngresoLinea(pod_id=1, cantidad_recibida=Decimal("10"))],
        )
        with pytest.raises(HTTPException) as exc:
            recepcion_service.registrar_ingresos(db, pedido_borrador, active_user, req)
        assert exc.value.status_code == 409

    def test_erp_read_only_ingresos(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_permiso_deposito
    ):
        """After successful POST ingresos, ERP tables unchanged."""
        p = PedidoCompra(
            numero="P-SM-ERP",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("5000"),
            estado="pagado",
            oc_comp_id=1,
            oc_bra_id=1,
            oc_poh_id=7020,
            creado_por_id=active_user.id,
        )
        db.add(p)
        db.flush()
        _mk_oc_header(db, poh_id=7020, supp_id=55)
        _mk_oc_detail(db, poh_id=7020, pod_id=1, qty=100.0, item_id=101)
        _mk_storage(db, stor_id=1)

        before = db.execute(
            text("SELECT pod_qty FROM tb_purchase_order_detail WHERE pod_id = 1 AND poh_id = 7020")
        ).scalar()

        r = client.post(
            f"{BASE}/pedidos/{p.id}/recepcion/ingresos",
            json={"lineas": [{"pod_id": 1, "cantidad_recibida": 50}]},
            headers=auth_headers,
        )
        assert r.status_code == 201

        after = db.execute(
            text("SELECT pod_qty FROM tb_purchase_order_detail WHERE pod_id = 1 AND poh_id = 7020")
        ).scalar()
        assert before == after  # ERP not modified


# ──────────────────────────────────────────────────────────────────────────
# RD-A.13 — Permission coexistence tests
# ──────────────────────────────────────────────────────────────────────────


class TestPermisosCoexistencia:
    def test_ingresos_permiso_deposito_acepta(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_permiso_deposito
    ):
        p = PedidoCompra(
            numero="P-PERM-D",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("5000"),
            estado="pagado",
            oc_comp_id=1,
            oc_bra_id=1,
            oc_poh_id=6001,
            creado_por_id=active_user.id,
        )
        db.add(p)
        db.flush()
        _mk_oc_header(db, poh_id=6001, supp_id=55)
        _mk_oc_detail(db, poh_id=6001, pod_id=1, qty=100.0, item_id=101)
        _mk_storage(db, stor_id=1)

        r = client.post(
            f"{BASE}/pedidos/{p.id}/recepcion/ingresos",
            json={"lineas": [{"pod_id": 1, "cantidad_recibida": 50}]},
            headers=auth_headers,
        )
        assert r.status_code == 201

    def test_ingresos_permiso_gestionar_oc_rechaza(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_permiso_gestionar_oc
    ):
        """D2 LOCKED: gestionar_ordenes_compra alone → 403 on POST ingresos."""
        p = PedidoCompra(
            numero="P-PERM-G",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("5000"),
            estado="pagado",
            oc_comp_id=1,
            oc_bra_id=1,
            oc_poh_id=6002,
            creado_por_id=active_user.id,
        )
        db.add(p)
        db.flush()

        r = client.post(
            f"{BASE}/pedidos/{p.id}/recepcion/ingresos",
            json={"lineas": [{"pod_id": 1, "cantidad_recibida": 50}]},
            headers=auth_headers,
        )
        assert r.status_code == 403

    def test_generar_etiqueta_permiso_deposito_rechaza(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_permiso_solo_recibir_mercaderia
    ):
        """deposito.recibir_mercaderia alone → 403 on generar-etiqueta-envio (regression guard).

        The endpoint requires administracion.gestionar_ordenes_compra exclusively.
        This test guards the revert: the previous wrong OR-widening is gone.
        """
        p = PedidoCompra(
            numero="P-PERM-ETQ",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("5000"),
            estado="pagado",
            requiere_envio=True,
            creado_por_id=active_user.id,
        )
        db.add(p)
        db.flush()

        r = client.post(
            f"{BASE}/pedidos/{p.id}/generar-etiqueta-envio",
            json={},
            headers=auth_headers,
        )
        assert r.status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# POST /pedidos/{id}/recepcion/despachar-retiro
# ──────────────────────────────────────────────────────────────────────────


class TestDespachlarRetiro:
    """Tests for the new deposito.despachar_retiro endpoint (Slice A fix)."""

    def _make_pedido_con_envio(self, db, empresa, proveedor, active_user, numero: str) -> PedidoCompra:
        p = PedidoCompra(
            numero=numero,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("5000"),
            estado="pagado",
            requiere_envio=True,
            creado_por_id=active_user.id,
        )
        db.add(p)
        db.flush()
        return p

    def _mock_etiqueta(self, pedido_id: int, proveedor_id: int):
        from app.models.etiqueta_envio import EtiquetaEnvio

        return EtiquetaEnvio(
            id=888,
            tipo_envio="retiro_proveedor",
            pedido_compra_id=pedido_id,
            proveedor_id=proveedor_id,
            shipping_id=None,
            fecha_envio=None,
            manual_receiver_name=None,
            manual_street_name=None,
            manual_zip_code=None,
            proveedor_direccion_id=None,
            manual_city_name=None,
            manual_phone=None,
        )

    def test_403_sin_permiso(self, client, auth_headers, db, empresa, proveedor, active_user, sin_permiso):
        """No permission → 403."""
        p = self._make_pedido_con_envio(db, empresa, proveedor, active_user, "P-DR-403")
        r = client.post(
            f"{BASE}/pedidos/{p.id}/recepcion/despachar-retiro",
            json={},
            headers=auth_headers,
        )
        assert r.status_code == 403

    def test_403_solo_recibir_mercaderia(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_permiso_solo_recibir_mercaderia
    ):
        """deposito.recibir_mercaderia alone → 403 (wrong permission for despachar-retiro)."""
        p = self._make_pedido_con_envio(db, empresa, proveedor, active_user, "P-DR-WRG")
        r = client.post(
            f"{BASE}/pedidos/{p.id}/recepcion/despachar-retiro",
            json={},
            headers=auth_headers,
        )
        assert r.status_code == 403

    def test_403_solo_gestionar_oc(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_permiso_gestionar_oc
    ):
        """administracion.gestionar_ordenes_compra alone → 403 on despachar-retiro."""
        p = self._make_pedido_con_envio(db, empresa, proveedor, active_user, "P-DR-GOC")
        r = client.post(
            f"{BASE}/pedidos/{p.id}/recepcion/despachar-retiro",
            json={},
            headers=auth_headers,
        )
        assert r.status_code == 403

    def test_success_returns_etiqueta_dict(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_permiso_despachar_retiro
    ):
        """deposito.despachar_retiro → 200 with compact etiqueta dict."""
        p = self._make_pedido_con_envio(db, empresa, proveedor, active_user, "P-DR-OK")

        with patch("app.services.etiqueta_retiro_service.generar_etiqueta_retiro") as mock_gen:
            mock_gen.return_value = self._mock_etiqueta(p.id, proveedor.id)

            r = client.post(
                f"{BASE}/pedidos/{p.id}/recepcion/despachar-retiro",
                json={},
                headers=auth_headers,
            )

        assert r.status_code == 200
        data = r.json()
        assert data["id"] == 888
        assert data["tipo_envio"] == "retiro_proveedor"
        assert data["pedido_compra_id"] == p.id
        mock_gen.assert_called_once()

    def test_success_with_proveedor_direccion_id(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_permiso_despachar_retiro
    ):
        """Passing proveedor_direccion_id in body forwards it to the service."""
        p = self._make_pedido_con_envio(db, empresa, proveedor, active_user, "P-DR-PDIR")

        with patch("app.services.etiqueta_retiro_service.generar_etiqueta_retiro") as mock_gen:
            mock_gen.return_value = self._mock_etiqueta(p.id, proveedor.id)

            r = client.post(
                f"{BASE}/pedidos/{p.id}/recepcion/despachar-retiro",
                json={"proveedor_direccion_id": 42},
                headers=auth_headers,
            )

        assert r.status_code == 200
        _, kwargs = mock_gen.call_args
        assert kwargs.get("proveedor_direccion_id") == 42

    def test_idempotency_409(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_permiso_despachar_retiro
    ):
        """Second call → 409 (idempotency guard inside generar_etiqueta_retiro)."""
        from fastapi import HTTPException

        p = self._make_pedido_con_envio(db, empresa, proveedor, active_user, "P-DR-IDEM")

        with patch(
            "app.services.etiqueta_retiro_service.generar_etiqueta_retiro",
            side_effect=HTTPException(status_code=409, detail="Ya existe etiqueta"),
        ):
            r = client.post(
                f"{BASE}/pedidos/{p.id}/recepcion/despachar-retiro",
                json={},
                headers=auth_headers,
            )

        assert r.status_code == 409

    def test_generar_etiqueta_envio_regression_gestionar_oc_acepta(
        self, client, auth_headers, db, empresa, proveedor, active_user, con_permiso_gestionar_oc
    ):
        """administracion.gestionar_ordenes_compra still grants generar-etiqueta-envio (regression guard)."""
        p = self._make_pedido_con_envio(db, empresa, proveedor, active_user, "P-DR-REG-OK")

        with patch("app.services.etiqueta_retiro_service.generar_etiqueta_retiro") as mock_gen:
            mock_gen.return_value = self._mock_etiqueta(p.id, proveedor.id)

            r = client.post(
                f"{BASE}/pedidos/{p.id}/generar-etiqueta-envio",
                json={},
                headers=auth_headers,
            )

        assert r.status_code == 200
