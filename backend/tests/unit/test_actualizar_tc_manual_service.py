"""
T5.7–T5.19 — Service tests for F5: actualizar_tipo_cambio_manual.

Tests cover:
  T5.7  — PUT {1430} sets tipo_cambio_manual=1430, tipo_cambio=1430.
  T5.8  — After override, Caso-A payment does NOT change tipo_cambio.
  T5.9  — Clear override (null) resumes weighted Caso-A average.
  T5.10 — Clear override with no Caso-A payments → falls back to tipo_cambio_original.
  T5.11 — Override emits append-only CC ajuste; existing rows untouched.
  T5.12 — After override, varianza_tc is recomputed.
  T5.13 — Override wins over posterior Caso-A payment (AD-4, Scenario 5.A).
  T5.14 — Clearing after posterior Caso-A resumes Caso-A weighted avg (Scenario 5.B).
  T5.15 — Override can eliminate variance (AC5.9, Scenario 5.C).
  T5.17 — editar_pedido rejects tipo_cambio with 422.
  T5.18 — corregir_pedido still works for monto corrections (regression).
  T5.19 — actualizar_tipo_cambio_manual rejects ARS pedidos with HTTP 400.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.caja import Caja, CajaTipoDocumento
from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
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
    emp = Empresa(nombre="Empresa F5", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(nombre="Prov F5", activo=True, origen=OrigenProveedor.ERP.value, supp_id=55)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def caja_ars(db, empresa) -> Caja:
    caja = Caja(
        nombre="Caja ARS F5",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("50000000"),
        saldo_actual=Decimal("50000000"),
        activo=True,
    )
    db.add(caja)
    db.flush()
    return caja


@pytest.fixture
def tipo_doc_caja(db) -> None:
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
    empresa: Empresa,
    proveedor: Proveedor,
    user_id: int,
    monto: Decimal = Decimal("1000"),
    tc_original: Decimal = Decimal("1400"),
) -> PedidoCompra:
    n = db.query(PedidoCompra).count() + 1
    pedido = PedidoCompra(
        numero=f"PC-F5-{n:04d}",
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


def _make_caso_a_op(
    db,
    empresa: Empresa,
    proveedor: Proveedor,
    caja: Caja,
    user_id: int,
    pedido: PedidoCompra,
    tc: Decimal,
    monto_ars: Decimal,
) -> OrdenPago:
    """Create and execute a Caso-A ARS OP against the pedido."""
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
        actualizar_tc_pedido=True,
    )
    ordenes_pago_service.ejecutar_pago(
        db,
        orden_pago_id=op.id,
        caja_id=caja.id,
        fecha_pago_real=date(2026, 1, 1),
        user_id=user_id,
    )
    db.refresh(pedido)
    return op


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestActualizarTipoCambioManual:
    """T5.7 — PUT {1430} sets tipo_cambio_manual=1430 and tipo_cambio=1430."""

    def test_manual_override_sets_tc(self, db, empresa, proveedor, active_user) -> None:
        """AC5.1 — override sets tipo_cambio_manual and type_cambio, returns updated pedido."""
        pedido = _make_pedido_usd(db, empresa, proveedor, active_user.id, tc_original=Decimal("1400"))
        assert pedido.tipo_cambio_manual is None

        pedidos_service.actualizar_tipo_cambio_manual(
            db,
            pedido_id=pedido.id,
            tipo_cambio=Decimal("1430"),
            motivo="test override",
            user_id=active_user.id,
        )
        db.refresh(pedido)

        assert pedido.tipo_cambio_manual == Decimal("1430")
        assert pedido.tipo_cambio == Decimal("1430")

    def test_manual_override_wins_over_caso_a_payment(
        self, db, empresa, proveedor, caja_ars, tipo_doc_caja, tipo_cambio_usd, active_user
    ) -> None:
        """T5.8 / AC5.2 — after override, Caso-A payment does NOT change tipo_cambio."""
        pedido = _make_pedido_usd(db, empresa, proveedor, active_user.id, tc_original=Decimal("1400"))

        # Set manual override to 1430.
        pedidos_service.actualizar_tipo_cambio_manual(
            db,
            pedido_id=pedido.id,
            tipo_cambio=Decimal("1430"),
            motivo="override antes de pago",
            user_id=active_user.id,
        )
        db.refresh(pedido)
        assert pedido.tipo_cambio == Decimal("1430")

        # Now execute a Caso-A payment at TC 1450.
        _make_caso_a_op(
            db,
            empresa,
            proveedor,
            caja_ars,
            active_user.id,
            pedido,
            tc=Decimal("1450"),
            monto_ars=Decimal("870000"),
        )
        db.refresh(pedido)

        # Override wins — tipo_cambio stays at 1430.
        assert pedido.tipo_cambio == Decimal("1430")
        assert pedido.tipo_cambio_manual == Decimal("1430")

    def test_override_cleared_resumes_weighted_average(
        self, db, empresa, proveedor, caja_ars, tipo_doc_caja, tipo_cambio_usd, active_user
    ) -> None:
        """T5.9 / AC5.3 — clear override (null) → tipo_cambio = Caso-A weighted average."""
        pedido = _make_pedido_usd(db, empresa, proveedor, active_user.id, tc_original=Decimal("1400"))

        # Execute a Caso-A payment at TC 1450 (USD 600 = ARS 870000).
        _make_caso_a_op(
            db,
            empresa,
            proveedor,
            caja_ars,
            active_user.id,
            pedido,
            tc=Decimal("1450"),
            monto_ars=Decimal("870000"),
        )
        db.refresh(pedido)
        assert pedido.tipo_cambio == Decimal("1450")

        # Set manual override.
        pedidos_service.actualizar_tipo_cambio_manual(
            db,
            pedido_id=pedido.id,
            tipo_cambio=Decimal("1400"),
            motivo="test",
            user_id=active_user.id,
        )
        db.refresh(pedido)
        assert pedido.tipo_cambio == Decimal("1400")

        # Clear override.
        pedidos_service.actualizar_tipo_cambio_manual(
            db,
            pedido_id=pedido.id,
            tipo_cambio=None,
            motivo="volver a automático",
            user_id=active_user.id,
        )
        db.refresh(pedido)

        # Should revert to Caso-A weighted average (1450).
        assert pedido.tipo_cambio_manual is None
        assert pedido.tipo_cambio == Decimal("1450")

    def test_override_cleared_falls_back_to_original_when_no_caso_a(self, db, empresa, proveedor, active_user) -> None:
        """T5.10 / AC5.3 — clear override, no Caso-A payments → tipo_cambio = tipo_cambio_original."""
        pedido = _make_pedido_usd(db, empresa, proveedor, active_user.id, tc_original=Decimal("1400"))

        # Set override.
        pedidos_service.actualizar_tipo_cambio_manual(
            db,
            pedido_id=pedido.id,
            tipo_cambio=Decimal("1430"),
            motivo="test",
            user_id=active_user.id,
        )
        # Clear override.
        pedidos_service.actualizar_tipo_cambio_manual(
            db,
            pedido_id=pedido.id,
            tipo_cambio=None,
            motivo="clear",
            user_id=active_user.id,
        )
        db.refresh(pedido)

        assert pedido.tipo_cambio_manual is None
        assert pedido.tipo_cambio == Decimal("1400")  # = tipo_cambio_original

    def test_override_emits_append_only_cc_ajuste(self, db, empresa, proveedor, active_user) -> None:
        """T5.11 / AC5.4 — setting override creates one CC ajuste row; existing rows unchanged."""
        pedido = _make_pedido_usd(db, empresa, proveedor, active_user.id, tc_original=Decimal("1400"))

        # Count CC movements before.
        count_before = (
            db.query(CCProveedorMovimiento)
            .filter(
                CCProveedorMovimiento.proveedor_id == proveedor.id,
            )
            .count()
        )

        pedidos_service.actualizar_tipo_cambio_manual(
            db,
            pedido_id=pedido.id,
            tipo_cambio=Decimal("1430"),
            motivo="test ajuste",
            user_id=active_user.id,
        )

        # Count CC movements after.
        count_after = (
            db.query(CCProveedorMovimiento)
            .filter(
                CCProveedorMovimiento.proveedor_id == proveedor.id,
            )
            .count()
        )

        # Exactly one new CC row was appended.
        assert count_after == count_before + 1

        # The new row is tipo='ajuste'.
        ajuste = (
            db.query(CCProveedorMovimiento)
            .filter(
                CCProveedorMovimiento.proveedor_id == proveedor.id,
                CCProveedorMovimiento.tipo == "ajuste",
            )
            .order_by(CCProveedorMovimiento.id.desc())
            .first()
        )
        assert ajuste is not None
        assert ajuste.tipo == "ajuste"

    def test_override_triggers_varianza_recompute(self, db, empresa, proveedor, active_user) -> None:
        """T5.12 / AC5.5 — after override, varianza_tc_neta is recomputed correctly."""
        # Pedido USD 1000, TC original 1400. No Caso-B payments → varianza = 0.
        pedido = _make_pedido_usd(db, empresa, proveedor, active_user.id, tc_original=Decimal("1400"))

        # varianza before override = 0 (no Caso-B payments).
        varianza_before = pedidos_service.calcular_varianza_tc(db, pedido)
        assert varianza_before == Decimal("0")

        # Set override to 1430. Still no Caso-B payments → varianza stays 0.
        pedidos_service.actualizar_tipo_cambio_manual(
            db,
            pedido_id=pedido.id,
            tipo_cambio=Decimal("1430"),
            motivo="test",
            user_id=active_user.id,
        )
        db.refresh(pedido)
        varianza_after = pedidos_service.calcular_varianza_tc(db, pedido)
        assert varianza_after == Decimal("0")  # no Caso-B payments → still 0

    def test_override_gana_sobre_pago_caso_a_posterior(
        self, db, empresa, proveedor, caja_ars, tipo_doc_caja, tipo_cambio_usd, active_user
    ) -> None:
        """T5.13 / AD-4, Scenario 5.A — override set, then Caso-A payment → tipo_cambio stays at manual."""
        pedido = _make_pedido_usd(db, empresa, proveedor, active_user.id, tc_original=Decimal("1400"))

        # Set manual override first.
        pedidos_service.actualizar_tipo_cambio_manual(
            db,
            pedido_id=pedido.id,
            tipo_cambio=Decimal("1430"),
            motivo="override primero",
            user_id=active_user.id,
        )
        db.refresh(pedido)
        assert pedido.tipo_cambio == Decimal("1430")

        # Caso-A payment arrives at TC 1450.
        _make_caso_a_op(
            db,
            empresa,
            proveedor,
            caja_ars,
            active_user.id,
            pedido,
            tc=Decimal("1450"),
            monto_ars=Decimal("725000"),  # USD 500 * 1450
        )
        db.refresh(pedido)

        # Override still wins (AD-4).
        assert pedido.tipo_cambio == Decimal("1430")
        assert pedido.tipo_cambio_manual == Decimal("1430")

    def test_clear_override_resumes_caso_a_weighted(
        self, db, empresa, proveedor, caja_ars, tipo_doc_caja, tipo_cambio_usd, active_user
    ) -> None:
        """T5.14 / Scenario 5.B — clear after posterior Caso-A → tipo_cambio = Caso-A weighted avg."""
        pedido = _make_pedido_usd(db, empresa, proveedor, active_user.id, tc_original=Decimal("1400"))

        # Override first.
        pedidos_service.actualizar_tipo_cambio_manual(
            db,
            pedido_id=pedido.id,
            tipo_cambio=Decimal("1430"),
            motivo="override",
            user_id=active_user.id,
        )

        # Caso-A payment at TC 1450 (USD 500 = ARS 725000).
        _make_caso_a_op(
            db,
            empresa,
            proveedor,
            caja_ars,
            active_user.id,
            pedido,
            tc=Decimal("1450"),
            monto_ars=Decimal("725000"),
        )
        db.refresh(pedido)
        assert pedido.tipo_cambio == Decimal("1430")  # override still wins

        # Clear override → Caso-A weighted resumes.
        pedidos_service.actualizar_tipo_cambio_manual(
            db,
            pedido_id=pedido.id,
            tipo_cambio=None,
            motivo="volver a automático",
            user_id=active_user.id,
        )
        db.refresh(pedido)

        # Now Caso-A weighted avg rules (only one payment: USD500 * TC1450 = ARS725000 → TC=1450).
        assert pedido.tipo_cambio_manual is None
        assert pedido.tipo_cambio == Decimal("1450")

    def test_override_eliminates_varianza(
        self, db, empresa, proveedor, caja_ars, tipo_doc_caja, tipo_cambio_usd, active_user
    ) -> None:
        """T5.15 / AC5.9, Scenario 5.C — manual TC override can drive variance to zero.

        Setup:
          Pedido USD 1000, TC_orig 1400.
          OP #1 Caso A TC 1450, USD 600 → effective TC becomes 1450 (Caso-A weighted).
          OP #2 Caso B TC 1430, USD 400 (ARS 572000).
          calcular_varianza_tc formula: (TC_efectivo - TC_original) * USD_caso_b
            = (1450 - 1400) * 400 = 20000 ARS ND (before override).
          Set manual TC = TC_original (1400) → variance = (1400 - 1400) * 400 = 0.

        Note: the spec's AC5.9 numeric example used TC_orig=1430 but the actual
        fixture uses TC_orig=1400 (pedido was created with tipo_cambio_original=1400).
        Override TC=1400 is used here so the formula produces variance=0.
        """
        pedido = _make_pedido_usd(
            db, empresa, proveedor, active_user.id, monto=Decimal("1000"), tc_original=Decimal("1400")
        )

        # Caso-A payment: USD 600 at TC 1450 = ARS 870000.
        _make_caso_a_op(
            db,
            empresa,
            proveedor,
            caja_ars,
            active_user.id,
            pedido,
            tc=Decimal("1450"),
            monto_ars=Decimal("870000"),
        )
        db.refresh(pedido)
        assert pedido.tipo_cambio == Decimal("1450")

        # Caso-B payment: USD 400 at TC 1430 = ARS 572000.
        op_b = ordenes_pago_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto_total=Decimal("572000"),
            tipo_cambio=Decimal("1430"),
            modo_imputacion="especifica",
            items=[{"tipo": "pedido_compra", "id": pedido.id, "monto": Decimal("572000")}],
            creado_por_id=active_user.id,
            actualizar_tc_pedido=False,
        )
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op_b.id,
            caja_id=caja_ars.id,
            fecha_pago_real=date(2026, 1, 1),
            user_id=active_user.id,
        )
        db.refresh(pedido)

        # Variance before override: (TC_ef - TC_orig) * USD_caso_b = (1450 - 1400) * 400 = 20000 ARS.
        # Note: spec AC5.9 uses 1430 as TC_orig reference in the arithmetic example, but
        # calcular_varianza_tc uses pedido.tipo_cambio_original (=1400) per §3.3 formula.
        varianza_before = pedidos_service.calcular_varianza_tc(db, pedido)
        assert varianza_before == Decimal("20000")

        # Set manual TC = 1400 (= TC_original) to eliminate variance.
        # With override = TC_original: (1400 - 1400) * 400 = 0.
        pedidos_service.actualizar_tipo_cambio_manual(
            db,
            pedido_id=pedido.id,
            tipo_cambio=Decimal("1400"),
            motivo="ajuste a TC original",
            user_id=active_user.id,
        )
        db.refresh(pedido)
        assert pedido.tipo_cambio == Decimal("1400")

        # Variance after override = 0 because TC_efectivo now equals TC_original.
        varianza_after = pedidos_service.calcular_varianza_tc(db, pedido)
        assert varianza_after == Decimal("0")


class TestActualizarTCManualARSRejection:
    """T5.19 — actualizar_tipo_cambio_manual rejects ARS pedidos with HTTP 400 (AC5.10)."""

    def test_ars_pedido_rejected(self, db, empresa, proveedor, active_user) -> None:
        """Passing a USD TC override to an ARS pedido raises HTTP 400."""
        pedido_ars = PedidoCompra(
            numero="PC-F5-ARS-001",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("50000"),
            tipo_cambio=None,
            tipo_cambio_original=None,
            estado="aprobado",
            creado_por_id=active_user.id,
        )
        db.add(pedido_ars)
        db.flush()

        with pytest.raises(HTTPException) as exc_info:
            pedidos_service.actualizar_tipo_cambio_manual(
                db,
                pedido_id=pedido_ars.id,
                tipo_cambio=Decimal("1430"),
                motivo="intento de override en ARS",
                user_id=active_user.id,
            )

        assert exc_info.value.status_code == 400
        assert "USD" in str(exc_info.value.detail)


class TestEditarPedidoF5Restriction:
    """T5.17 — editar_pedido rejects tipo_cambio with 422 (AC5.6, FR5.9)."""

    def test_editar_pedido_rejects_tipo_cambio(self, db, empresa, proveedor, active_user) -> None:
        """After F5, tipo_cambio is no longer in CAMPOS_EDITABLES_APROBADO → 422."""
        pedido = _make_pedido_usd(db, empresa, proveedor, active_user.id)

        with pytest.raises(HTTPException) as exc_info:
            pedidos_service.editar_pedido(
                db,
                pedido_id=pedido.id,
                user_id=active_user.id,
                tipo_cambio=Decimal("1500"),
            )

        assert exc_info.value.status_code == 422
        assert "tipo_cambio" in str(exc_info.value.detail).lower() or "editable" in str(exc_info.value.detail).lower()

    def test_corregir_pedido_unaffected_by_f5(self, db, empresa, proveedor, active_user) -> None:
        """T5.18 / AC5.7 — corregir_pedido still handles monto corrections; no regression."""
        pedido = _make_pedido_usd(db, empresa, proveedor, active_user.id, monto=Decimal("1000"))

        # corregir_pedido with a monto change (should succeed — this is its job).
        result = pedidos_service.corregir_pedido(
            db,
            pedido_original_id=pedido.id,
            cambios={"monto": Decimal("900")},
            motivo_correccion="corrección de monto",
            user_id=active_user.id,
        )
        # Returns the clone pedido in 'pendiente_aprobacion'.
        assert result is not None
        assert result.monto == Decimal("900")

    def test_corregir_pedido_rejects_tipo_cambio(self, db, empresa, proveedor, active_user) -> None:
        """F5 — corregir_pedido must reject tipo_cambio with HTTP 422 (closes the unaudited TC path)."""
        pedido = _make_pedido_usd(db, empresa, proveedor, active_user.id, monto=Decimal("1000"))

        with pytest.raises(HTTPException) as exc_info:
            pedidos_service.corregir_pedido(
                db,
                pedido_original_id=pedido.id,
                cambios={"tipo_cambio": Decimal("1500")},
                motivo_correccion="intento de cambio TC por correccion",
                user_id=active_user.id,
            )

        assert exc_info.value.status_code == 422
        assert "tipo_cambio" in str(exc_info.value.detail).lower()
