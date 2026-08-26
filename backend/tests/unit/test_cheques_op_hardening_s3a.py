"""
Tests unitarios — Slice S3a: OP↔cheque hardening.

TDD Strict:
  - FIX 1: `_revertir_cc_si_linkeado` must NOT invent CC money for a cheque
    linked to a non-`pagado` OP (guard by op.estado, not just orden_pago_id).
  - FIX 2 (ADR-5): anulling an OP that used a PRE-EXISTING applied propio
    must RELEASE that cheque (unlink, keep valid), not `anular` it.
  - FIX 3: `cancelar_pendiente` must release any linked cheque (no CC ever
    existed for a `pendiente` OP) and its docstring must state that truth.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.banco_empresa import BancoEmpresa
from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.cheque import Cheque, ChequeEvento, OrdenPagoCheque
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.orden_pago import OrdenPago
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import cheques_service, ordenes_pago_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=92, nombre="EmpresaChequeHardeningS3a", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=92,
        nombre="ProveedorChequeHardeningS3a",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=920,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def banco(db, empresa) -> BancoEmpresa:
    b = BancoEmpresa(
        id=92,
        banco="BancoChequeHardeningS3a",
        moneda="ARS",
        empresa_id=empresa.id,
        activo=True,
    )
    db.add(b)
    db.flush()
    return b


def _cheque_propio(db, *, numero: str, banco_empresa_id: int, proveedor_id: int | None = None) -> Cheque:
    return cheques_service.emitir_cheque_propio(
        db,
        tipo="propio",
        instrumento="echeq",
        numero=numero,
        monto=Decimal("500000"),
        moneda="ARS",
        fecha_emision=date(2026, 6, 22),
        fecha_pago=date(2026, 6, 22),
        banco_empresa_id=banco_empresa_id,
        proveedor_id=proveedor_id,
    )


def _op_manual(db, *, empresa_id: int, proveedor_id: int, estado: str, numero: str, creado_por_id: int) -> OrdenPago:
    """Constructs an OP directly (bypassing crear/ejecutar_pago) for hardening
    tests that need a specific pre-reservation-like state that S3b's real
    reservation flow does not yet produce."""
    op = OrdenPago(
        numero=numero,
        empresa_id=empresa_id,
        proveedor_id=proveedor_id,
        moneda="ARS",
        monto_total=Decimal("500000"),
        modo_imputacion="a_cuenta",
        estado=estado,
        creado_por_id=creado_por_id,
    )
    db.add(op)
    db.flush()
    return op


def _linkear_cheque_a_op(db, *, cheque: Cheque, op: OrdenPago) -> OrdenPagoCheque:
    cheque.orden_pago_id = op.id
    link = OrdenPagoCheque(orden_pago_id=op.id, cheque_id=cheque.id, monto_op_moneda=cheque.monto)
    db.add(link)
    db.flush()
    return link


# ──────────────────────────────────────────────────────────────────────────
# FIX 1 — _revertir_cc_si_linkeado must not invent money for a non-pagado OP
# ──────────────────────────────────────────────────────────────────────────


class TestRevertirCCGuardaEstadoOP:
    def test_anular_cheque_linkeado_a_op_no_pagada_no_crea_movimiento_cc(
        self, db, empresa, proveedor, banco, active_user
    ) -> None:
        """A cheque manually linked to a `pendiente` OP (simulating a reserved
        cheque before S3b exists) must NOT produce any CC movement or reversal
        Imputacion when anulled — no money was ever credited for it."""
        cheque = _cheque_propio(db, numero="P-GUARD-PENDIENTE", banco_empresa_id=banco.id, proveedor_id=proveedor.id)
        db.flush()
        op = _op_manual(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            estado="pendiente",
            numero="OP-GUARD-1",
            creado_por_id=active_user.id,
        )
        _linkear_cheque_a_op(db, cheque=cheque, op=op)

        cheques_service.transicionar_cheque(db, cheque, "anular", usuario_id=active_user.id)

        movs = db.query(CCProveedorMovimiento).filter(CCProveedorMovimiento.proveedor_id == proveedor.id).all()
        assert movs == [], f"Esperaba cero movimientos CC, got {len(movs)}"

        reversals = (
            db.query(Imputacion)
            .filter(
                Imputacion.origen_tipo == "cheque",
                Imputacion.origen_id == cheque.id,
                Imputacion.es_reversal.is_(True),
            )
            .all()
        )
        assert reversals == [], f"Esperaba cero reversals, got {len(reversals)}"

        db.refresh(cheque)
        assert cheque.estado == "anulado"


# ──────────────────────────────────────────────────────────────────────────
# FIX 2 (ADR-5) — anular OP releases a pre-existing applied propio
# ──────────────────────────────────────────────────────────────────────────


class TestAnularOPADR5:
    def test_anular_op_con_propio_preexistente_libera_no_anula(
        self, db, empresa, proveedor, banco, active_user
    ) -> None:
        cheque = _cheque_propio(db, numero="P-ADR5-PREEXISTENTE", banco_empresa_id=banco.id)
        db.flush()
        assert cheque.estado == "emitido"

        op = ordenes_pago_service.crear_y_pagar(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            moneda="ARS",
            monto_total=cheque.monto,
            modo_imputacion="a_cuenta",
            items=[],
            caja_id=None,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 22),
            creado_por_id=active_user.id,
            cheques=[{"cheque_id": cheque.id, "monto": cheque.monto, "moneda": cheque.moneda}],
        )
        db.refresh(cheque)
        assert cheque.orden_pago_id == op.id

        ordenes_pago_service.anular(db, orden_pago_id=op.id, motivo="Test ADR-5 release", user_id=active_user.id)

        db.expire_all()
        cheque_after = db.get(Cheque, cheque.id)
        assert cheque_after.estado != "anulado", "El cheque preexistente NO debe quedar 'anulado'"
        assert cheque_after.orden_pago_id is None
        link = db.query(OrdenPagoCheque).filter(OrdenPagoCheque.cheque_id == cheque.id).one_or_none()
        assert link is None

        liberado = (
            db.query(ChequeEvento)
            .filter(ChequeEvento.cheque_id == cheque.id, ChequeEvento.tipo == "liberado_de_op")
            .one_or_none()
        )
        assert liberado is not None


# ──────────────────────────────────────────────────────────────────────────
# FIX 3 — cancelar_pendiente releases linked cheques, zero CC
# ──────────────────────────────────────────────────────────────────────────


class TestCancelarPendienteLiberaCheques:
    def test_cancelar_pendiente_con_cheque_linkeado_lo_libera_sin_cc(
        self, db, empresa, proveedor, banco, active_user
    ) -> None:
        cheque = _cheque_propio(db, numero="P-CANCEL-RELEASE", banco_empresa_id=banco.id, proveedor_id=None)
        db.flush()
        op = _op_manual(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            estado="pendiente",
            numero="OP-CANCEL-1",
            creado_por_id=active_user.id,
        )
        cheque.proveedor_id = proveedor.id
        db.flush()
        _linkear_cheque_a_op(db, cheque=cheque, op=op)
        cheques_service.registrar_evento(
            db,
            cheque_id=cheque.id,
            tipo="aplicado_a_op",
            payload={"orden_pago_id": op.id, "origen": "preexistente", "proveedor_asignado": True},
            usuario_id=active_user.id,
        )
        db.flush()

        ordenes_pago_service.cancelar_pendiente(
            db, op_id=op.id, motivo="Test release en cancelar_pendiente", user_id=active_user.id
        )

        db.expire_all()
        cheque_after = db.get(Cheque, cheque.id)
        assert cheque_after.orden_pago_id is None
        assert cheque_after.proveedor_id is None, "proveedor_id auto-asignado debe limpiarse en la liberación"
        link = db.query(OrdenPagoCheque).filter(OrdenPagoCheque.cheque_id == cheque.id).one_or_none()
        assert link is None

        movs = db.query(CCProveedorMovimiento).filter(CCProveedorMovimiento.proveedor_id == proveedor.id).all()
        assert movs == [], f"Esperaba cero movimientos CC en cancelar_pendiente, got {len(movs)}"

        liberado = (
            db.query(ChequeEvento)
            .filter(ChequeEvento.cheque_id == cheque.id, ChequeEvento.tipo == "liberado_de_op")
            .one_or_none()
        )
        assert liberado is not None
