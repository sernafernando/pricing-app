"""
Tests unitarios — Slice 2 backend: cheques de terceros + endoso en OP.

TDD Strict — FR-2.1, FR-2.2, FR-2.4:
  - recibir_cheque_tercero: estado en_cartera, validaciones.
  - Máquina de estados terceros: entregar / anular / rechazar + transición inválida.
  - Endoso en OP: cheque de cartera → entregado + imputa pedido → saldo 0.
  - Endoso combinado: cheque tercero + caja.
  - Des-endoso al anular OP: cheque vuelve a en_cartera.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.banco_empresa import BancoEmpresa
from app.models.caja import Caja
from app.models.cheque import Cheque, OrdenPagoCheque
from app.models.empresa import Empresa
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import cheques_service, ordenes_pago_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures comunes
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=80, nombre="EmpresaSlice2", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=80,
        nombre="ProveedorSlice2",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=800,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def banco(db, empresa) -> BancoEmpresa:
    b = BancoEmpresa(
        id=80,
        banco="BancoSlice2",
        moneda="ARS",
        empresa_id=empresa.id,
        activo=True,
    )
    db.add(b)
    db.flush()
    return b


@pytest.fixture
def tipos_doc_caja(db) -> None:
    from app.models.caja import CajaTipoDocumento

    for nombre in ("Orden de Pago", "Orden de Pago Anulada"):
        existing = db.query(CajaTipoDocumento).filter(CajaTipoDocumento.nombre == nombre).first()
        if not existing:
            db.add(CajaTipoDocumento(nombre=nombre, descripcion=nombre, activo=True))
    db.flush()


@pytest.fixture
def caja(db, empresa, tipos_doc_caja) -> Caja:
    c = Caja(
        nombre="CajaSlice2",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_actual=Decimal("5000000"),
        saldo_inicial=Decimal("5000000"),
        activo=True,
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def pedido_500k(db, empresa, proveedor, active_user):
    """Pedido ARS 500_000 en estado aprobado."""
    from app.models.pedido_compra import PedidoCompra

    p = PedidoCompra(
        id=80,
        numero="PC-80-2026-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("500000"),
        tipo_cambio=None,
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(p)
    db.flush()
    return p


def _cheque_tercero(db, numero: str = "CH-T-001", monto: Decimal | None = None, active_user=None) -> Cheque:
    """Crea un cheque de tercero en cartera."""
    return cheques_service.recibir_cheque_tercero(
        db,
        banco_nombre="Banco Nación",
        cuit_librador="20112233445",
        librador_nombre="Tercero SA",
        numero=numero,
        monto=monto or Decimal("500000"),
        moneda="ARS",
        fecha_emision=date(2026, 6, 22),
        fecha_pago=date(2026, 7, 22),
        instrumento="fisico",
        usuario_id=active_user.id if active_user else None,
    )


# ──────────────────────────────────────────────────────────────────────────
# FR-2.1 — Alta a cartera
# ──────────────────────────────────────────────────────────────────────────


class TestCuitLibradorFormato:
    """Fix 4 — validación de formato CUIT en RecibirChequeTercero."""

    def test_cuit_con_letras_levanta_422(self, db) -> None:
        from app.schemas.cheque import RecibirChequeTercero

        with pytest.raises(Exception):
            RecibirChequeTercero(
                banco_nombre="Banco X",
                cuit_librador="XX-11223344-5",  # letras → inválido
                numero="CH-BAD-CUIT",
                monto=Decimal("1000"),
                moneda="ARS",
                fecha_emision=date(2026, 6, 22),
                fecha_pago=date(2026, 7, 22),
            )

    def test_cuit_sin_guiones_acepta(self, db) -> None:
        from app.schemas.cheque import RecibirChequeTercero

        payload = RecibirChequeTercero(
            banco_nombre="Banco X",
            cuit_librador="20112233445",  # 11 dígitos, sin guiones
            numero="CH-CUIT-OK",
            monto=Decimal("1000"),
            moneda="ARS",
            fecha_emision=date(2026, 6, 22),
            fecha_pago=date(2026, 7, 22),
        )
        assert payload.cuit_librador == "20112233445"

    def test_cuit_con_guiones_acepta(self, db) -> None:
        from app.schemas.cheque import RecibirChequeTercero

        payload = RecibirChequeTercero(
            banco_nombre="Banco X",
            cuit_librador="20-11223344-5",  # formato con guiones
            numero="CH-CUIT-GUION",
            monto=Decimal("1000"),
            moneda="ARS",
            fecha_emision=date(2026, 6, 22),
            fecha_pago=date(2026, 7, 22),
        )
        assert payload.cuit_librador == "20-11223344-5"


class TestChequeListResponseCamposTercero:
    """Fix 3 — ChequeListResponse y ChequeResponse exponen cuit_librador y librador_nombre."""

    def test_list_response_trae_cuit_y_librador(self, db, active_user) -> None:
        from app.schemas.cheque import ChequeListResponse

        cheque = _cheque_tercero(db, numero="CH-T-SCHEMA-001", active_user=active_user)
        db.flush()

        resp = ChequeListResponse.model_validate(cheque)
        assert resp.cuit_librador == "20112233445"
        assert resp.librador_nombre == "Tercero SA"

    def test_response_trae_cuit_y_librador(self, db, active_user) -> None:
        from app.schemas.cheque import ChequeResponse

        cheque = _cheque_tercero(db, numero="CH-T-SCHEMA-002", active_user=active_user)
        db.flush()

        resp = ChequeResponse.model_validate(cheque)
        assert resp.cuit_librador == "20112233445"
        assert resp.librador_nombre == "Tercero SA"


class TestRecibirChequeTercero:
    def test_crea_en_estado_en_cartera(self, db, active_user) -> None:
        cheque = _cheque_tercero(db, active_user=active_user)
        db.flush()
        assert cheque.id is not None
        assert cheque.tipo == "tercero"
        assert cheque.estado == "en_cartera"

    def test_campos_librador_guardados(self, db, active_user) -> None:
        cheque = _cheque_tercero(db, active_user=active_user)
        db.flush()
        assert cheque.banco_nombre == "Banco Nación"
        assert cheque.cuit_librador == "20112233445"
        assert cheque.librador_nombre == "Tercero SA"

    def test_no_usa_banco_empresa_ni_chequera(self, db, active_user) -> None:
        cheque = _cheque_tercero(db, active_user=active_user)
        db.flush()
        assert cheque.banco_empresa_id is None
        assert cheque.chequera_id is None

    def test_registra_evento_recibido(self, db, active_user) -> None:
        from app.models.cheque import ChequeEvento

        cheque = _cheque_tercero(db, active_user=active_user)
        db.flush()
        eventos = db.query(ChequeEvento).filter(ChequeEvento.cheque_id == cheque.id).all()
        assert any(e.tipo == "recibido" for e in eventos), "Debe existir evento 'recibido'"

    def test_valida_monto_cero(self, db) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            cheques_service.recibir_cheque_tercero(
                db,
                banco_nombre="Banco X",
                cuit_librador="20112233445",
                numero="CH-0",
                monto=Decimal("0"),
                moneda="ARS",
                fecha_emision=date(2026, 6, 22),
                fecha_pago=date(2026, 7, 22),
            )
        assert exc_info.value.status_code == 422

    def test_valida_fecha_pago_anterior_emision(self, db) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            cheques_service.recibir_cheque_tercero(
                db,
                banco_nombre="Banco X",
                cuit_librador="20112233445",
                numero="CH-FECHAS",
                monto=Decimal("1000"),
                moneda="ARS",
                fecha_emision=date(2026, 6, 22),
                fecha_pago=date(2026, 6, 21),  # anterior a emision
            )
        assert exc_info.value.status_code == 422

    def test_valida_banco_nombre_requerido(self, db) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            cheques_service.recibir_cheque_tercero(
                db,
                banco_nombre="   ",  # blank
                cuit_librador="20112233445",
                numero="CH-BLANK",
                monto=Decimal("1000"),
                moneda="ARS",
                fecha_emision=date(2026, 6, 22),
                fecha_pago=date(2026, 7, 22),
            )
        assert exc_info.value.status_code == 422

    def test_valida_cuit_librador_requerido(self, db) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            cheques_service.recibir_cheque_tercero(
                db,
                banco_nombre="Banco X",
                cuit_librador="  ",  # blank
                numero="CH-CUIT",
                monto=Decimal("1000"),
                moneda="ARS",
                fecha_emision=date(2026, 6, 22),
                fecha_pago=date(2026, 7, 22),
            )
        assert exc_info.value.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# FR-2.4 — Máquina de estados terceros
# ──────────────────────────────────────────────────────────────────────────


class TestTransicionesTerceros:
    def test_entregar_en_cartera_a_entregado(self, db, active_user) -> None:
        cheque = _cheque_tercero(db, numero="CH-T-ENT", active_user=active_user)
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "entregar", usuario_id=active_user.id)
        assert cheque.estado == "entregado"

    def test_anular_en_cartera_a_anulado(self, db, active_user) -> None:
        cheque = _cheque_tercero(db, numero="CH-T-ANU", active_user=active_user)
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "anular", usuario_id=active_user.id, motivo="Error")
        assert cheque.estado == "anulado"

    def test_rechazar_en_cartera(self, db, active_user) -> None:
        cheque = _cheque_tercero(db, numero="CH-T-REC1", active_user=active_user)
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "rechazar", usuario_id=active_user.id)
        assert cheque.estado == "rechazado"

    def test_rechazar_entregado(self, db, active_user) -> None:
        cheque = _cheque_tercero(db, numero="CH-T-REC2", active_user=active_user)
        db.flush()
        # Primero entregar
        cheques_service.transicionar_cheque(db, cheque, "entregar", usuario_id=active_user.id)
        assert cheque.estado == "entregado"
        # Luego rechazar
        cheques_service.transicionar_cheque(db, cheque, "rechazar", usuario_id=active_user.id)
        assert cheque.estado == "rechazado"

    def test_transicion_invalida_levanta_422(self, db, active_user) -> None:
        from fastapi import HTTPException

        cheque = _cheque_tercero(db, numero="CH-T-INV", active_user=active_user)
        db.flush()
        # "debitar" no existe para tercero en cartera
        with pytest.raises(HTTPException) as exc_info:
            cheques_service.transicionar_cheque(db, cheque, "debitar", usuario_id=active_user.id)
        assert exc_info.value.status_code == 422

    def test_estado_terminal_no_permite_transicion(self, db, active_user) -> None:
        from fastapi import HTTPException

        cheque = _cheque_tercero(db, numero="CH-T-TERM", active_user=active_user)
        db.flush()
        cheques_service.transicionar_cheque(db, cheque, "anular", usuario_id=active_user.id, motivo="Test")
        assert cheque.estado == "anulado"
        with pytest.raises(HTTPException) as exc_info:
            cheques_service.transicionar_cheque(db, cheque, "rechazar", usuario_id=active_user.id)
        assert exc_info.value.status_code == 422

    def test_propios_no_se_rompen(self, db, banco, active_user) -> None:
        """Regresión: transiciones de propios siguen funcionando."""
        from app.models.cheque import Chequera

        chequera = Chequera(
            banco_empresa_id=banco.id,
            instrumento="echeq",
            numero_desde=1,
            numero_hasta=100,
            proximo_numero=1,
            activa=True,
        )
        db.add(chequera)
        db.flush()

        cheque_propio = cheques_service.emitir_cheque_propio(
            db,
            tipo="propio",
            instrumento="echeq",
            numero="P-REG-001",
            monto=Decimal("1000"),
            moneda="ARS",
            fecha_emision=date(2026, 6, 22),
            fecha_pago=date(2026, 6, 22),
            banco_empresa_id=banco.id,
            chequera_id=chequera.id,
        )
        db.flush()
        assert cheque_propio.estado == "emitido"

        cheques_service.transicionar_cheque(db, cheque_propio, "anular", motivo="Regresión", usuario_id=active_user.id)
        assert cheque_propio.estado == "anulado"


# ──────────────────────────────────────────────────────────────────────────
# FR-2.2 — Endoso en OP
# ──────────────────────────────────────────────────────────────────────────


class TestEndosoTerceroEnOP:
    def test_endoso_imputa_pedido_saldo_cero(self, db, empresa, proveedor, banco, pedido_500k, active_user) -> None:
        """
        OP ARS 500_000.
        Cheque tercero 500_000 (100% cobertura) con pedido_id.
        Tras pagar: saldo_pendiente == 0, cheque estado='entregado'.
        """
        from app.services.pedidos_service import calcular_saldo_pendiente_pedido

        cheque = _cheque_tercero(db, numero="CH-T-OP-001", active_user=active_user)
        db.flush()
        assert cheque.estado == "en_cartera"

        op = ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("500000"),
            # modo_imputacion="a_cuenta" es correcto cuando items=[] y la imputación
            # específica al pedido se expresa solo vía pedido_id en el cheque.
            # El cheque lleva pedido_id → _imputar_cheque_en_op toma el Caso A.
            modo_imputacion="a_cuenta",
            items=[],
            caja_id=None,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 22),
            creado_por_id=active_user.id,
            cheques=[
                {
                    "cheque_id": cheque.id,
                    "monto": cheque.monto,
                    "moneda": cheque.moneda,
                    "pedido_id": pedido_500k.id,
                }
            ],
        )

        assert op.estado == "pagado"

        db.refresh(cheque)
        assert cheque.estado == "entregado"
        assert cheque.proveedor_id == proveedor.id
        assert cheque.orden_pago_id == op.id

        # OrdenPagoCheque creado
        link = db.query(OrdenPagoCheque).filter(OrdenPagoCheque.cheque_id == cheque.id).one()
        assert link.monto_op_moneda == Decimal("500000")

        # Saldo del pedido = 0
        saldo = calcular_saldo_pendiente_pedido(db, pedido_500k.id)
        assert saldo == Decimal("0"), f"Esperaba saldo=0, got {saldo}"

    def test_endoso_a_cuenta_sin_pedido_id(self, db, empresa, proveedor, active_user) -> None:
        """
        Cheque tercero sin pedido_id → haber directo CC (a cuenta).
        """
        from app.models.cc_proveedor_movimiento import CCProveedorMovimiento

        cheque = _cheque_tercero(db, numero="CH-T-OP-002", active_user=active_user)
        db.flush()

        op = ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("500000"),
            modo_imputacion="a_cuenta",
            items=[],
            caja_id=None,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 22),
            creado_por_id=active_user.id,
            cheques=[
                {
                    "cheque_id": cheque.id,
                    "monto": cheque.monto,
                    "moneda": cheque.moneda,
                }
            ],
        )

        assert op.estado == "pagado"
        db.refresh(cheque)
        assert cheque.estado == "entregado"

        # Haber directo CC (origen_tipo='cheque')
        mov = (
            db.query(CCProveedorMovimiento)
            .filter(
                CCProveedorMovimiento.proveedor_id == proveedor.id,
                CCProveedorMovimiento.origen_tipo == "cheque",
                CCProveedorMovimiento.tipo == "haber",
            )
            .one_or_none()
        )
        assert mov is not None, "Debe existir haber directo CC para endoso a_cuenta"

    def test_endoso_tercero_mas_caja_combinados(self, db, empresa, proveedor, caja, pedido_500k, active_user) -> None:
        """
        OP ARS 500_000.
        Cheque tercero 300_000 + caja 200_000.
        Saldo del pedido = 0.
        """
        from app.services.pedidos_service import calcular_saldo_pendiente_pedido

        cheque = _cheque_tercero(db, numero="CH-T-OP-003", monto=Decimal("300000"), active_user=active_user)
        db.flush()

        op = ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("500000"),
            modo_imputacion="especifica",
            items=[{"tipo": "pedido_compra", "id": pedido_500k.id, "monto": Decimal("200000")}],
            caja_id=caja.id,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 22),
            creado_por_id=active_user.id,
            cheques=[
                {
                    "cheque_id": cheque.id,
                    "monto": cheque.monto,
                    "moneda": cheque.moneda,
                    "pedido_id": pedido_500k.id,
                }
            ],
        )

        assert op.estado == "pagado"
        saldo = calcular_saldo_pendiente_pedido(db, pedido_500k.id)
        assert saldo == Decimal("0"), f"Esperaba saldo=0, got {saldo}"

    def test_endoso_cheque_no_en_cartera_levanta_422(self, db, empresa, proveedor, active_user) -> None:
        """Intentar endosar un cheque que ya fue entregado → 422."""
        from fastapi import HTTPException

        cheque = _cheque_tercero(db, numero="CH-T-OP-YA", active_user=active_user)
        db.flush()
        # Manualmente marcar como entregado para simular estado incorrecto
        cheque.estado = "entregado"
        db.flush()

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.crear_y_pagar(
                db,
                proveedor_id=proveedor.id,
                empresa_id=empresa.id,
                moneda="ARS",
                monto_total=Decimal("500000"),
                modo_imputacion="a_cuenta",
                items=[],
                caja_id=None,
                banco_id=None,
                fecha_pago_real=date(2026, 6, 22),
                creado_por_id=active_user.id,
                cheques=[
                    {
                        "cheque_id": cheque.id,
                        "monto": cheque.monto,
                        "moneda": cheque.moneda,
                    }
                ],
            )
        assert exc_info.value.status_code == 422

    def test_endoso_cheque_propio_por_id_levanta_422(self, db, empresa, proveedor, banco, active_user) -> None:
        """No se puede endosar un cheque propio usando cheque_id (solo terceros)."""
        from fastapi import HTTPException

        # Crear un cheque propio sin chequera (echeq)
        cheque_propio = cheques_service.emitir_cheque_propio(
            db,
            tipo="propio",
            instrumento="echeq",
            numero="P-NO-ENDOSAR",
            monto=Decimal("500000"),
            moneda="ARS",
            fecha_emision=date(2026, 6, 22),
            fecha_pago=date(2026, 6, 22),
            banco_empresa_id=banco.id,
        )
        db.flush()

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.crear_y_pagar(
                db,
                proveedor_id=proveedor.id,
                empresa_id=empresa.id,
                moneda="ARS",
                monto_total=Decimal("500000"),
                modo_imputacion="a_cuenta",
                items=[],
                caja_id=None,
                banco_id=None,
                fecha_pago_real=date(2026, 6, 22),
                creado_por_id=active_user.id,
                cheques=[
                    {
                        "cheque_id": cheque_propio.id,
                        "monto": cheque_propio.monto,
                        "moneda": cheque_propio.moneda,
                    }
                ],
            )
        assert exc_info.value.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# Des-endoso al anular OP
# ──────────────────────────────────────────────────────────────────────────


class TestDesEndosoAlAnularOP:
    def test_anular_op_devuelve_cheque_tercero_a_cartera(self, db, empresa, proveedor, active_user) -> None:
        """
        Cheque tercero endosado 100% en OP (sin caja) → anular OP →
        cheque vuelve a 'en_cartera'; proveedor_id y orden_pago_id se limpian.
        OP modo a_cuenta, cheque cubre el 100% del monto.
        """
        cheque = _cheque_tercero(db, numero="CH-T-REVERT-001", active_user=active_user)
        db.flush()

        # OP 100% cubierta por el cheque tercero (sin caja/banco adicional).
        # modo a_cuenta: items=[] → balance: cheques(500k) = monto_total(500k).
        op = ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("500000"),
            modo_imputacion="a_cuenta",
            items=[],
            caja_id=None,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 22),
            creado_por_id=active_user.id,
            cheques=[
                {
                    "cheque_id": cheque.id,
                    "monto": cheque.monto,
                    "moneda": cheque.moneda,
                }
            ],
        )

        db.refresh(cheque)
        assert cheque.estado == "entregado"

        # Anular la OP
        ordenes_pago_service.anular(
            db,
            orden_pago_id=op.id,
            motivo="Test des-endoso",
            user_id=active_user.id,
        )

        db.refresh(cheque)
        assert cheque.estado == "en_cartera", f"Esperaba 'en_cartera', got '{cheque.estado}'"
        assert cheque.proveedor_id is None, "proveedor_id debe limpiarse en des-endoso"
        assert cheque.orden_pago_id is None, "orden_pago_id debe limpiarse en des-endoso"

    def test_anular_op_con_cheque_tercero_imputa_pedido_restaura_saldo(
        self, db, empresa, proveedor, caja, pedido_500k, active_user
    ) -> None:
        """
        Cheque tercero con pedido_id → pagar → saldo=0.
        Anular OP → cheque vuelve a en_cartera + saldo pedido restaurado.
        """
        from app.services.pedidos_service import calcular_saldo_pendiente_pedido

        cheque = _cheque_tercero(db, numero="CH-T-REVERT-002", active_user=active_user)
        db.flush()

        op = ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("500000"),
            modo_imputacion="a_cuenta",
            items=[],
            caja_id=None,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 22),
            creado_por_id=active_user.id,
            cheques=[
                {
                    "cheque_id": cheque.id,
                    "monto": cheque.monto,
                    "moneda": cheque.moneda,
                    "pedido_id": pedido_500k.id,
                }
            ],
        )

        assert calcular_saldo_pendiente_pedido(db, pedido_500k.id) == Decimal("0")

        ordenes_pago_service.anular(
            db,
            orden_pago_id=op.id,
            motivo="Test reversal",
            user_id=active_user.id,
        )

        db.refresh(cheque)
        assert cheque.estado == "en_cartera"
        # Saldo del pedido debe haberse restaurado
        saldo_post = calcular_saldo_pendiente_pedido(db, pedido_500k.id)
        assert saldo_post == Decimal("500000"), f"Esperaba saldo=500000, got {saldo_post}"


# ──────────────────────────────────────────────────────────────────────────
# Fix 1 — Guard over-imputación: item + cheque sobre mismo pedido
# ──────────────────────────────────────────────────────────────────────────


class TestOverImputacionItemMasCheque:
    def test_item_mas_cheque_mismo_pedido_levanta_422(self, db, empresa, proveedor, pedido_500k, active_user) -> None:
        """
        OP ARS 950_000.
        Item pedido_compra 450_000 sobre pedido saldo 500_000.
        Cheque tercero 500_000 sobre el MISMO pedido.
        Total a imputar: 950_000 > saldo 500_000 → debe lanzar 422.

        Verifica que session.flush() entre el loop de items y el loop de
        cheques hace que _imputar_cheque_en_op vea el saldo ya reducido.
        """
        from fastapi import HTTPException

        cheque = _cheque_tercero(db, numero="CH-T-OVER-001", monto=Decimal("500000"), active_user=active_user)
        db.flush()

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.crear_y_pagar(
                db,
                proveedor_id=proveedor.id,
                empresa_id=empresa.id,
                moneda="ARS",
                monto_total=Decimal("950000"),
                modo_imputacion="especifica",
                items=[
                    {
                        "tipo": "pedido_compra",
                        "id": pedido_500k.id,
                        "monto": Decimal("450000"),
                    }
                ],
                caja_id=None,
                banco_id=None,
                fecha_pago_real=date(2026, 6, 22),
                creado_por_id=active_user.id,
                cheques=[
                    {
                        "cheque_id": cheque.id,
                        "monto": Decimal("500000"),
                        "moneda": "ARS",
                        "pedido_id": pedido_500k.id,
                    }
                ],
            )
        assert exc_info.value.status_code == 422, (
            f"Esperaba 422 over-imputación, got {exc_info.value.status_code}: {exc_info.value.detail}"
        )
