"""
Tests unitarios — Slice S3b: reserva/liberación de cheques propios en OP.

TDD Strict:
  - `reservar_cheque_propio_en_op`: crea el link OrdenPagoCheque de inmediato
    contra una OP 'pendiente' SIN mover CC ni crear Imputacion (invariante R).
  - `liberar_cheque_de_op`: des-reserva sin tocar CC.
  - Merge step en `ejecutar_pago`: una OP con SOLO cheques reservados (sin
    caja_id/banco_id/cheques=) puede pagarse igual.
  - Duplicate guard: un cheque_id en el payload que YA está reservado -> 422.
  - UNIQUE constraint: doble reserva concurrente del mismo cheque -> 409
    limpio, nunca un IntegrityError crudo.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

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
    e = Empresa(id=93, nombre="EmpresaChequeReservaS3b", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=93,
        nombre="ProveedorChequeReservaS3b",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=930,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def otro_proveedor(db) -> Proveedor:
    p = Proveedor(
        id=94,
        nombre="OtroProveedorChequeReservaS3b",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=940,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def banco(db, empresa) -> BancoEmpresa:
    b = BancoEmpresa(
        id=93,
        banco="BancoChequeReservaS3b",
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
    proveedor_id: int | None = None,
    monto: Decimal = Decimal("100000"),
    moneda: str = "ARS",
) -> Cheque:
    return cheques_service.emitir_cheque_propio(
        db,
        tipo="propio",
        instrumento="echeq",
        numero=numero,
        monto=monto,
        moneda=moneda,
        fecha_emision=date(2026, 6, 22),
        fecha_pago=date(2026, 6, 22),
        banco_empresa_id=banco_empresa_id,
        proveedor_id=proveedor_id,
    )


def _op_pendiente(
    db, *, empresa_id: int, proveedor_id: int, numero: str, creado_por_id: int, monto_total=Decimal("100000")
) -> OrdenPago:
    op = OrdenPago(
        numero=numero,
        empresa_id=empresa_id,
        proveedor_id=proveedor_id,
        moneda="ARS",
        monto_total=monto_total,
        modo_imputacion="a_cuenta",
        estado="pendiente",
        creado_por_id=creado_por_id,
    )
    db.add(op)
    db.flush()
    return op


# ──────────────────────────────────────────────────────────────────────────
# reservar_cheque_propio_en_op
# ──────────────────────────────────────────────────────────────────────────


class TestReservarChequePropioEnOp:
    def test_reserva_crea_link_sin_cc_ni_imputacion(self, db, empresa, proveedor, banco, active_user) -> None:
        cheque = _cheque_propio(db, numero="P-RES-1", banco_empresa_id=banco.id)
        op = _op_pendiente(
            db, empresa_id=empresa.id, proveedor_id=proveedor.id, numero="OP-RES-1", creado_por_id=active_user.id
        )

        ordenes_pago_service.reservar_cheque_propio_en_op(
            db,
            orden_pago_id=op.id,
            cheque_id=cheque.id,
            monto=cheque.monto,
            moneda=cheque.moneda,
            user_id=active_user.id,
        )
        db.flush()
        db.expire_all()

        cheque_after = db.get(Cheque, cheque.id)
        assert cheque_after.orden_pago_id == op.id
        assert cheque_after.proveedor_id == proveedor.id
        assert cheque_after.estado == "emitido"  # unchanged — no transition

        link = db.query(OrdenPagoCheque).filter(OrdenPagoCheque.cheque_id == cheque.id).one()
        assert link.orden_pago_id == op.id

        movs = db.query(CCProveedorMovimiento).filter(CCProveedorMovimiento.proveedor_id == proveedor.id).all()
        assert movs == []
        imps = db.query(Imputacion).filter(Imputacion.origen_id == cheque.id, Imputacion.origen_tipo == "cheque").all()
        assert imps == []

        evento = (
            db.query(ChequeEvento)
            .filter(ChequeEvento.cheque_id == cheque.id, ChequeEvento.tipo == "aplicado_a_op")
            .one()
        )
        assert evento.payload["origen"] == "preexistente"
        assert evento.payload["proveedor_asignado"] is True

    def test_reserva_estado_debitado_422_nombra_estado(self, db, empresa, proveedor, banco, active_user) -> None:
        cheque = _cheque_propio(db, numero="P-RES-DEB", banco_empresa_id=banco.id)
        cheque.estado = "debitado"
        db.flush()
        op = _op_pendiente(
            db, empresa_id=empresa.id, proveedor_id=proveedor.id, numero="OP-RES-2", creado_por_id=active_user.id
        )

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.reservar_cheque_propio_en_op(
                db,
                orden_pago_id=op.id,
                cheque_id=cheque.id,
                monto=cheque.monto,
                moneda=cheque.moneda,
                user_id=active_user.id,
            )
        assert exc_info.value.status_code == 422
        assert "debitado" in str(exc_info.value.detail)

    def test_reserva_beneficiario_mismatch_422_nombra_ambos_ids(
        self, db, empresa, proveedor, otro_proveedor, banco, active_user
    ) -> None:
        cheque = _cheque_propio(db, numero="P-RES-BENEF", banco_empresa_id=banco.id, proveedor_id=otro_proveedor.id)
        op = _op_pendiente(
            db, empresa_id=empresa.id, proveedor_id=proveedor.id, numero="OP-RES-3", creado_por_id=active_user.id
        )

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.reservar_cheque_propio_en_op(
                db,
                orden_pago_id=op.id,
                cheque_id=cheque.id,
                monto=cheque.monto,
                moneda=cheque.moneda,
                user_id=active_user.id,
            )
        assert exc_info.value.status_code == 422
        detail = str(exc_info.value.detail)
        assert str(proveedor.id) in detail
        assert str(otro_proveedor.id) in detail

    def test_reserva_op_no_pendiente_409(self, db, empresa, proveedor, banco, active_user) -> None:
        cheque = _cheque_propio(db, numero="P-RES-OPNOTPEND", banco_empresa_id=banco.id)
        op = _op_pendiente(
            db, empresa_id=empresa.id, proveedor_id=proveedor.id, numero="OP-RES-4", creado_por_id=active_user.id
        )
        op.estado = "cancelado"
        db.flush()

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.reservar_cheque_propio_en_op(
                db,
                orden_pago_id=op.id,
                cheque_id=cheque.id,
                monto=cheque.monto,
                moneda=cheque.moneda,
                user_id=active_user.id,
            )
        assert exc_info.value.status_code == 409

    def test_reserva_monto_no_coincide_con_cheque_422(self, db, empresa, proveedor, banco, active_user) -> None:
        cheque = _cheque_propio(db, numero="P-RES-MONTO", banco_empresa_id=banco.id, monto=Decimal("50000"))
        op = _op_pendiente(
            db, empresa_id=empresa.id, proveedor_id=proveedor.id, numero="OP-RES-5", creado_por_id=active_user.id
        )

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.reservar_cheque_propio_en_op(
                db, orden_pago_id=op.id, cheque_id=cheque.id, monto=Decimal("1"), moneda="ARS", user_id=active_user.id
            )
        assert exc_info.value.status_code == 422

    def test_reserva_doble_del_mismo_cheque_409_no_integrity_error(
        self, db, empresa, proveedor, banco, active_user
    ) -> None:
        """R4 — the OrdenPagoCheque.cheque_id UNIQUE constraint is the guard;
        a second reservation of the same cheque must raise a clean domain
        error, never a raw IntegrityError bubbling to the caller."""
        cheque = _cheque_propio(db, numero="P-RES-DOBLE", banco_empresa_id=banco.id)
        op1 = _op_pendiente(
            db, empresa_id=empresa.id, proveedor_id=proveedor.id, numero="OP-RES-6A", creado_por_id=active_user.id
        )
        op2 = _op_pendiente(
            db, empresa_id=empresa.id, proveedor_id=proveedor.id, numero="OP-RES-6B", creado_por_id=active_user.id
        )

        ordenes_pago_service.reservar_cheque_propio_en_op(
            db,
            orden_pago_id=op1.id,
            cheque_id=cheque.id,
            monto=cheque.monto,
            moneda=cheque.moneda,
            user_id=active_user.id,
        )
        db.flush()

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.reservar_cheque_propio_en_op(
                db,
                orden_pago_id=op2.id,
                cheque_id=cheque.id,
                monto=cheque.monto,
                moneda=cheque.moneda,
                user_id=active_user.id,
            )
        assert exc_info.value.status_code == 409
        assert str(op1.id) in str(exc_info.value.detail)


# ──────────────────────────────────────────────────────────────────────────
# liberar_cheque_de_op
# ──────────────────────────────────────────────────────────────────────────


class TestLiberarChequeDeOp:
    def test_liberar_desvincula_sin_cc(self, db, empresa, proveedor, banco, active_user) -> None:
        cheque = _cheque_propio(db, numero="P-LIB-1", banco_empresa_id=banco.id)
        op = _op_pendiente(
            db, empresa_id=empresa.id, proveedor_id=proveedor.id, numero="OP-LIB-1", creado_por_id=active_user.id
        )
        ordenes_pago_service.reservar_cheque_propio_en_op(
            db,
            orden_pago_id=op.id,
            cheque_id=cheque.id,
            monto=cheque.monto,
            moneda=cheque.moneda,
            user_id=active_user.id,
        )
        db.flush()

        ordenes_pago_service.liberar_cheque_de_op(db, orden_pago_id=op.id, cheque_id=cheque.id, user_id=active_user.id)
        db.flush()
        db.expire_all()

        cheque_after = db.get(Cheque, cheque.id)
        assert cheque_after.orden_pago_id is None
        assert cheque_after.proveedor_id is None
        link = db.query(OrdenPagoCheque).filter(OrdenPagoCheque.cheque_id == cheque.id).one_or_none()
        assert link is None
        liberado = (
            db.query(ChequeEvento)
            .filter(ChequeEvento.cheque_id == cheque.id, ChequeEvento.tipo == "liberado_de_op")
            .one_or_none()
        )
        assert liberado is not None
        movs = db.query(CCProveedorMovimiento).filter(CCProveedorMovimiento.proveedor_id == proveedor.id).all()
        assert movs == []

    def test_liberar_conserva_proveedor_si_no_fue_auto_asignado(
        self, db, empresa, proveedor, banco, active_user
    ) -> None:
        cheque = _cheque_propio(db, numero="P-LIB-2", banco_empresa_id=banco.id, proveedor_id=proveedor.id)
        op = _op_pendiente(
            db, empresa_id=empresa.id, proveedor_id=proveedor.id, numero="OP-LIB-2", creado_por_id=active_user.id
        )
        ordenes_pago_service.reservar_cheque_propio_en_op(
            db,
            orden_pago_id=op.id,
            cheque_id=cheque.id,
            monto=cheque.monto,
            moneda=cheque.moneda,
            user_id=active_user.id,
        )
        db.flush()

        ordenes_pago_service.liberar_cheque_de_op(db, orden_pago_id=op.id, cheque_id=cheque.id, user_id=active_user.id)
        db.flush()
        db.expire_all()

        cheque_after = db.get(Cheque, cheque.id)
        assert cheque_after.orden_pago_id is None
        assert cheque_after.proveedor_id == proveedor.id

    def test_liberar_op_no_pendiente_409(self, db, empresa, proveedor, banco, active_user) -> None:
        cheque = _cheque_propio(db, numero="P-LIB-3", banco_empresa_id=banco.id)
        op = _op_pendiente(
            db, empresa_id=empresa.id, proveedor_id=proveedor.id, numero="OP-LIB-3", creado_por_id=active_user.id
        )
        ordenes_pago_service.reservar_cheque_propio_en_op(
            db,
            orden_pago_id=op.id,
            cheque_id=cheque.id,
            monto=cheque.monto,
            moneda=cheque.moneda,
            user_id=active_user.id,
        )
        db.flush()
        op.estado = "pagado"
        db.flush()

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.liberar_cheque_de_op(
                db, orden_pago_id=op.id, cheque_id=cheque.id, user_id=active_user.id
            )
        assert exc_info.value.status_code == 409

    def test_liberar_cheque_no_reservado_en_esta_op_409(self, db, empresa, proveedor, banco, active_user) -> None:
        cheque = _cheque_propio(db, numero="P-LIB-4", banco_empresa_id=banco.id)
        op = _op_pendiente(
            db, empresa_id=empresa.id, proveedor_id=proveedor.id, numero="OP-LIB-4", creado_por_id=active_user.id
        )

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.liberar_cheque_de_op(
                db, orden_pago_id=op.id, cheque_id=cheque.id, user_id=active_user.id
            )
        assert exc_info.value.status_code == 409


# ──────────────────────────────────────────────────────────────────────────
# Merge step en ejecutar_pago — OP pagada solo con cheques reservados
# ──────────────────────────────────────────────────────────────────────────


class TestMergeStepEjecutarPago:
    def test_op_paga_solo_con_cheque_reservado_sin_fuente(self, db, empresa, proveedor, banco, active_user) -> None:
        cheque = _cheque_propio(db, numero="P-MERGE-1", banco_empresa_id=banco.id, monto=Decimal("75000"))
        op = _op_pendiente(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero="OP-MERGE-1",
            creado_por_id=active_user.id,
            monto_total=Decimal("75000"),
        )
        ordenes_pago_service.reservar_cheque_propio_en_op(
            db,
            orden_pago_id=op.id,
            cheque_id=cheque.id,
            monto=cheque.monto,
            moneda=cheque.moneda,
            user_id=active_user.id,
        )
        db.flush()

        result = ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=None,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 25),
            user_id=active_user.id,
            cheques=None,
        )

        assert result.estado == "pagado"
        db.expire_all()
        link = db.query(OrdenPagoCheque).filter(OrdenPagoCheque.cheque_id == cheque.id).one()
        assert link.orden_pago_id == op.id
        assert Decimal(link.monto_op_moneda) == Decimal("75000")

        movs = db.query(CCProveedorMovimiento).filter(CCProveedorMovimiento.proveedor_id == proveedor.id).all()
        assert len(movs) >= 1

    def test_duplicado_en_payload_de_cheque_ya_reservado_422(self, db, empresa, proveedor, banco, active_user) -> None:
        cheque = _cheque_propio(db, numero="P-MERGE-DUP", banco_empresa_id=banco.id, monto=Decimal("30000"))
        op = _op_pendiente(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero="OP-MERGE-2",
            creado_por_id=active_user.id,
            monto_total=Decimal("30000"),
        )
        ordenes_pago_service.reservar_cheque_propio_en_op(
            db,
            orden_pago_id=op.id,
            cheque_id=cheque.id,
            monto=cheque.monto,
            moneda=cheque.moneda,
            user_id=active_user.id,
        )
        db.flush()

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.ejecutar_pago(
                db,
                orden_pago_id=op.id,
                caja_id=None,
                banco_id=None,
                fecha_pago_real=date(2026, 6, 25),
                user_id=active_user.id,
                cheques=[{"cheque_id": cheque.id, "monto": cheque.monto, "moneda": cheque.moneda}],
            )
        assert exc_info.value.status_code == 422
        assert str(cheque.id) in str(exc_info.value.detail)

    def test_cheque_reservado_debitado_por_banco_antes_de_pagar_422(
        self, db, empresa, proveedor, banco, active_user
    ) -> None:
        """The bank may debit the reserved cheque while the OP still sits
        'pendiente' — ejecutar_pago must re-validate estado, not blindly
        trust the reservation."""
        cheque = _cheque_propio(db, numero="P-MERGE-DEBITADO", banco_empresa_id=banco.id, monto=Decimal("40000"))
        op = _op_pendiente(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero="OP-MERGE-3",
            creado_por_id=active_user.id,
            monto_total=Decimal("40000"),
        )
        ordenes_pago_service.reservar_cheque_propio_en_op(
            db,
            orden_pago_id=op.id,
            cheque_id=cheque.id,
            monto=cheque.monto,
            moneda=cheque.moneda,
            user_id=active_user.id,
        )
        db.flush()
        cheque.estado = "debitado"
        db.flush()

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.ejecutar_pago(
                db,
                orden_pago_id=op.id,
                caja_id=None,
                banco_id=None,
                fecha_pago_real=date(2026, 6, 25),
                user_id=active_user.id,
                cheques=None,
            )
        assert exc_info.value.status_code == 422
        assert "debitado" in str(exc_info.value.detail)

    def test_anular_op_pagada_con_cheque_reservado_libera_no_anula(
        self, db, empresa, proveedor, banco, active_user
    ) -> None:
        """Full loop: reservar (pendiente) -> pagar (merge step) -> anular
        must RELEASE the cheque (ADR-5), not anular it — the instrument
        pre-existed the OP."""
        cheque = _cheque_propio(db, numero="P-MERGE-ANUL", banco_empresa_id=banco.id, monto=Decimal("60000"))
        op = _op_pendiente(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero="OP-MERGE-4",
            creado_por_id=active_user.id,
            monto_total=Decimal("60000"),
        )
        ordenes_pago_service.reservar_cheque_propio_en_op(
            db,
            orden_pago_id=op.id,
            cheque_id=cheque.id,
            monto=cheque.monto,
            moneda=cheque.moneda,
            user_id=active_user.id,
        )
        db.flush()
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=None,
            banco_id=None,
            fecha_pago_real=date(2026, 6, 25),
            user_id=active_user.id,
            cheques=None,
        )

        ordenes_pago_service.anular(
            db, orden_pago_id=op.id, motivo="Test S3b full loop anulación", user_id=active_user.id
        )

        db.expire_all()
        cheque_after = db.get(Cheque, cheque.id)
        assert cheque_after.estado != "anulado"
        assert cheque_after.orden_pago_id is None
        link = db.query(OrdenPagoCheque).filter(OrdenPagoCheque.cheque_id == cheque.id).one_or_none()
        assert link is None

        # CC movement created at pay time must be reversed.
        movs = db.query(CCProveedorMovimiento).filter(CCProveedorMovimiento.proveedor_id == proveedor.id).all()
        haberes = [m for m in movs if str(m.tipo) == "haber"]
        debes = [m for m in movs if str(m.tipo) == "debe"]
        assert len(haberes) >= 1
        assert len(debes) >= 1
