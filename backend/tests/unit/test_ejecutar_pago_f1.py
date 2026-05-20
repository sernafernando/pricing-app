"""
T1.23–T1.30 — Tests for ejecutar_pago F1 behavior.

Verifies that after ejecutar_pago:
- Caso A: pedido.tipo_cambio is updated to the weighted average.
- Caso B: pedido.tipo_cambio is NOT changed.
- Consistency invariant: pedido.tipo_cambio == resolver_tc_efectivo_pedido(session, pedido).
- tipo_cambio_original is immutable after first payment.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.caja import Caja, CajaTipoDocumento
from app.models.empresa import Empresa
from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.tipo_cambio import TipoCambio
from app.services import ordenes_pago_service, pedidos_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(nombre="Empresa EP F1", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(nombre="Prov EP F1", activo=True, origen=OrigenProveedor.ERP.value, supp_id=99)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def caja_ars(db, empresa) -> Caja:
    caja = Caja(
        nombre="Caja ARS EP",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("5000000"),
        saldo_actual=Decimal("5000000"),
        activo=True,
    )
    db.add(caja)
    db.flush()
    return caja


@pytest.fixture
def tipos_doc_caja(db) -> None:
    td = CajaTipoDocumento(nombre="Orden de Pago", descripcion="OP", activo=True)
    db.add(td)
    db.flush()


@pytest.fixture
def tipo_cambio_usd(db) -> None:
    tc = TipoCambio(fecha=date(2026, 1, 1), moneda="USD", compra=Decimal("1400"), venta=Decimal("1410"))
    db.add(tc)
    db.flush()


def _make_pedido_usd(
    db,
    empresa,
    proveedor,
    user_id: int,
    monto: Decimal = Decimal("1000"),
    tc_original: Decimal = Decimal("1400"),
) -> PedidoCompra:
    """Create an approved USD pedido."""
    n = db.query(PedidoCompra).count() + 1
    pedido = PedidoCompra(
        numero=f"PC-F1-{n:04d}",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="USD",
        monto=monto,
        tipo_cambio=tc_original,
        tipo_cambio_original=tc_original,
        estado="aprobado",
        creado_por_id=user_id,
    )
    db.add(pedido)
    db.flush()
    return pedido


def _make_op_pendiente(
    db,
    empresa,
    proveedor,
    caja,
    user_id: int,
    tc: Decimal,
    actualizar_tc: bool,
    monto_ars: Decimal,
    pedido: PedidoCompra,
) -> OrdenPago:
    """Create a 'pendiente' ARS OP with one item targeting the given pedido."""
    op = ordenes_pago_service.crear(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto_total=monto_ars,
        tipo_cambio=tc,
        modo_imputacion="especifica",
        items=[{"tipo": "pedido_compra", "id": pedido.id, "monto": Decimal(str(monto_ars))}],
        creado_por_id=user_id,
        actualizar_tc_pedido=actualizar_tc,
    )
    return op


# ──────────────────────────────────────────────────────────────────────────
# T1.23 — Caso A updates pedido.tipo_cambio
# ──────────────────────────────────────────────────────────────────────────


class TestEjecutarPagoF1:
    def test_caso_a_updates_pedido_tipo_cambio(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user
    ) -> None:
        """T1.23 — after Caso-A payment, pedido.tipo_cambio = weighted average of Caso-A imps."""
        uid = active_user.id
        # Pedido USD 1000, TC original 1400.
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, monto=Decimal("1000"), tc_original=Decimal("1400"))
        assert pedido.tipo_cambio == Decimal("1400")

        # ARS OP at TC 1450, Caso A, paying USD 600 = ARS 870000
        op = _make_op_pendiente(
            db,
            empresa,
            proveedor,
            caja_ars,
            uid,
            tc=Decimal("1450"),
            actualizar_tc=True,
            monto_ars=Decimal("870000"),
            pedido=pedido,
        )

        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date(2026, 5, 20),
            user_id=uid,
        )
        db.flush()

        db.refresh(pedido)
        # After Caso-A payment TC 1450, effective TC = 1450
        assert pedido.tipo_cambio == Decimal("1450.0000")

    def test_caso_b_does_not_change_tipo_cambio(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user
    ) -> None:
        """T1.24 — after Caso-B payment, pedido.tipo_cambio unchanged."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, monto=Decimal("1000"), tc_original=Decimal("1400"))

        op = _make_op_pendiente(
            db,
            empresa,
            proveedor,
            caja_ars,
            uid,
            tc=Decimal("1450"),
            actualizar_tc=False,  # Caso B
            monto_ars=Decimal("870000"),
            pedido=pedido,
        )

        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date(2026, 5, 20),
            user_id=uid,
        )
        db.flush()

        db.refresh(pedido)
        # Caso B: TC should stay at original 1400
        assert pedido.tipo_cambio == Decimal("1400")

    def test_consistency_invariant_caso_a(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user
    ) -> None:
        """T1.25 — after Caso-A payment, pedido.tipo_cambio == resolver_tc_efectivo_pedido."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, monto=Decimal("1000"), tc_original=Decimal("1400"))

        op = _make_op_pendiente(
            db,
            empresa,
            proveedor,
            caja_ars,
            uid,
            tc=Decimal("1450"),
            actualizar_tc=True,
            monto_ars=Decimal("870000"),
            pedido=pedido,
        )
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date(2026, 5, 20),
            user_id=uid,
        )
        db.flush()
        db.refresh(pedido)

        tc_resolver = pedidos_service.resolver_tc_efectivo_pedido(db, pedido)
        assert pedido.tipo_cambio == tc_resolver

    def test_consistency_invariant_caso_b(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user
    ) -> None:
        """T1.26 — after Caso-B payment, invariant still holds."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, monto=Decimal("1000"), tc_original=Decimal("1400"))

        op = _make_op_pendiente(
            db,
            empresa,
            proveedor,
            caja_ars,
            uid,
            tc=Decimal("1450"),
            actualizar_tc=False,
            monto_ars=Decimal("870000"),
            pedido=pedido,
        )
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date(2026, 5, 20),
            user_id=uid,
        )
        db.flush()
        db.refresh(pedido)

        tc_resolver = pedidos_service.resolver_tc_efectivo_pedido(db, pedido)
        assert pedido.tipo_cambio == tc_resolver

    def test_tipo_cambio_original_immutable_after_approval(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user
    ) -> None:
        """T1.27 — a second payment cannot overwrite tipo_cambio_original."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, monto=Decimal("1000"), tc_original=Decimal("1400"))
        original_tc_original = Decimal("1400")

        # First Caso-A payment
        op1 = _make_op_pendiente(
            db,
            empresa,
            proveedor,
            caja_ars,
            uid,
            tc=Decimal("1450"),
            actualizar_tc=True,
            monto_ars=Decimal("870000"),
            pedido=pedido,
        )
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op1.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date(2026, 5, 20),
            user_id=uid,
        )
        db.flush()
        db.refresh(pedido)
        assert pedido.tipo_cambio_original == original_tc_original

        # Second Caso-A payment
        op2 = _make_op_pendiente(
            db,
            empresa,
            proveedor,
            caja_ars,
            uid,
            tc=Decimal("1430"),
            actualizar_tc=True,
            monto_ars=Decimal("572000"),
            pedido=pedido,
        )
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op2.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date(2026, 5, 21),
            user_id=uid,
        )
        db.flush()
        db.refresh(pedido)

        # tipo_cambio_original must still be 1400 (immutable)
        assert pedido.tipo_cambio_original == original_tc_original
        # tipo_cambio should be the new weighted average
        # (600/870000*1450 + 400/572000*1430) ... let resolver verify
        assert pedido.tipo_cambio == pedidos_service.resolver_tc_efectivo_pedido(db, pedido)


# ──────────────────────────────────────────────────────────────────────────
# W4 — CC adjustment + pedido TC cache write must be ATOMIC
# ──────────────────────────────────────────────────────────────────────────


class TestEjecutarPagoF1AjusteAtomico:
    """W4 — if the CC re-valuation adjustment fails, the pedido.tipo_cambio
    cache must NOT be written and the error MUST propagate. The pedido cache
    and the CC ledger must never silently diverge."""

    def test_ajuste_falla_no_escribe_cache_y_propaga(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user, monkeypatch
    ) -> None:
        """W4 — when registrar_ajuste_revaluacion_tc raises, ejecutar_pago must
        propagate the error and leave pedido.tipo_cambio unchanged (no silent
        divergence between the pedido cache and the CC ledger)."""
        uid = active_user.id
        pedido = _make_pedido_usd(db, empresa, proveedor, uid, monto=Decimal("1000"), tc_original=Decimal("1400"))
        assert pedido.tipo_cambio == Decimal("1400")

        op = _make_op_pendiente(
            db,
            empresa,
            proveedor,
            caja_ars,
            uid,
            tc=Decimal("1450"),
            actualizar_tc=True,  # Caso A → TC drifts → adjustment is emitted
            monto_ars=Decimal("870000"),
            pedido=pedido,
        )

        # Make the CC re-valuation adjustment fail with a realistic error
        # (insertar_mov raises HTTPException on validation failure).
        from fastapi import HTTPException

        from app.services import cc_proveedor_service

        def _boom(*args, **kwargs):
            raise HTTPException(status_code=400, detail="CC adjustment forced failure")

        monkeypatch.setattr(cc_proveedor_service, "registrar_ajuste_revaluacion_tc", _boom)

        # The error must propagate — ejecutar_pago must NOT swallow it.
        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.ejecutar_pago(
                db,
                orden_pago_id=op.id,
                caja_id=caja_ars.id,
                fecha_pago_real=date(2026, 5, 20),
                user_id=uid,
            )
        assert exc_info.value.detail == "CC adjustment forced failure"

        # The pedido TC cache must NOT have been written — it stays at the
        # original value, so the cache and the (failed) CC ledger do not diverge.
        assert pedido.tipo_cambio == Decimal("1400")
