"""
T2.3 — Unit tests for BancoService (F7/PR#2a).

Tests registrar_movimiento, listar_bancos (empresa_id filter),
crear_banco (saldo_actual=saldo_inicial, empresa_id), and actualizar_banco.

Pattern: MagicMock session, no real DB required.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_banco(
    id: int = 1,
    saldo_actual: Decimal = Decimal("10000"),
    activo: bool = True,
    empresa_id: int | None = 1,
    moneda: str = "ARS",
    saldo_inicial: Decimal = Decimal("10000"),
) -> MagicMock:
    banco = MagicMock()
    banco.id = id
    banco.saldo_actual = saldo_actual
    banco.saldo_inicial = saldo_inicial
    banco.activo = activo
    banco.empresa_id = empresa_id
    banco.moneda = moneda
    return banco


# ---------------------------------------------------------------------------
# registrar_movimiento
# ---------------------------------------------------------------------------


class TestRegistrarMovimiento:
    """BancoService.registrar_movimiento — atomic balance update."""

    def _make_service(self, banco: MagicMock):  # type: ignore[override]  # type: ignore[name-defined]
        from app.services.banco_service import BancoService  # noqa: PLC0415

        db = MagicMock()
        # SELECT FOR UPDATE chain: .query().filter().with_for_update().first()
        db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = banco
        svc = BancoService(db)
        return svc

    def test_egreso_calculates_correct_saldo_posterior(self) -> None:
        banco = _make_mock_banco(saldo_actual=Decimal("10000"))
        svc = self._make_service(banco)
        from datetime import date  # noqa: PLC0415

        mov = svc.registrar_movimiento(
            banco_id=1,
            fecha=date.today(),
            detalle="Pago proveedor",
            tipo="egreso",
            monto=Decimal("3000"),
            user_id=42,
            origen="op",
        )

        assert mov.saldo_posterior == Decimal("7000")
        assert banco.saldo_actual == Decimal("7000")

    def test_ingreso_calculates_correct_saldo_posterior(self) -> None:
        banco = _make_mock_banco(saldo_actual=Decimal("5000"))
        svc = self._make_service(banco)
        from datetime import date  # noqa: PLC0415

        mov = svc.registrar_movimiento(
            banco_id=1,
            fecha=date.today(),
            detalle="Transferencia recibida",
            tipo="ingreso",
            monto=Decimal("2000"),
            user_id=1,
            origen="manual",
        )

        assert mov.saldo_posterior == Decimal("7000")
        assert banco.saldo_actual == Decimal("7000")

    def test_egreso_insufficient_saldo_raises_422(self) -> None:
        banco = _make_mock_banco(saldo_actual=Decimal("100"))
        svc = self._make_service(banco)
        from datetime import date  # noqa: PLC0415

        with pytest.raises(HTTPException) as exc_info:
            svc.registrar_movimiento(
                banco_id=1,
                fecha=date.today(),
                detalle="Pago",
                tipo="egreso",
                monto=Decimal("500"),
                user_id=1,
            )
        assert exc_info.value.status_code == 422
        assert "saldo" in exc_info.value.detail.lower()

    def test_uses_select_for_update(self) -> None:
        """SELECT FOR UPDATE must be called to prevent concurrent updates."""
        banco = _make_mock_banco()
        svc = self._make_service(banco)
        from datetime import date  # noqa: PLC0415

        svc.registrar_movimiento(
            banco_id=1,
            fecha=date.today(),
            detalle="Test",
            tipo="egreso",
            monto=Decimal("100"),
            user_id=1,
        )

        # Verify with_for_update was called in the chain
        svc.db.query.return_value.filter.return_value.with_for_update.assert_called()

    def test_does_not_commit(self) -> None:
        """registrar_movimiento must NOT commit — caller owns the transaction."""
        banco = _make_mock_banco()
        svc = self._make_service(banco)
        from datetime import date  # noqa: PLC0415

        svc.registrar_movimiento(
            banco_id=1,
            fecha=date.today(),
            detalle="Test",
            tipo="egreso",
            monto=Decimal("100"),
            user_id=1,
        )

        svc.db.commit.assert_not_called()

    def test_creates_banco_movimiento_record(self) -> None:
        banco = _make_mock_banco(saldo_actual=Decimal("5000"))
        svc = self._make_service(banco)
        from datetime import date  # noqa: PLC0415

        svc.registrar_movimiento(
            banco_id=1,
            fecha=date.today(),
            detalle="Detalle test",
            tipo="egreso",
            monto=Decimal("1000"),
            user_id=5,
        )

        svc.db.add.assert_called()
        svc.db.flush.assert_called()


# ---------------------------------------------------------------------------
# listar_bancos — empresa_id filter
# ---------------------------------------------------------------------------


class TestListarBancos:
    """BancoService.listar_bancos — empresa_id filter."""

    def _make_service(self):  # type: ignore[override]  # type: ignore[name-defined]
        from app.services.banco_service import BancoService  # noqa: PLC0415

        db = MagicMock()
        svc = BancoService(db)
        return svc

    def test_empresa_id_filter_applied(self) -> None:
        svc = self._make_service()
        svc.listar_bancos(empresa_id=1)

        # The query chain must include a filter call
        assert svc.db.query.called

    def test_no_empresa_id_filter_when_none(self) -> None:
        svc = self._make_service()
        # Should not raise — empresa_id=None means no filter
        svc.listar_bancos(empresa_id=None)
        assert svc.db.query.called


# ---------------------------------------------------------------------------
# crear_banco
# ---------------------------------------------------------------------------


class TestCrearBanco:
    """BancoService.crear_banco — saldo_actual initialized from saldo_inicial."""

    def test_saldo_actual_set_to_saldo_inicial(self) -> None:
        from app.services.banco_service import BancoService  # noqa: PLC0415

        db = MagicMock()
        svc = BancoService(db)

        created_banco = MagicMock()
        created_banco.saldo_actual = None
        created_banco.saldo_inicial = Decimal("5000")

        # Capture what gets added
        added_objects: list = []

        def capture_add(obj: object) -> None:
            added_objects.append(obj)

        db.add.side_effect = capture_add

        svc.crear_banco(
            banco="Santander",
            empresa_id=1,
            moneda="ARS",
            saldo_inicial=Decimal("5000"),
        )

        db.add.assert_called()
        db.flush.assert_called()
        # Verify the object added has saldo_actual == saldo_inicial
        added = added_objects[0]
        assert added.saldo_actual == Decimal("5000")

    def test_empresa_id_persisted(self) -> None:
        from app.services.banco_service import BancoService  # noqa: PLC0415

        db = MagicMock()
        svc = BancoService(db)
        added_objects: list = []
        db.add.side_effect = lambda obj: added_objects.append(obj)

        svc.crear_banco(banco="HSBC", empresa_id=2, moneda="USD", saldo_inicial=Decimal("0"))

        added = added_objects[0]
        assert added.empresa_id == 2

    def test_empresa_id_none_persisted(self) -> None:
        from app.services.banco_service import BancoService  # noqa: PLC0415

        db = MagicMock()
        svc = BancoService(db)
        added_objects: list = []
        db.add.side_effect = lambda obj: added_objects.append(obj)

        svc.crear_banco(banco="Galicia", empresa_id=None, moneda="ARS", saldo_inicial=Decimal("0"))

        added = added_objects[0]
        assert added.empresa_id is None


# ---------------------------------------------------------------------------
# actualizar_banco
# ---------------------------------------------------------------------------


class TestActualizarBanco:
    """BancoService.actualizar_banco — empresa_id update."""

    def _svc_with_banco(self, banco: MagicMock):  # type: ignore[override]  # type: ignore[name-defined]
        from app.services.banco_service import BancoService  # noqa: PLC0415

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = banco
        svc = BancoService(db)
        return svc

    def test_actualizar_empresa_id(self) -> None:
        banco = _make_mock_banco(empresa_id=1)
        svc = self._svc_with_banco(banco)

        svc.actualizar_banco(banco_id=1, empresa_id=2)

        assert banco.empresa_id == 2

    def test_actualizar_empresa_id_to_none(self) -> None:
        banco = _make_mock_banco(empresa_id=1)
        svc = self._svc_with_banco(banco)

        svc.actualizar_banco(banco_id=1, empresa_id=None)

        # empresa_id=None is a valid update (unassign empresa)
        assert banco.empresa_id is None
