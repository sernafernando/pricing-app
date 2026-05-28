"""
Tests de regresión — over-imputación silenciosa al pedido.

Bug: cuando el item.monto de tipo 'pedido_compra' excede el saldo_pendiente del
pedido, el sistema lo aceptaba silenciosamente (el CC emitía un haber mayor al
saldo real, el pedido quedaba con saldo negativo, y no se podía recuperar el
excedente). Fix: validar_balance_op rechaza con 422 si item.monto >
saldo_pendiente del pedido.

Cobertura:
  - test_over_imputacion_pedido_rechaza_422
      El caso exacto del bug: OP $1.500, pedido saldo $1.000 → 422.
  - test_exacto_saldo_pendiente_acepta
      OP igual al saldo → acepta (no-regresión).
  - test_pedido_pagado_parcial_saldo_correcto
      Pedido parcialmente pagado, el saldo restante es el tope; over → 422.
  - test_multiples_items_un_item_excede_rechaza
      OP con dos pedidos, uno con monto correcto y otro excedido → 422.
  - test_pago_a_cuenta_no_se_valida_como_pedido
      item pago_a_cuenta con monto > monto_total de la OP no dispara este
      validador (pago_a_cuenta no tiene destino pedido).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models.caja import Caja, CajaTipoDocumento
from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import Proveedor
from app.models.usuario import AuthProvider, RolUsuario, Usuario


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures base — mínimas, SQLite en memoria vía conftest.py
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def empresa(db) -> Empresa:
    emp = Empresa(nombre="Empresa SaldoCap Test", activo=True)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture()
def proveedor(db) -> Proveedor:
    prov = Proveedor(nombre="Proveedor SaldoCap Test", origen="manual", activo=True)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture()
def user(db) -> Usuario:
    u = Usuario(
        username="saldocap_user",
        email="saldocap@test.com",
        nombre="SaldoCap User",
        password_hash="hashed",
        rol=RolUsuario.ADMIN,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture()
def caja(db, empresa) -> Caja:
    c = Caja(
        nombre="Caja SaldoCap Test",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("999999"),
        saldo_actual=Decimal("999999"),
        activo=True,
    )
    db.add(c)
    db.flush()
    td = CajaTipoDocumento(nombre="Orden de Pago")
    db.add(td)
    db.flush()
    return c


def _insert_op(
    db,
    *,
    empresa_id: int,
    proveedor_id: int,
    user_id: int,
    monto_total: float,
    modo_imputacion: str = "especifica",
    moneda: str = "ARS",
    numero: str,
) -> int:
    db.execute(
        text(
            """
            INSERT INTO ordenes_pago
              (numero, empresa_id, proveedor_id, moneda, monto_total,
               modo_imputacion, estado, actualizar_tc_pedido, creado_por_id)
            VALUES
              (:num, :emp, :prov, :mon, :monto, :modo, 'pendiente', 0, :uid)
            """
        ),
        {
            "num": numero,
            "emp": empresa_id,
            "prov": proveedor_id,
            "mon": moneda,
            "monto": monto_total,
            "modo": modo_imputacion,
            "uid": user_id,
        },
    )
    db.flush()
    return int(db.execute(text("SELECT last_insert_rowid()")).scalar())


def _insert_pedido(
    db,
    *,
    empresa_id: int,
    proveedor_id: int,
    user_id: int,
    monto: float,
    numero: str,
    moneda: str = "ARS",
    estado: str = "aprobado",
) -> int:
    ped = PedidoCompra(
        numero=numero,
        empresa_id=empresa_id,
        proveedor_id=proveedor_id,
        moneda=moneda,
        monto=Decimal(str(monto)),
        estado=estado,
        creado_por_id=user_id,
    )
    db.add(ped)
    db.flush()
    return int(ped.id)


def _seed_evento_items(db, *, op_id: int, items: list[dict], user_id: int) -> None:
    import json

    db.execute(
        text(
            """
            INSERT INTO compras_eventos
              (tipo, entidad_tipo, entidad_id, payload, usuario_id)
            VALUES
              ('items_registrados', 'orden_pago', :op_id, :payload, :uid)
            """
        ),
        {
            "op_id": op_id,
            "payload": json.dumps({"items": items}),
            "uid": user_id,
        },
    )
    db.flush()


def _seed_imputacion_previa(
    db,
    *,
    proveedor_id: int,
    pedido_id: int,
    monto: float,
    moneda: str = "ARS",
    origen_op_id: int,
    user_id: int,
) -> None:
    """Inserta una imputación de pago previa sobre el pedido para simular pago parcial."""
    from app.models.imputacion import Imputacion

    imp = Imputacion(
        origen_tipo="orden_pago",
        origen_id=origen_op_id,
        destino_tipo="pedido_compra",
        destino_id=pedido_id,
        monto_imputado=Decimal(str(monto)),
        moneda_imputada=moneda,
        proveedor_id=proveedor_id,
        es_reversal=False,
        creado_por_id=user_id,
    )
    db.add(imp)
    db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_over_imputacion_pedido_rechaza_422(db, empresa, proveedor, user, caja) -> None:
    """
    Bug exacto: OP $1.500, pedido saldo $1.000.
    El item paga $1.500 al pedido → saldo excedido en $500.
    validar_balance_op debe rechazar con 422 ANTES de mover plata.
    """
    from fastapi import HTTPException

    from app.services import ordenes_pago_service

    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=1_000,
        numero="PED-SCAP-001",
    )

    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=1_500,
        modo_imputacion="especifica",
        numero="OP-SCAP-001",
    )
    _seed_evento_items(
        db,
        op_id=op_id,
        # item: pedido saldo = $1.000, pagamos $1.500 → excede en $500
        items=[{"tipo": "pedido_compra", "id": ped_id, "monto": 1_500}],
        user_id=user.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op_id,
            caja_id=caja.id,
            fecha_pago_real=date(2026, 1, 1),
            user_id=user.id,
        )

    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail.lower()
    # El mensaje debe mencionar el exceso, el pedido, y guiar al usuario.
    assert "excede" in detail or "saldo" in detail or "excedente" in detail


def test_exacto_saldo_pendiente_acepta(db, empresa, proveedor, user, caja) -> None:
    """
    No-regresión: OP == saldo_pendiente del pedido → debe ejecutarse sin error.
    """
    from app.services import ordenes_pago_service

    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=1_000,
        numero="PED-SCAP-002",
    )

    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=1_000,
        numero="OP-SCAP-002",
    )
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[{"tipo": "pedido_compra", "id": ped_id, "monto": 1_000}],
        user_id=user.id,
    )

    op = ordenes_pago_service.ejecutar_pago(
        db,
        orden_pago_id=op_id,
        caja_id=caja.id,
        fecha_pago_real=date(2026, 1, 1),
        user_id=user.id,
    )
    assert op.estado == "pagado"


def test_pedido_pagado_parcial_saldo_correcto(db, empresa, proveedor, user, caja) -> None:
    """
    Pedido de $2.000, ya imputado $1.500 previamente → saldo = $500.
    OP $600 con item pedido $600 → excede saldo ($500) → 422.
    """
    from fastapi import HTTPException

    from app.services import ordenes_pago_service

    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=2_000,
        numero="PED-SCAP-003",
        estado="pagado_parcial",
    )

    # OP anterior que ya imputó $1.500
    op_anterior_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=1_500,
        numero="OP-SCAP-003A",
        modo_imputacion="especifica",
    )
    _seed_imputacion_previa(
        db,
        proveedor_id=proveedor.id,
        pedido_id=ped_id,
        monto=1_500,
        origen_op_id=op_anterior_id,
        user_id=user.id,
    )

    # Nueva OP que intenta pagar $600 (saldo real es $500)
    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=600,
        numero="OP-SCAP-003B",
        modo_imputacion="especifica",
    )
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[{"tipo": "pedido_compra", "id": ped_id, "monto": 600}],
        user_id=user.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op_id,
            caja_id=caja.id,
            fecha_pago_real=date(2026, 1, 1),
            user_id=user.id,
        )

    assert exc_info.value.status_code == 422


def test_multiples_items_un_item_excede_rechaza(db, empresa, proveedor, user, caja) -> None:
    """
    OP con dos pedidos: pedido A saldo $800, pedido B saldo $300.
    items: pedido A $800 (OK), pedido B $400 (excede en $100).
    Total OP = $1.200 = $800 + $400 → balancea, PERO pedido B excede → 422.
    """
    from fastapi import HTTPException

    from app.services import ordenes_pago_service

    ped_a_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=800,
        numero="PED-SCAP-004A",
    )
    ped_b_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=300,
        numero="PED-SCAP-004B",
    )

    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=1_200,
        modo_imputacion="especifica",
        numero="OP-SCAP-004",
    )
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[
            {"tipo": "pedido_compra", "id": ped_a_id, "monto": 800},
            {"tipo": "pedido_compra", "id": ped_b_id, "monto": 400},  # excede $300
        ],
        user_id=user.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op_id,
            caja_id=caja.id,
            fecha_pago_real=date(2026, 1, 1),
            user_id=user.id,
        )

    assert exc_info.value.status_code == 422


def test_pago_a_cuenta_no_se_valida_como_pedido(db, empresa, proveedor, user, caja) -> None:
    """
    item pago_a_cuenta no tiene destino pedido — la validación de saldo no aplica.
    OP $500 con pago_a_cuenta $500 → debe ejecutarse sin error (genera DAC).
    """
    from app.services import ordenes_pago_service

    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=500,
        modo_imputacion="a_cuenta",
        numero="OP-SCAP-005",
    )
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[{"tipo": "pago_a_cuenta", "id": None, "monto": 500}],
        user_id=user.id,
    )

    op = ordenes_pago_service.ejecutar_pago(
        db,
        orden_pago_id=op_id,
        caja_id=caja.id,
        fecha_pago_real=date(2026, 1, 1),
        user_id=user.id,
    )
    assert op.estado == "pagado"
