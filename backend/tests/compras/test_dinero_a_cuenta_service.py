"""
T2.3 — Tests para dinero_a_cuenta_service.

Cubre (strict TDD — tests se escriben ANTES del servicio):
  - test_crear_crea_fila_disponible
  - test_calcular_saldo_disponible_sin_consumos
  - test_calcular_saldo_disponible_con_consumo_parcial
  - test_recalcular_estado_transitions (disponible→consumido_parcial→consumido)
  - test_listar_por_proveedor_filtra_moneda
  - test_calcular_componente_dinero_a_cuenta_no_cross_moneda (AC-2.4)
  - test_cc_saldo_incluye_dinero_a_cuenta (AC-2.1)

Patrón de fixtures: igual a test_wipe_compras.py — usa la sesión SQLite
en memoria provista por conftest.py. No se usan fixtures HTTP (client),
se llama el servicio directamente contra `db`.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.dinero_a_cuenta import DineroACuenta
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.proveedor import Proveedor
from app.models.usuario import AuthProvider, RolUsuario, Usuario


# ──────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def empresa(db) -> Empresa:
    emp = Empresa(nombre="Empresa DAC Test", activo=True)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture()
def proveedor(db) -> Proveedor:
    prov = Proveedor(nombre="Proveedor DAC Test", origen="manual", activo=True)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture()
def proveedor_b(db) -> Proveedor:
    """Segundo proveedor — para aislar queries por proveedor_id."""
    prov = Proveedor(nombre="Proveedor B", origen="manual", activo=True)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture()
def user(db) -> Usuario:
    u = Usuario(
        username="dac_user",
        email="dac@test.com",
        nombre="DAC User",
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
    """
    OP mínima en estado 'pagado' para satisfacer FK dinero_a_cuenta.origen_op_id.
    Usa raw INSERT para no depender del router de OPs ni de sus validaciones.
    """
    from sqlalchemy import text

    db.execute(
        text(
            """
            INSERT INTO ordenes_pago
              (numero, empresa_id, proveedor_id, moneda, monto_total,
               modo_imputacion, estado, actualizar_tc_pedido,
               creado_por_id)
            VALUES
              ('OP-DAC-001', :emp, :prov, 'ARS', 10000,
               'especifica', 'pagado', 0,
               :uid)
            """
        ),
        {"emp": empresa.id, "prov": proveedor.id, "uid": user.id},
    )
    db.flush()
    op_id = db.execute(text("SELECT last_insert_rowid()")).scalar()
    return type("OP", (), {"id": op_id})()


# ──────────────────────────────────────────────────────────────────────────
# Helper: insertar una fila DineroACuenta directamente (sin pasar por el svc)
# ──────────────────────────────────────────────────────────────────────────


def _insert_dac(
    db,
    *,
    proveedor_id: int,
    empresa_id: int,
    monto: Decimal,
    moneda: str,
    origen_op_id: int,
    creado_por_id: int,
    estado: str = "disponible",
) -> DineroACuenta:
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


def _insert_imputacion_consumo(
    db,
    *,
    origen_id: int,
    destino_id: int,
    monto: Decimal,
    moneda: str,
    proveedor_id: int,
    creado_por_id: int,
    es_reversal: bool = False,
) -> Imputacion:
    """Simula una imputación origen='dinero_a_cuenta' → destino='pedido_compra'."""
    imp = Imputacion(
        origen_tipo="dinero_a_cuenta",
        origen_id=origen_id,
        destino_tipo="pedido_compra",
        destino_id=destino_id,
        monto_imputado=monto,
        moneda_imputada=moneda,
        proveedor_id=proveedor_id,
        es_reversal=es_reversal,
        creado_por_id=creado_por_id,
    )
    db.add(imp)
    db.flush()
    return imp


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestCrear:
    def test_crear_crea_fila_disponible(self, db, empresa, proveedor, user, op_stub):
        """T2.3 — crear() inserta una fila DineroACuenta con estado='disponible'."""
        from app.services.dinero_a_cuenta_service import crear

        dac = crear(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("5000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            user_id=user.id,
        )

        assert dac.id is not None
        assert dac.proveedor_id == proveedor.id
        assert dac.empresa_id == empresa.id
        assert dac.monto == Decimal("5000")
        assert dac.moneda == "ARS"
        assert dac.estado == "disponible"
        assert dac.origen_op_id == op_stub.id
        assert dac.creado_por_id == user.id

    def test_crear_monto_cero_rechaza(self, db, empresa, proveedor, user, op_stub):
        """crear() con monto=0 debe lanzar HTTPException 400 (CHECK y validación)."""
        from fastapi import HTTPException

        from app.services.dinero_a_cuenta_service import crear

        with pytest.raises(HTTPException) as exc_info:
            crear(
                db,
                proveedor_id=proveedor.id,
                empresa_id=empresa.id,
                monto=Decimal("0"),
                moneda="ARS",
                origen_op_id=op_stub.id,
                user_id=user.id,
            )
        assert exc_info.value.status_code == 400


class TestCalcularSaldoDisponible:
    def test_sin_consumos_saldo_igual_al_monto(self, db, empresa, proveedor, user, op_stub):
        """AC-2.1 — Sin consumos, saldo_disponible == monto original."""
        from app.services.dinero_a_cuenta_service import calcular_saldo_disponible

        dac = _insert_dac(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("3000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
        )

        saldo = calcular_saldo_disponible(db, dac.id)
        assert saldo == Decimal("3000")

    def test_con_consumo_parcial_saldo_reducido(self, db, empresa, proveedor, user, op_stub):
        """Con 1 imputación no-reversal, saldo_disponible se reduce."""
        from app.services.dinero_a_cuenta_service import calcular_saldo_disponible

        dac = _insert_dac(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("5000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
        )
        # Simular pedido destino con ID arbitrario (sin FK en SQLite mode)
        _insert_imputacion_consumo(
            db,
            origen_id=dac.id,
            destino_id=999,
            monto=Decimal("2000"),
            moneda="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user.id,
        )

        saldo = calcular_saldo_disponible(db, dac.id)
        assert saldo == Decimal("3000")

    def test_reversal_restaura_saldo(self, db, empresa, proveedor, user, op_stub):
        """Un reversal de consumo restaura el saldo."""
        from app.services.dinero_a_cuenta_service import calcular_saldo_disponible

        dac = _insert_dac(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("4000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
        )
        _insert_imputacion_consumo(
            db,
            origen_id=dac.id,
            destino_id=1,
            monto=Decimal("4000"),
            moneda="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user.id,
            es_reversal=False,
        )
        # Reversal del consumo
        _insert_imputacion_consumo(
            db,
            origen_id=dac.id,
            destino_id=1,
            monto=Decimal("4000"),
            moneda="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user.id,
            es_reversal=True,
        )

        saldo = calcular_saldo_disponible(db, dac.id)
        assert saldo == Decimal("4000")


class TestRecalcularEstado:
    def test_sin_consumo_estado_disponible(self, db, empresa, proveedor, user, op_stub):
        from app.services.dinero_a_cuenta_service import recalcular_estado

        dac = _insert_dac(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("1000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
        )
        recalcular_estado(db, dac.id)
        db.refresh(dac)
        assert dac.estado == "disponible"

    def test_consumo_parcial_estado_consumido_parcial(self, db, empresa, proveedor, user, op_stub):
        from app.services.dinero_a_cuenta_service import recalcular_estado

        dac = _insert_dac(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("1000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
        )
        _insert_imputacion_consumo(
            db,
            origen_id=dac.id,
            destino_id=1,
            monto=Decimal("400"),
            moneda="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user.id,
        )
        recalcular_estado(db, dac.id)
        db.refresh(dac)
        assert dac.estado == "consumido_parcial"

    def test_consumo_total_estado_consumido(self, db, empresa, proveedor, user, op_stub):
        from app.services.dinero_a_cuenta_service import recalcular_estado

        dac = _insert_dac(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("1000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
        )
        _insert_imputacion_consumo(
            db,
            origen_id=dac.id,
            destino_id=1,
            monto=Decimal("1000"),
            moneda="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user.id,
        )
        recalcular_estado(db, dac.id)
        db.refresh(dac)
        assert dac.estado == "consumido"


class TestListarPorProveedor:
    def test_filtra_por_moneda(self, db, empresa, proveedor, user, op_stub):
        """listar_por_proveedor con moneda='USD' no devuelve registros ARS."""
        from app.services.dinero_a_cuenta_service import listar_por_proveedor

        _insert_dac(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("5000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
        )
        resultado = listar_por_proveedor(db, proveedor_id=proveedor.id, moneda="USD")
        assert resultado == []

    def test_filtra_por_estado(self, db, empresa, proveedor, user, op_stub):
        """listar_por_proveedor con estado='consumido' no devuelve disponibles."""
        from app.services.dinero_a_cuenta_service import listar_por_proveedor

        _insert_dac(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("2000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
            estado="disponible",
        )
        resultado = listar_por_proveedor(db, proveedor_id=proveedor.id, estado="consumido")
        assert resultado == []

    def test_devuelve_todos_si_sin_filtros(self, db, empresa, proveedor, user, op_stub):
        from app.services.dinero_a_cuenta_service import listar_por_proveedor

        _insert_dac(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("1000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
        )
        _insert_dac(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("500"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
        )
        resultado = listar_por_proveedor(db, proveedor_id=proveedor.id)
        assert len(resultado) == 2


class TestCalcularComponente:
    def test_no_cross_moneda(self, db, empresa, proveedor, user, op_stub):
        """AC-2.4 — consultar USD cuando solo hay ARS retorna Decimal('0')."""
        from app.services.dinero_a_cuenta_service import calcular_componente_dinero_a_cuenta

        _insert_dac(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("8000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
        )
        componente_usd = calcular_componente_dinero_a_cuenta(db, proveedor_id=proveedor.id, moneda="USD")
        assert componente_usd == Decimal("0")

    def test_suma_solo_disponibles(self, db, empresa, proveedor, user, op_stub):
        """AC-2.3 — consumidos no cuentan en el componente."""
        from app.services.dinero_a_cuenta_service import calcular_componente_dinero_a_cuenta

        _insert_dac(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("3000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
            estado="disponible",
        )
        _insert_dac(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("2000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
            estado="consumido",
        )
        componente = calcular_componente_dinero_a_cuenta(db, proveedor_id=proveedor.id, moneda="ARS")
        # Solo el disponible (3000), no el consumido (2000)
        assert componente == Decimal("3000")

    def test_aislado_por_proveedor(self, db, empresa, proveedor, proveedor_b, user, op_stub):
        """El componente de proveedor A no incluye DACs del proveedor B."""
        from app.services.dinero_a_cuenta_service import calcular_componente_dinero_a_cuenta

        _insert_dac(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("5000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
        )
        _insert_dac(
            db,
            proveedor_id=proveedor_b.id,
            empresa_id=empresa.id,
            monto=Decimal("9000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
        )
        componente_a = calcular_componente_dinero_a_cuenta(db, proveedor_id=proveedor.id, moneda="ARS")
        assert componente_a == Decimal("5000")

    def test_componente_con_consumo_parcial(self, db, empresa, proveedor, user, op_stub):
        """El saldo_disponible de cada DAC (no su monto) se suma en el componente."""
        from app.services.dinero_a_cuenta_service import (
            calcular_componente_dinero_a_cuenta,
            recalcular_estado,
        )

        dac = _insert_dac(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            monto=Decimal("10000"),
            moneda="ARS",
            origen_op_id=op_stub.id,
            creado_por_id=user.id,
        )
        # Consumir 3000 de los 10000
        _insert_imputacion_consumo(
            db,
            origen_id=dac.id,
            destino_id=1,
            monto=Decimal("3000"),
            moneda="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user.id,
        )
        recalcular_estado(db, dac.id)

        componente = calcular_componente_dinero_a_cuenta(db, proveedor_id=proveedor.id, moneda="ARS")
        # 10000 - 3000 = 7000 disponible
        assert componente == Decimal("7000")
