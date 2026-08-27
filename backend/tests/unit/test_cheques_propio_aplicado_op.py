"""
Tests unitarios — Slice S2: aplicar un cheque PROPIO preexistente a una OP al pagar.

TDD Strict — R2/R3/R5/R9/R11:
  - R2: solo estados 'emitido'/'diferido' pueden aplicarse; el resto 422 nombrando el estado.
  - R3: beneficiario — mismatch rechazado (nada persiste); null se completa desde la OP;
    match no dispara escritura espuria.
  - R5: el camino de endoso de tercero queda intacto (regresión).
  - R9: derive cross-moneda cubre también el camino de aplicación de propio.
  - R11: el evento 'aplicado_a_op' con origen='preexistente' es el discriminador;
    emitir_cheque_propio jamás lo escribe.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.banco_empresa import BancoEmpresa
from app.models.cheque import Cheque, ChequeEvento, OrdenPagoCheque
from app.models.empresa import Empresa
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import cheques_service, ordenes_pago_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=90, nombre="EmpresaChequePropioOP", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=90,
        nombre="ProveedorChequePropioOP",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=900,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def otro_proveedor(db) -> Proveedor:
    p = Proveedor(
        id=91,
        nombre="OtroProveedorChequePropioOP",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=901,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def banco(db, empresa) -> BancoEmpresa:
    b = BancoEmpresa(
        id=90,
        banco="BancoChequePropioOP",
        moneda="ARS",
        empresa_id=empresa.id,
        activo=True,
    )
    db.add(b)
    db.flush()
    return b


def _cheque_propio(
    db,
    *,
    numero: str,
    banco_empresa_id: int,
    moneda: str = "ARS",
    monto: Decimal = Decimal("500000"),
    fecha_emision: date = date(2026, 6, 22),
    fecha_pago: date | None = None,
    proveedor_id: int | None = None,
) -> Cheque:
    """Emite un cheque propio standalone (sin OP), como haría el flujo de alta."""
    return cheques_service.emitir_cheque_propio(
        db,
        tipo="propio",
        instrumento="echeq",
        numero=numero,
        monto=monto,
        moneda=moneda,
        fecha_emision=fecha_emision,
        fecha_pago=fecha_pago or fecha_emision,
        banco_empresa_id=banco_empresa_id,
        proveedor_id=proveedor_id,
    )


def _pagar_con_cheque_propio(db, *, empresa, proveedor, cheque, monto_total=None, active_user=None):
    return ordenes_pago_service.crear_y_pagar(
        db,
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        moneda="ARS",
        monto_total=monto_total if monto_total is not None else cheque.monto,
        modo_imputacion="a_cuenta",
        items=[],
        caja_id=None,
        banco_id=None,
        fecha_pago_real=date(2026, 6, 22),
        creado_por_id=active_user.id if active_user else None,
        cheques=[
            {
                "cheque_id": cheque.id,
                "monto": cheque.monto,
                "moneda": cheque.moneda,
            }
        ],
    )


# ──────────────────────────────────────────────────────────────────────────
# R2 — estados permitidos
# ──────────────────────────────────────────────────────────────────────────


class TestAplicarPropioEstadosPermitidos:
    def test_acepta_estado_emitido(self, db, empresa, proveedor, banco, active_user) -> None:
        cheque = _cheque_propio(db, numero="P-EMITIDO-OK", banco_empresa_id=banco.id)
        db.flush()
        assert cheque.estado == "emitido"

        op = _pagar_con_cheque_propio(db, empresa=empresa, proveedor=proveedor, cheque=cheque, active_user=active_user)

        assert op.estado == "pagado"
        db.refresh(cheque)
        assert cheque.orden_pago_id == op.id

    def test_acepta_estado_diferido(self, db, empresa, proveedor, banco, active_user) -> None:
        cheque = _cheque_propio(
            db,
            numero="P-DIFERIDO-OK",
            banco_empresa_id=banco.id,
            fecha_emision=date(2026, 6, 22),
            fecha_pago=date(2026, 7, 22),
        )
        db.flush()
        assert cheque.estado == "diferido"

        op = _pagar_con_cheque_propio(db, empresa=empresa, proveedor=proveedor, cheque=cheque, active_user=active_user)

        assert op.estado == "pagado"
        db.refresh(cheque)
        assert cheque.orden_pago_id == op.id


class TestAplicarPropioEstadosRechazados:
    @pytest.mark.parametrize("estado_terminal", ["debitado", "anulado", "rechazado", "en_custodia"])
    def test_rechaza_estados_terminales_nombrando_estado(
        self, db, empresa, proveedor, banco, active_user, estado_terminal
    ) -> None:
        cheque = _cheque_propio(db, numero=f"P-{estado_terminal.upper()}", banco_empresa_id=banco.id)
        db.flush()
        cheque.estado = estado_terminal
        db.flush()

        with pytest.raises(HTTPException) as exc_info:
            _pagar_con_cheque_propio(db, empresa=empresa, proveedor=proveedor, cheque=cheque, active_user=active_user)

        assert exc_info.value.status_code == 422
        assert estado_terminal in str(exc_info.value.detail)


# ──────────────────────────────────────────────────────────────────────────
# R3 — beneficiario
# ──────────────────────────────────────────────────────────────────────────


class TestAplicarPropioBeneficiario:
    def test_mismatch_rechazado_nada_persiste(self, db, empresa, proveedor, otro_proveedor, banco, active_user) -> None:
        cheque = _cheque_propio(
            db, numero="P-BENEF-MISMATCH", banco_empresa_id=banco.id, proveedor_id=otro_proveedor.id
        )
        db.flush()

        with pytest.raises(HTTPException) as exc_info:
            _pagar_con_cheque_propio(db, empresa=empresa, proveedor=proveedor, cheque=cheque, active_user=active_user)

        assert exc_info.value.status_code == 422
        detail = str(exc_info.value.detail)
        assert str(proveedor.id) in detail
        assert str(otro_proveedor.id) in detail

        db.expire_all()
        cheque_after = db.get(Cheque, cheque.id)
        assert cheque_after.proveedor_id == otro_proveedor.id
        assert cheque_after.orden_pago_id is None
        link = db.query(OrdenPagoCheque).filter(OrdenPagoCheque.cheque_id == cheque.id).one_or_none()
        assert link is None

    def test_proveedor_null_se_completa_desde_op(self, db, empresa, proveedor, banco, active_user) -> None:
        cheque = _cheque_propio(db, numero="P-BENEF-NULL", banco_empresa_id=banco.id, proveedor_id=None)
        db.flush()
        assert cheque.proveedor_id is None

        op = _pagar_con_cheque_propio(db, empresa=empresa, proveedor=proveedor, cheque=cheque, active_user=active_user)

        assert op.estado == "pagado"
        db.refresh(cheque)
        assert cheque.proveedor_id == proveedor.id

    def test_proveedor_matching_no_escribe_espurio(self, db, empresa, proveedor, banco, active_user) -> None:
        cheque = _cheque_propio(db, numero="P-BENEF-MATCH", banco_empresa_id=banco.id, proveedor_id=proveedor.id)
        db.flush()

        op = _pagar_con_cheque_propio(db, empresa=empresa, proveedor=proveedor, cheque=cheque, active_user=active_user)

        assert op.estado == "pagado"
        db.refresh(cheque)
        assert cheque.proveedor_id == proveedor.id


# ──────────────────────────────────────────────────────────────────────────
# R5 — regresión: endoso de tercero intacto
# ──────────────────────────────────────────────────────────────────────────


class TestRegresionEndosoTercero:
    def test_endoso_tercero_transicion_proveedor_link_imputacion_intactos(
        self, db, empresa, proveedor, active_user
    ) -> None:
        from app.services.pedidos_service import calcular_saldo_pendiente_pedido
        from app.models.pedido_compra import PedidoCompra

        pedido = PedidoCompra(
            id=90,
            numero="PC-90-2026-00001",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("500000"),
            tipo_cambio=None,
            estado="aprobado",
            creado_por_id=active_user.id,
        )
        db.add(pedido)
        db.flush()

        cheque = cheques_service.recibir_cheque_tercero(
            db,
            banco_nombre="Banco Nación",
            cuit_librador="20112233445",
            librador_nombre="Tercero SA",
            numero="CH-T-REGRESION",
            monto=Decimal("500000"),
            moneda="ARS",
            fecha_emision=date(2026, 6, 22),
            fecha_pago=date(2026, 7, 22),
            instrumento="fisico",
            usuario_id=active_user.id,
        )
        db.flush()
        assert cheque.estado == "en_cartera"

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
                    "pedido_id": pedido.id,
                }
            ],
        )

        assert op.estado == "pagado"
        db.refresh(cheque)
        # Transición en_cartera -> entregado fired.
        assert cheque.estado == "entregado"
        # proveedor_id overwritten unconditionally (tercero keeps this behavior).
        assert cheque.proveedor_id == proveedor.id
        # Link created.
        link = db.query(OrdenPagoCheque).filter(OrdenPagoCheque.cheque_id == cheque.id).one()
        assert link.monto_op_moneda == Decimal("500000")
        # Imputation invoked (saldo pedido = 0).
        saldo = calcular_saldo_pendiente_pedido(db, pedido.id)
        assert saldo == Decimal("0")

    def test_transiciones_cheque_no_gano_entrada_para_propio_emitido_entregar(self) -> None:
        assert ("propio", "emitido", "entregar") not in cheques_service.TRANSICIONES_CHEQUE


# ──────────────────────────────────────────────────────────────────────────
# R9 — cross-moneda
# ──────────────────────────────────────────────────────────────────────────


class TestAplicarPropioCrossMoneda:
    def test_cheque_usd_op_ars_deriva_monto(self, db, empresa, proveedor, banco, active_user) -> None:
        cheque = _cheque_propio(db, numero="P-USD-CROSS", banco_empresa_id=banco.id, moneda="USD", monto=Decimal("100"))
        db.flush()

        op = ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=Decimal("100000"),
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
            tipo_cambio=Decimal("1000"),
        )

        assert op.estado == "pagado"
        link = db.query(OrdenPagoCheque).filter(OrdenPagoCheque.cheque_id == cheque.id).one()
        assert link.monto_op_moneda == Decimal("100000")


# ──────────────────────────────────────────────────────────────────────────
# R11 — discriminador aplicado_a_op
# ──────────────────────────────────────────────────────────────────────────


class TestEventoAplicadoAOp:
    def test_evento_aplicado_a_op_con_origen_preexistente(self, db, empresa, proveedor, banco, active_user) -> None:
        cheque = _cheque_propio(db, numero="P-EVENTO", banco_empresa_id=banco.id)
        db.flush()

        op = _pagar_con_cheque_propio(db, empresa=empresa, proveedor=proveedor, cheque=cheque, active_user=active_user)

        eventos = db.query(ChequeEvento).filter(ChequeEvento.cheque_id == cheque.id).all()
        aplicados = [e for e in eventos if e.tipo == "aplicado_a_op"]
        assert len(aplicados) == 1
        assert aplicados[0].payload["orden_pago_id"] == op.id
        assert aplicados[0].payload["origen"] == "preexistente"

    def test_emitir_cheque_propio_nunca_escribe_aplicado_a_op(self, db, banco) -> None:
        cheque = _cheque_propio(db, numero="P-SIN-EVENTO", banco_empresa_id=banco.id)
        db.flush()

        eventos = db.query(ChequeEvento).filter(ChequeEvento.cheque_id == cheque.id).all()
        assert all(e.tipo != "aplicado_a_op" for e in eventos)
