"""Unit tests de las funciones de Batch I en `pedidos_service`.

Cubre:
  - vincular_factura: happy, pedido ya vinculado 409, ct no vigente 400,
    proveedor sin supp_id 400.
  - desvincular_factura: happy, sin factura 400.
  - ajustar_monto_con_factura: happy con aumento, happy con reducción,
    diferencia 0 (no emite CC), motivo vacío 400, ct de otra factura 409,
    valida movimiento en cc_proveedor_movimientos (tipo='ajuste', signo
    correcto, origen_tipo='ajuste_pedido').
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

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


def _seed_imputacion_viva(db, *, pedido_id: int, proveedor_id: int, user_id: int, monto: Decimal = Decimal("1")):
    """Seedea una imputación viva al pedido para forzar el comportamiento
    de ajuste compensatorio append-only (sub-batch 4).

    Sin esta imputación, `ajustar_monto_con_factura` hace UPDATE directo
    SIN generar movimiento en CC.
    """
    imp = Imputacion(
        origen_tipo="orden_pago",
        origen_id=1,
        destino_tipo="pedido_compra",
        destino_id=pedido_id,
        monto_imputado=monto,
        moneda_imputada="ARS",
        proveedor_id=proveedor_id,
        es_reversal=False,
        creado_por_id=user_id,
    )
    db.add(imp)
    db.flush()
    return imp


from app.services import pedidos_service


# ──────────────────────────────────────────────────────────────────────────
# Vista SQLite (las migrations Alembic no corren en tests — la creamos a mano)
# ──────────────────────────────────────────────────────────────────────────

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
def empresa(db) -> Empresa:
    e = Empresa(id=1, nombre="EmpresaVinc", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=55,
        nombre="PROV_TEST",
        supp_id=55,
        comp_id=1,
        activo=True,
        origen=OrigenProveedor.ERP.value,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def proveedor_sin_supp(db) -> Proveedor:
    p = Proveedor(
        id=66,
        nombre="PROV_MANUAL",
        supp_id=None,
        activo=True,
        origen=OrigenProveedor.MANUAL.value,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def sd_factura(db) -> SaleDocument:
    sd = SaleDocument(
        sd_id=101,
        sd_desc="Factura compra",
        sd_ispurchase=True,
        sd_isinbalance=True,
        sd_istaxable=True,
        sd_plusorminus=1,
        hacc_group=9001,
    )
    db.add(sd)
    db.flush()
    return sd


def _crear_pedido(db, empresa, proveedor, active_user, *, monto=Decimal("1000"), ct_id=None):
    p = PedidoCompra(
        numero="P-TEST-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=monto,
        estado="aprobado",
        ct_transaction_id=ct_id,
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


def _crear_ct(db, *, ct_transaction, supp_id, ct_total, ct_docnumber="0000001", sd_id=101):
    ct = CommercialTransaction(
        ct_transaction=ct_transaction,
        comp_id=1,
        bra_id=1,
        supp_id=supp_id,
        ct_docNumber=ct_docnumber,
        sd_id=sd_id,
        ct_total=ct_total,
        ct_date=datetime(2026, 4, 15, 10, 0, 0),
        ct_isCancelled=False,
    )
    db.add(ct)
    db.flush()
    return ct


# ══════════════════════════════════════════════════════════════════════════
# vincular_factura
# ══════════════════════════════════════════════════════════════════════════


class TestVincularFactura:
    def test_happy_sin_ajuste(self, db, empresa, proveedor, sd_factura, active_user):
        pedido = _crear_pedido(db, empresa, proveedor, active_user)
        _crear_ct(
            db,
            ct_transaction=700001,
            supp_id=proveedor.supp_id,
            ct_total=Decimal("1000"),
        )

        pedidos_service.vincular_factura(
            db,
            pedido_id=pedido.id,
            ct_transaction=700001,
            user_id=active_user.id,
        )

        db.refresh(pedido)
        assert pedido.ct_transaction_id == 700001
        # Monto no se toca
        assert pedido.monto == Decimal("1000")
        # Evento 'factura_vinculada' presente
        ev = db.query(CompraEvento).filter_by(entidad_id=pedido.id, tipo="factura_vinculada").first()
        assert ev is not None
        assert ev.payload["ct_transaction"] == 700001
        assert ev.payload["modo"] == "manual"

    def test_pedido_ya_vinculado_409(self, db, empresa, proveedor, sd_factura, active_user):
        pedido = _crear_pedido(db, empresa, proveedor, active_user, ct_id=123456)
        _crear_ct(
            db,
            ct_transaction=700001,
            supp_id=proveedor.supp_id,
            ct_total=Decimal("1000"),
        )

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            pedidos_service.vincular_factura(
                db,
                pedido_id=pedido.id,
                ct_transaction=700001,
                user_id=active_user.id,
            )
        assert exc.value.status_code == 409

    def test_ct_no_vigente_400(self, db, empresa, proveedor, sd_factura, active_user):
        pedido = _crear_pedido(db, empresa, proveedor, active_user)
        # no creamos la ct → no existe en la vista

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            pedidos_service.vincular_factura(
                db,
                pedido_id=pedido.id,
                ct_transaction=700001,
                user_id=active_user.id,
            )
        assert exc.value.status_code == 400

    def test_proveedor_sin_supp_id_400(self, db, empresa, proveedor_sin_supp, sd_factura, active_user):
        pedido = _crear_pedido(db, empresa, proveedor_sin_supp, active_user)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            pedidos_service.vincular_factura(
                db,
                pedido_id=pedido.id,
                ct_transaction=700001,
                user_id=active_user.id,
            )
        assert exc.value.status_code == 400


# ══════════════════════════════════════════════════════════════════════════
# desvincular_factura
# ══════════════════════════════════════════════════════════════════════════


class TestDesvincularFactura:
    def test_happy(self, db, empresa, proveedor, sd_factura, active_user):
        pedido = _crear_pedido(db, empresa, proveedor, active_user, ct_id=555)

        pedidos_service.desvincular_factura(db, pedido_id=pedido.id, user_id=active_user.id)

        db.refresh(pedido)
        assert pedido.ct_transaction_id is None

        ev = db.query(CompraEvento).filter_by(entidad_id=pedido.id, tipo="factura_desvinculada").first()
        assert ev is not None
        assert ev.payload["ct_transaction_anterior"] == 555

    def test_sin_factura_400(self, db, empresa, proveedor, active_user):
        pedido = _crear_pedido(db, empresa, proveedor, active_user)  # ct_id=None

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            pedidos_service.desvincular_factura(db, pedido_id=pedido.id, user_id=active_user.id)
        assert exc.value.status_code == 400


# ══════════════════════════════════════════════════════════════════════════
# ajustar_monto_con_factura
# ══════════════════════════════════════════════════════════════════════════


class TestAjustarMontoConFactura:
    def test_aumento_crea_ajuste_positivo_en_cc(self, db, empresa, proveedor, sd_factura, active_user):
        """Sub-batch 4: solo genera ajuste CC si hay imputaciones vigentes."""
        pedido = _crear_pedido(db, empresa, proveedor, active_user, monto=Decimal("1000"))
        _crear_ct(
            db,
            ct_transaction=800001,
            supp_id=proveedor.supp_id,
            ct_total=Decimal("1150"),
        )
        _seed_imputacion_viva(db, pedido_id=pedido.id, proveedor_id=proveedor.id, user_id=active_user.id)

        pedidos_service.ajustar_monto_con_factura(
            db,
            pedido_id=pedido.id,
            ct_transaction=800001,
            nuevo_monto=Decimal("1150"),
            motivo="TC al pagar fue mayor que al pedido",
            user_id=active_user.id,
        )

        db.refresh(pedido)
        assert pedido.monto == Decimal("1150")
        assert pedido.ct_transaction_id == 800001

        # Movimiento CC con signo +1 (porque hay imputación viva).
        movs = db.query(CCProveedorMovimiento).filter_by(origen_tipo="ajuste_pedido", origen_id=pedido.id).all()
        assert len(movs) == 1
        assert movs[0].tipo == "ajuste"
        assert movs[0].signo_ajuste == 1
        assert movs[0].monto == Decimal("150")

        ev = db.query(CompraEvento).filter_by(entidad_id=pedido.id, tipo="monto_ajustado_por_factura").first()
        assert ev is not None
        assert ev.payload["monto_anterior"] == "1000"
        assert ev.payload["monto_nuevo"] == "1150"
        assert ev.payload["diferencia"] == "150"
        assert ev.payload["motivo"] == "TC al pagar fue mayor que al pedido"
        assert ev.payload["tenia_imputaciones_vivas"] is True

    def test_reduccion_crea_ajuste_negativo_en_cc(self, db, empresa, proveedor, sd_factura, active_user):
        """Sub-batch 4: con imputaciones vivas, reducción genera ajuste -1."""
        pedido = _crear_pedido(db, empresa, proveedor, active_user, monto=Decimal("1000"))
        _crear_ct(
            db,
            ct_transaction=800002,
            supp_id=proveedor.supp_id,
            ct_total=Decimal("900"),
        )
        _seed_imputacion_viva(db, pedido_id=pedido.id, proveedor_id=proveedor.id, user_id=active_user.id)

        pedidos_service.ajustar_monto_con_factura(
            db,
            pedido_id=pedido.id,
            ct_transaction=800002,
            nuevo_monto=Decimal("900"),
            motivo="Proveedor descuento tardío",
            user_id=active_user.id,
        )

        db.refresh(pedido)
        assert pedido.monto == Decimal("900")

        mov = db.query(CCProveedorMovimiento).filter_by(origen_tipo="ajuste_pedido", origen_id=pedido.id).one()
        assert mov.signo_ajuste == -1
        assert mov.monto == Decimal("100")

    def test_sin_imputaciones_update_directo_sin_mov_cc(self, db, empresa, proveedor, sd_factura, active_user):
        """Sub-batch 4 nuevo: pedido sin imputaciones → solo UPDATE, evento diferente."""
        pedido = _crear_pedido(db, empresa, proveedor, active_user, monto=Decimal("1000"))
        _crear_ct(
            db,
            ct_transaction=800007,
            supp_id=proveedor.supp_id,
            ct_total=Decimal("1300"),
        )

        pedidos_service.ajustar_monto_con_factura(
            db,
            pedido_id=pedido.id,
            ct_transaction=800007,
            nuevo_monto=Decimal("1300"),
            motivo="monto real de factura",
            user_id=active_user.id,
        )

        db.refresh(pedido)
        assert pedido.monto == Decimal("1300")

        # NINGÚN movimiento CC creado
        count = db.query(CCProveedorMovimiento).filter_by(origen_tipo="ajuste_pedido", origen_id=pedido.id).count()
        assert count == 0

        # Evento distinto
        ev = db.query(CompraEvento).filter_by(entidad_id=pedido.id, tipo="monto_actualizado_sin_imputaciones").one()
        assert ev.payload["tenia_imputaciones_vivas"] is False

    def test_diferencia_cero_no_emite_cc(self, db, empresa, proveedor, sd_factura, active_user):
        pedido = _crear_pedido(db, empresa, proveedor, active_user, monto=Decimal("1000"))
        _crear_ct(
            db,
            ct_transaction=800003,
            supp_id=proveedor.supp_id,
            ct_total=Decimal("1000"),
        )

        pedidos_service.ajustar_monto_con_factura(
            db,
            pedido_id=pedido.id,
            ct_transaction=800003,
            nuevo_monto=Decimal("1000"),
            motivo="Vinculación con ajuste nominal (dif=0)",
            user_id=active_user.id,
        )

        db.refresh(pedido)
        assert pedido.monto == Decimal("1000")
        # NO se creó movimiento CC porque dif=0
        n = db.query(CCProveedorMovimiento).filter_by(origen_tipo="ajuste_pedido", origen_id=pedido.id).count()
        assert n == 0

    def test_motivo_vacio_400(self, db, empresa, proveedor, sd_factura, active_user):
        pedido = _crear_pedido(db, empresa, proveedor, active_user)
        _crear_ct(
            db,
            ct_transaction=800004,
            supp_id=proveedor.supp_id,
            ct_total=Decimal("1100"),
        )

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            pedidos_service.ajustar_monto_con_factura(
                db,
                pedido_id=pedido.id,
                ct_transaction=800004,
                nuevo_monto=Decimal("1100"),
                motivo="    ",  # solo espacios
                user_id=active_user.id,
            )
        assert exc.value.status_code == 400

    def test_nuevo_monto_invalido_400(self, db, empresa, proveedor, sd_factura, active_user):
        pedido = _crear_pedido(db, empresa, proveedor, active_user)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            pedidos_service.ajustar_monto_con_factura(
                db,
                pedido_id=pedido.id,
                ct_transaction=1,
                nuevo_monto=Decimal("0"),
                motivo="x",
                user_id=active_user.id,
            )
        assert exc.value.status_code == 400

    def test_pedido_ya_vinculado_a_otra_factura_409(self, db, empresa, proveedor, sd_factura, active_user):
        pedido = _crear_pedido(db, empresa, proveedor, active_user, ct_id=111)
        _crear_ct(
            db,
            ct_transaction=222,
            supp_id=proveedor.supp_id,
            ct_total=Decimal("1100"),
        )

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            pedidos_service.ajustar_monto_con_factura(
                db,
                pedido_id=pedido.id,
                ct_transaction=222,
                nuevo_monto=Decimal("1100"),
                motivo="reajuste",
                user_id=active_user.id,
            )
        assert exc.value.status_code == 409


# ══════════════════════════════════════════════════════════════════════════
# match_backward con diferencia de monto → alerta sin ajustar
# ══════════════════════════════════════════════════════════════════════════


class TestMatchBackwardMismatchMonto:
    def test_genera_evento_y_notificacion_sin_tocar_monto(self, db, empresa, proveedor, sd_factura, active_user):
        """
        Fix 4 (batch "4 riesgos compras"): el hook de matching ya NO crea
        `Notificacion(user_id=None)` (invisible por el filtro estricto del
        endpoint `GET /notificaciones`). Ahora hace fan-out a usuarios con
        permisos `administracion.gestionar_ordenes_compra` o
        `administracion.ver_cuentas_corrientes`.

        Este test siembra un usuario admin con ambos permisos base y valida
        que RECIBE la notificación.
        """
        from app.core.compras_empresa_erp_map import (  # noqa: PLC0415
            EMPRESA_A_COMP_BRA_MAP,
        )
        from app.core.security import get_password_hash  # noqa: PLC0415
        from app.models.notificacion import Notificacion  # noqa: PLC0415
        from app.models.permiso import Permiso, RolPermisoBase  # noqa: PLC0415
        from app.models.rol import Rol  # noqa: PLC0415
        from app.models.usuario import AuthProvider, RolUsuario, Usuario  # noqa: PLC0415
        from app.services.erp_matching_service import match_backward  # noqa: PLC0415

        # Asegurar mapeo empresa.id=1 → (comp_id=1, bra_id=1) en el test
        EMPRESA_A_COMP_BRA_MAP[empresa.id] = (1, 1)

        # Sembrar permisos + rol + usuario admin que recibirá la notificación.
        p_ops = Permiso(
            codigo="administracion.gestionar_ordenes_compra",
            nombre="Gestionar órdenes de compra",
            categoria="administracion",
        )
        p_cc = Permiso(
            codigo="administracion.ver_cuentas_corrientes",
            nombre="Ver CC",
            categoria="administracion",
        )
        db.add_all([p_ops, p_cc])
        db.flush()

        rol_admin_c = Rol(codigo="ADMIN_COMPRAS_T", nombre="Admin Compras Test", activo=True, orden=5)
        db.add(rol_admin_c)
        db.flush()
        db.add_all(
            [
                RolPermisoBase(rol_id=rol_admin_c.id, permiso_id=p_ops.id),
                RolPermisoBase(rol_id=rol_admin_c.id, permiso_id=p_cc.id),
            ]
        )
        db.flush()

        admin_dest = Usuario(
            username="admin_destinatario",
            email="admin_dest@example.com",
            nombre="Admin Destinatario",
            password_hash=get_password_hash("TestPass123!"),
            rol=RolUsuario.ADMIN,
            rol_id=rol_admin_c.id,
            auth_provider=AuthProvider.LOCAL,
            activo=True,
        )
        db.add(admin_dest)
        db.flush()

        # Pedido con numero_factura (que matchea ct_docnumber)
        pedido = PedidoCompra(
            numero="P-TEST-00002",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("1000"),
            numero_factura="0000099",
            estado="aprobado",
            creado_por_id=active_user.id,
        )
        db.add(pedido)
        db.flush()

        _crear_ct(
            db,
            ct_transaction=900099,
            supp_id=proveedor.supp_id,
            ct_total=Decimal("1234.56"),
            ct_docnumber="0000099",
        )

        resumen = match_backward(db, cts_synced=[900099])
        assert resumen["pedidos_asociados"] == 1

        db.refresh(pedido)
        # El monto NO debe haberse tocado
        assert pedido.monto == Decimal("1000")
        # El pedido SÍ se vinculó
        assert pedido.ct_transaction_id == 900099

        # Evento de mismatch
        ev = db.query(CompraEvento).filter_by(entidad_id=pedido.id, tipo="monto_difiere_al_matchear").first()
        assert ev is not None
        assert ev.payload["ct_total_erp"] == "1234.56"
        assert ev.payload["monto_pedido"] == "1000"
        assert Decimal(ev.payload["diferencia"]) == Decimal("234.56")

        # Notificación WARNING dirigida AL ADMIN con permiso (Fix 4):
        # antes era `user_id=None` y no la veía nadie.
        notif = (
            db.query(Notificacion).filter_by(tipo="compras.pedido_monto_difiere_factura", user_id=admin_dest.id).first()
        )
        assert notif is not None, (
            "Fix 4: la notificación debe dirigirse al usuario con permisos "
            "(`administracion.gestionar_ordenes_compra` o `ver_cuentas_corrientes`). "
            "Antes se creaba con `user_id=None` y el endpoint `GET /notificaciones` "
            "la filtraba → nadie la veía."
        )
        assert notif.severidad.value == "WARNING"
        assert notif.item_id == pedido.id
