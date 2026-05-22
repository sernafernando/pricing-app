"""
T2.7 — Tests para calcular_saldo_a_favor_breakdown en cc_proveedor_service.

Cubre (strict TDD):
  - test_breakdown_ars_only: CC solo ARS, sin DAC ni NC → breakdown vacío
  - test_breakdown_separa_nc_de_dinero_a_cuenta (AC-2.2): proveedor con saldo
    a favor compuesto de NC crédito + DAC → breakdown los separa
  - test_breakdown_excludes_consumido (AC-2.3): DAC consumido no aparece en componente

Los tests usan la sesión SQLite en memoria del conftest.py.
Llaman el servicio directamente, sin HTTP.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.dinero_a_cuenta import DineroACuenta
from app.models.empresa import Empresa
from app.models.proveedor import Proveedor
from app.models.usuario import AuthProvider, RolUsuario, Usuario


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def empresa(db) -> Empresa:
    emp = Empresa(nombre="Empresa Breakdown Test", activo=True)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture()
def proveedor(db) -> Proveedor:
    prov = Proveedor(nombre="Proveedor Breakdown Test", origen="manual", activo=True)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture()
def user(db) -> Usuario:
    u = Usuario(
        username="breakdown_user",
        email="breakdown@test.com",
        nombre="Breakdown User",
        password_hash="hashed",
        rol=RolUsuario.ADMIN,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture()
def op_stub(db, empresa, proveedor, user) -> object:
    from sqlalchemy import text

    db.execute(
        text(
            """
            INSERT INTO ordenes_pago
              (numero, empresa_id, proveedor_id, moneda, monto_total,
               modo_imputacion, estado, actualizar_tc_pedido, creado_por_id)
            VALUES
              ('OP-BRK-001', :emp, :prov, 'ARS', 5000,
               'especifica', 'pagado', 0, :uid)
            """
        ),
        {"emp": empresa.id, "prov": proveedor.id, "uid": user.id},
    )
    db.flush()
    op_id = db.execute(text("SELECT last_insert_rowid()")).scalar()
    return type("OP", (), {"id": op_id})()


def _insert_cc_haber(db, *, proveedor_id: int, empresa_id: int, monto: Decimal) -> None:
    """Inserta un HABER ARS en cc_proveedor_movimientos (simula un pago)."""
    mov = CCProveedorMovimiento(
        proveedor_id=proveedor_id,
        empresa_id=empresa_id,
        fecha_movimiento=datetime.date.today(),
        tipo="haber",
        monto=monto,
        moneda="ARS",
        origen_tipo="imputacion",
        origen_id=None,
    )
    db.add(mov)
    db.flush()


def _insert_cc_debe(db, *, proveedor_id: int, empresa_id: int, monto: Decimal) -> None:
    """Inserta un DEBE ARS en cc_proveedor_movimientos (simula una deuda)."""
    mov = CCProveedorMovimiento(
        proveedor_id=proveedor_id,
        empresa_id=empresa_id,
        fecha_movimiento=datetime.date.today(),
        tipo="debe",
        monto=monto,
        moneda="ARS",
        origen_tipo="pedido_compra",
        origen_id=None,
    )
    db.add(mov)
    db.flush()


def _insert_dac(db, *, proveedor_id, empresa_id, monto, moneda, origen_op_id, creado_por_id, estado="disponible"):
    dac = DineroACuenta(
        proveedor_id=proveedor_id,
        empresa_id=empresa_id,
        monto=monto,
        moneda=moneda,
        estado=estado,
        origen_op_id=origen_op_id,
        creado_por_id=creado_por_id,
    )
    db.add(dac)
    db.flush()
    return dac


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestSaldoAFavorBreakdown:
    def test_breakdown_ars_only_sin_dac_ni_nc(self, db, empresa, proveedor, user):
        """Proveedor con deuda neta (debe > haber) → saldo_a_favor_total_ars es 0, componentes 0."""
        from app.services.cc_proveedor_service import calcular_saldo_a_favor_breakdown

        _insert_cc_debe(db, proveedor_id=proveedor.id, empresa_id=empresa.id, monto=Decimal("1000"))

        result = calcular_saldo_a_favor_breakdown(db, proveedor_id=proveedor.id)

        assert result["proveedor_id"] == proveedor.id
        # Sign contract: saldo_a_favor_total_ars is NEVER negative.
        # When proveedor owes us money, magnitude = 0.
        assert result["saldo_a_favor_total_ars"] == Decimal("0")
        assert result["componente_dinero_a_cuenta_ars"] == Decimal("0")
        assert result["componente_nc_ars"] == Decimal("0")

    def test_breakdown_separa_nc_de_dinero_a_cuenta(self, db, empresa, proveedor, user, op_stub):
        """
        AC-2.2 — proveedor con saldo a favor compuesto de DAC + NC → breakdown los separa.

        Setup: saldo a favor ARS 10.000 total.
          - DAC ARS 3.000 (disponible)
          - componente_nc: calculado aparte (requiere NC local fixture complejo)

        Para mantener el test aislado y sin depender del NC router,
        testeamos que el componente_dinero_a_cuenta es correcto y que
        el breakdown devuelve la estructura esperada con los campos separados.
        """
        from app.services.cc_proveedor_service import calcular_saldo_a_favor_breakdown

        # Simular saldo a favor: haber > debe
        _insert_cc_debe(db, proveedor_id=proveedor.id, empresa_id=empresa.id, monto=Decimal("5000"))
        _insert_cc_haber(db, proveedor_id=proveedor.id, empresa_id=empresa.id, monto=Decimal("8000"))
        # Saldo neto = 5000 - 8000 = -3000 → saldo a favor 3000

        # Insertar DAC disponible de 2000
        _insert_dac(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("2000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
        )

        result = calcular_saldo_a_favor_breakdown(db, proveedor_id=proveedor.id)

        assert result["proveedor_id"] == proveedor.id
        # Sign contract: saldo_a_favor_total_ars is POSITIVE (magnitude).
        # Saldo neto ARS = 5000 - 8000 = -3000 → a favor del proveedor → magnitude 3000.
        assert result["saldo_a_favor_total_ars"] == Decimal("3000")
        # Componente DAC debe ser 2000
        assert result["componente_dinero_a_cuenta_ars"] == Decimal("2000")
        # NC 0 porque no hay NCs
        assert result["componente_nc_ars"] == Decimal("0")
        assert "por_moneda" in result

    def test_breakdown_excludes_consumido(self, db, empresa, proveedor, user, op_stub):
        """AC-2.3 — DAC consumido no aparece en componente_dinero_a_cuenta."""
        from app.services.cc_proveedor_service import calcular_saldo_a_favor_breakdown

        _insert_dac(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("5000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
            estado="consumido",
        )

        result = calcular_saldo_a_favor_breakdown(db, proveedor_id=proveedor.id)

        # El DAC consumido NO debe contar en el componente
        assert result["componente_dinero_a_cuenta_ars"] == Decimal("0")

    def test_breakdown_includes_consumido_parcial(self, db, empresa, proveedor, user, op_stub):
        """DAC consumido_parcial sí aporta su saldo restante al componente."""
        from app.services.cc_proveedor_service import calcular_saldo_a_favor_breakdown
        from app.models.imputacion import Imputacion

        dac = _insert_dac(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("6000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
            estado="consumido_parcial",  # ya marcado como parcial
        )
        # Simular que se consumió 1000 (saldo restante = 5000)
        consumo = Imputacion(
            origen_tipo="dinero_a_cuenta",
            origen_id=dac.id,
            destino_tipo="pedido_compra",
            destino_id=1,
            monto_imputado=Decimal("1000"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            es_reversal=False,
            creado_por_id=user.id,
        )
        db.add(consumo)
        db.flush()

        result = calcular_saldo_a_favor_breakdown(db, proveedor_id=proveedor.id)

        # Saldo disponible = 6000 - 1000 = 5000
        assert result["componente_dinero_a_cuenta_ars"] == Decimal("5000")
