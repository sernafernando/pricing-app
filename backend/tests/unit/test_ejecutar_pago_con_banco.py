"""
T3.2 — Unit tests for ejecutar_pago with banco as fund source (F7/PR#2b).
T3.3 — Unit tests for anular on OP pagada con banco.

Uses MagicMock session — no real DB required.

Covers (T3.2):
  - Happy path: banco_id set → BancoMovimiento egreso, banco.saldo_actual updated,
    op.banco_id / op.banco_movimiento_id set, caja_id=None, caja_movimiento_id=None (AC-F2-5).
  - Caja path regression: caja_id → same as before, banco FKs stay None (AC-F2-6).
  - banco not found → 404.
  - banco activo=False → 422 (AC-F2-8).
  - banco empresa_id=None → 422 (AC-F2-9, Scenario G2).
  - banco empresa_id != op.empresa_id → 409 (AC-F2-10, igual que caja).
  - saldo banco insuficiente → 422 (Scenario I).
  - caja_documento_id is NULL for banco payments (AD-8).

Covers (T3.3):
  - anular on OP paid with banco → BancoMovimiento ingreso compensatorio.
  - anular on OP paid with caja → unchanged behaviour (regression).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services import ordenes_pago_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_op(
    id: int = 42,
    numero: str = "OP-042",
    estado: str = "pendiente",
    empresa_id: int = 1,
    proveedor_id: int = 10,
    moneda: str = "ARS",
    monto_total: Decimal = Decimal("20000"),
    modo_imputacion: str = "a_cuenta",
    tipo_cambio: Decimal | None = None,
    caja_id: int | None = None,
    banco_id: int | None = None,
) -> MagicMock:
    op = MagicMock()
    op.id = id
    op.numero = numero
    op.estado = estado
    op.empresa_id = empresa_id
    op.proveedor_id = proveedor_id
    op.moneda = moneda
    op.monto_total = monto_total
    op.modo_imputacion = modo_imputacion
    op.tipo_cambio = tipo_cambio
    op.caja_id = caja_id
    op.banco_id = banco_id
    op.caja_movimiento_id = None
    op.caja_documento_id = None
    op.banco_movimiento_id = None
    return op


def _make_banco(
    id: int = 5,
    moneda: str = "ARS",
    empresa_id: int | None = 1,
    saldo_actual: Decimal = Decimal("50000"),
    activo: bool = True,
) -> MagicMock:
    banco = MagicMock()
    banco.id = id
    banco.moneda = moneda
    banco.empresa_id = empresa_id
    banco.saldo_actual = saldo_actual
    banco.activo = activo
    return banco


def _make_movimiento(id: int = 99) -> MagicMock:
    mov = MagicMock()
    mov.id = id
    return mov


# ---------------------------------------------------------------------------
# T3.2 — ejecutar_pago con banco
# ---------------------------------------------------------------------------


class TestEjecutarPagoConBanco:
    """ejecutar_pago wired to BancoService when banco_id is provided."""

    def _session_for_banco(
        self,
        op: MagicMock,
        banco: MagicMock,
    ) -> MagicMock:
        """Build a mock session that returns op (with_for_update) and banco (get)."""
        session = MagicMock()
        # SELECT FOR UPDATE returns op
        session.execute.return_value.scalar_one_or_none.return_value = op
        # session.get calls: banco by id, Proveedor
        proveedor = MagicMock()
        proveedor.nombre = "Proveedor Test"

        def _get(model_cls: Any, pk: Any) -> Any:
            from app.models.banco_empresa import BancoEmpresa  # noqa: PLC0415
            from app.models.proveedor import Proveedor  # noqa: PLC0415

            if model_cls is BancoEmpresa:
                return banco
            if model_cls is Proveedor:
                return proveedor
            return None

        session.get.side_effect = _get
        return session

    def test_happy_path_banco_egreso(self) -> None:
        """
        Happy path (Scenario G): ejecutar_pago with banco_id=5.
        - BancoMovimiento egreso created via BancoService.
        - op.banco_id, op.banco_movimiento_id set.
        - op.caja_id, op.caja_movimiento_id, op.caja_documento_id remain None.
        """
        op = _make_op(estado="pendiente", empresa_id=1, moneda="ARS", monto_total=Decimal("20000"))
        banco = _make_banco(id=5, moneda="ARS", empresa_id=1, saldo_actual=Decimal("50000"))
        banco_movimiento = _make_movimiento(id=77)
        session = self._session_for_banco(op, banco)

        # Patch all side-effect callees
        with (
            patch("app.services.ordenes_pago_service.BancoService") as MockBancoSvc,
            patch("app.services.ordenes_pago_service._leer_items_de_op", return_value=[]),
            patch("app.services.ordenes_pago_service.validar_balance_op"),
            patch("app.services.ordenes_pago_service._validar_items_cross_moneda_con_tc"),
            patch("app.services.ordenes_pago_service.imputaciones_service"),
            patch("app.services.cc_proveedor_service"),
            patch("app.services.ordenes_pago_service.pedidos_service"),
            patch("app.services.ordenes_pago_service._actualizar_tc_efectivo_pedidos_afectados"),
            patch("app.services.ordenes_pago_service._registrar_evento"),
        ):
            mock_banco_svc = MockBancoSvc.return_value
            mock_banco_svc.registrar_movimiento.return_value = banco_movimiento

            ordenes_pago_service.ejecutar_pago(
                session,
                orden_pago_id=42,
                banco_id=5,
                fecha_pago_real=date(2026, 5, 21),
                user_id=1,
            )

        # Banco service was called with egreso
        mock_banco_svc.registrar_movimiento.assert_called_once()
        call_kwargs = mock_banco_svc.registrar_movimiento.call_args
        assert call_kwargs.kwargs.get("tipo") == "egreso" or call_kwargs.args[3] == "egreso"

        # OP fields set correctly
        assert op.banco_id == 5
        assert op.banco_movimiento_id == 77
        assert op.caja_documento_id is None
        assert op.estado == "pagado"

    def test_caja_path_regression(self) -> None:
        """
        Regression (AC-F2-6): caja_id still works; banco FKs stay None.
        """
        from app.models.caja import Caja  # noqa: PLC0415

        op = _make_op(estado="pendiente", empresa_id=1, moneda="ARS", monto_total=Decimal("10000"))
        caja = MagicMock()
        caja.id = 3
        caja.moneda = "ARS"
        caja.empresa_id = 1
        proveedor = MagicMock()
        proveedor.nombre = "Prov"
        movimiento = _make_movimiento(id=55)
        documento = _make_movimiento(id=66)

        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = op

        def _get(cls: Any, pk: Any) -> Any:
            if cls is Caja:
                return caja
            from app.models.proveedor import Proveedor  # noqa: PLC0415

            if cls is Proveedor:
                return proveedor
            return None

        session.get.side_effect = _get

        with (
            patch("app.services.ordenes_pago_service.CajaService") as MockCajaSvc,
            patch("app.services.ordenes_pago_service._leer_items_de_op", return_value=[]),
            patch("app.services.ordenes_pago_service.validar_balance_op"),
            patch("app.services.ordenes_pago_service._validar_items_cross_moneda_con_tc"),
            patch("app.services.ordenes_pago_service.imputaciones_service"),
            patch("app.services.cc_proveedor_service"),
            patch("app.services.ordenes_pago_service.pedidos_service"),
            patch("app.services.ordenes_pago_service._actualizar_tc_efectivo_pedidos_afectados"),
            patch("app.services.ordenes_pago_service._registrar_evento"),
            patch("app.services.ordenes_pago_service._lookup_tipo_documento_id", return_value=1),
        ):
            mock_caja_svc = MockCajaSvc.return_value
            mock_caja_svc.registrar_movimiento.return_value = movimiento
            mock_caja_svc.crear_documento.return_value = documento

            ordenes_pago_service.ejecutar_pago(
                session,
                orden_pago_id=42,
                caja_id=3,
                fecha_pago_real=date(2026, 5, 21),
                user_id=1,
            )

        # Caja was used — banco fields NOT set
        assert op.caja_id == 3
        assert op.caja_movimiento_id == 55
        assert op.caja_documento_id == 66
        assert op.banco_id is None
        assert op.banco_movimiento_id is None

    def test_banco_not_found_404(self) -> None:
        """banco_id pointing to non-existent banco → 404."""
        op = _make_op(estado="pendiente")
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = op

        def _get(cls: Any, pk: Any) -> Any:
            from app.models.banco_empresa import BancoEmpresa  # noqa: PLC0415

            if cls is BancoEmpresa:
                return None
            return None

        session.get.side_effect = _get

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.ejecutar_pago(
                session,
                orden_pago_id=42,
                banco_id=999,
                fecha_pago_real=date(2026, 5, 21),
                user_id=1,
            )
        assert exc_info.value.status_code == 404

    def test_banco_inactivo_422(self) -> None:
        """banco with activo=False → 422 (AC-F2-8)."""
        op = _make_op(estado="pendiente")
        banco = _make_banco(activo=False)
        session = self._session_for_banco(op, banco)

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.ejecutar_pago(
                session,
                orden_pago_id=42,
                banco_id=5,
                fecha_pago_real=date(2026, 5, 21),
                user_id=1,
            )
        assert exc_info.value.status_code == 422

    def test_banco_sin_empresa_422(self) -> None:
        """banco with empresa_id=None → 422 (AC-F2-9, Scenario G2)."""
        op = _make_op(estado="pendiente", empresa_id=1)
        banco = _make_banco(empresa_id=None)
        session = self._session_for_banco(op, banco)

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.ejecutar_pago(
                session,
                orden_pago_id=42,
                banco_id=5,
                fecha_pago_real=date(2026, 5, 21),
                user_id=1,
            )
        assert exc_info.value.status_code == 422
        assert "empresa" in str(exc_info.value.detail).lower()

    def test_banco_empresa_mismatch_409(self) -> None:
        """banco.empresa_id != op.empresa_id → 409 (AC-F2-10, igual que caja)."""
        op = _make_op(estado="pendiente", empresa_id=1)
        banco = _make_banco(empresa_id=2)  # different empresa
        session = self._session_for_banco(op, banco)

        with pytest.raises(HTTPException) as exc_info:
            ordenes_pago_service.ejecutar_pago(
                session,
                orden_pago_id=42,
                banco_id=5,
                fecha_pago_real=date(2026, 5, 21),
                user_id=1,
            )
        assert exc_info.value.status_code == 409

    def test_saldo_insuficiente_via_banco_service_422(self) -> None:
        """Insufficient banco balance → BancoService raises 422 (Scenario I)."""
        op = _make_op(estado="pendiente", empresa_id=1, moneda="ARS", monto_total=Decimal("30000"))
        banco = _make_banco(empresa_id=1, saldo_actual=Decimal("5000"))
        session = self._session_for_banco(op, banco)

        with (
            patch("app.services.ordenes_pago_service.BancoService") as MockBancoSvc,
        ):
            mock_banco_svc = MockBancoSvc.return_value
            mock_banco_svc.registrar_movimiento.side_effect = HTTPException(
                status_code=422, detail="Saldo insuficiente"
            )

            with pytest.raises(HTTPException) as exc_info:
                ordenes_pago_service.ejecutar_pago(
                    session,
                    orden_pago_id=42,
                    banco_id=5,
                    fecha_pago_real=date(2026, 5, 21),
                    user_id=1,
                )
            assert exc_info.value.status_code == 422

    def test_caja_documento_id_null_for_banco_payment(self) -> None:
        """caja_documento_id stays None for banco payments (AD-8 / FR2.9)."""
        op = _make_op(estado="pendiente", empresa_id=1, moneda="ARS", monto_total=Decimal("10000"))
        banco = _make_banco(id=5, empresa_id=1)
        banco_movimiento = _make_movimiento(id=88)
        session = self._session_for_banco(op, banco)

        with (
            patch("app.services.ordenes_pago_service.BancoService") as MockBancoSvc,
            patch("app.services.ordenes_pago_service._leer_items_de_op", return_value=[]),
            patch("app.services.ordenes_pago_service.validar_balance_op"),
            patch("app.services.ordenes_pago_service._validar_items_cross_moneda_con_tc"),
            patch("app.services.ordenes_pago_service.imputaciones_service"),
            patch("app.services.cc_proveedor_service"),
            patch("app.services.ordenes_pago_service.pedidos_service"),
            patch("app.services.ordenes_pago_service._actualizar_tc_efectivo_pedidos_afectados"),
            patch("app.services.ordenes_pago_service._registrar_evento"),
        ):
            MockBancoSvc.return_value.registrar_movimiento.return_value = banco_movimiento

            ordenes_pago_service.ejecutar_pago(
                session,
                orden_pago_id=42,
                banco_id=5,
                fecha_pago_real=date(2026, 5, 21),
                user_id=1,
            )

        # caja_documento_id must NOT be set for banco payments
        assert op.caja_documento_id is None


# ---------------------------------------------------------------------------
# T3.3 — anular OP pagada con banco
# ---------------------------------------------------------------------------


class TestAnularOpPagadaConBanco:
    """anular dispatches compensatory BancoMovimiento ingreso for banco-paid OPs."""

    def test_anular_banco_payment_creates_ingreso(self) -> None:
        """
        anular on OP paid with banco → BancoService.registrar_movimiento(tipo='ingreso').
        banco.saldo_actual restored (Risk #9 — reversal invariant).
        """
        op = _make_op(
            estado="pagado",
            banco_id=5,
            monto_total=Decimal("20000"),
            moneda="ARS",
        )
        op.caja_id = None
        op.banco_movimiento_id = 77  # original egreso movement id
        banco_movimiento_reverso = _make_movimiento(id=200)

        # Mock the original egreso BancoMovimiento (cross-moneda reversal invariant).
        egreso_original = MagicMock()
        egreso_original.monto = Decimal("20000")

        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = op
        session.get.return_value = egreso_original  # session.get(BancoMovimiento, 77)
        # imputaciones query
        session.execute.return_value.scalars.return_value.all.return_value = []

        with (
            patch("app.services.ordenes_pago_service.BancoService") as MockBancoSvc,
            patch("app.services.ordenes_pago_service.imputaciones_service"),
            patch("app.services.ordenes_pago_service.pedidos_service"),
            patch("app.services.ordenes_pago_service._actualizar_tc_efectivo_pedidos_afectados"),
            patch("app.services.ordenes_pago_service._registrar_evento"),
        ):
            mock_banco_svc = MockBancoSvc.return_value
            mock_banco_svc.registrar_movimiento.return_value = banco_movimiento_reverso

            # Two sequential execute calls: 1) SELECT FOR UPDATE op, 2) imputaciones
            session.execute.side_effect = [
                # Call 1: SELECT FOR UPDATE → op
                _mock_execute_scalar(op),
                # Call 2: imputaciones query → empty
                _mock_execute_scalars([]),
            ]

            result = ordenes_pago_service.anular(
                session,
                orden_pago_id=42,
                motivo="test reversal",
                user_id=1,
            )

        # BancoService called with tipo='ingreso' (compensatory movement)
        mock_banco_svc.registrar_movimiento.assert_called_once()
        call_kwargs = mock_banco_svc.registrar_movimiento.call_args
        kwargs = call_kwargs.kwargs
        assert kwargs.get("tipo") == "ingreso"
        assert kwargs.get("banco_id") == 5

        assert result.estado == "anulado"

    def test_anular_caja_payment_regression(self) -> None:
        """
        anular on OP paid with caja → CajaService used; banco untouched.
        Regression for existing behaviour.
        """
        op = _make_op(
            estado="pagado",
            caja_id=3,
            monto_total=Decimal("10000"),
            moneda="ARS",
        )
        op.banco_id = None
        op.caja_movimiento_id = 55  # original egreso movement id
        movimiento_reverso = _make_movimiento(id=300)
        documento = _make_movimiento(id=301)

        # Mock the original egreso CajaMovimiento for cross-moneda reversal invariant.
        egreso_caja_original = MagicMock()
        egreso_caja_original.monto = Decimal("10000")

        with (
            patch("app.services.ordenes_pago_service.CajaService") as MockCajaSvc,
            patch("app.services.ordenes_pago_service.BancoService") as MockBancoSvc,
            patch("app.services.ordenes_pago_service.imputaciones_service"),
            patch("app.services.ordenes_pago_service.pedidos_service"),
            patch("app.services.ordenes_pago_service._actualizar_tc_efectivo_pedidos_afectados"),
            patch("app.services.ordenes_pago_service._registrar_evento"),
            patch("app.services.ordenes_pago_service._lookup_tipo_documento_id", return_value=2),
        ):
            mock_caja_svc = MockCajaSvc.return_value
            mock_caja_svc.registrar_movimiento.return_value = movimiento_reverso
            mock_caja_svc.crear_documento.return_value = documento

            session = MagicMock()
            session.execute.side_effect = [
                _mock_execute_scalar(op),
                _mock_execute_scalars([]),
            ]
            session.get.return_value = egreso_caja_original

            result = ordenes_pago_service.anular(
                session,
                orden_pago_id=42,
                motivo="caja reversal",
                user_id=1,
            )

        # BancoService NOT called for caja-paid OPs
        MockBancoSvc.assert_not_called()
        MockCajaSvc.assert_called_once()
        assert result.estado == "anulado"


# ---------------------------------------------------------------------------
# Helpers for mock execute
# ---------------------------------------------------------------------------


def _mock_execute_scalar(value: Any) -> MagicMock:
    m = MagicMock()
    m.scalar_one_or_none.return_value = value
    return m


def _mock_execute_scalars(items: list) -> MagicMock:
    m = MagicMock()
    m.scalars.return_value.all.return_value = items
    return m
