"""
Regression test — NC/DAC over-imputation bug fix (Model A: net cash items).

Bug:
  When an NC is applied to a pedido at CREATE (imputar_nc_a_pedido reduces
  pedido.saldo from 30M to 25M), and then ejecutar_pago is called with the
  OP item at FULL saldo (30M), the backend raises 422 because 30M > 25M
  (same-moneda path) or silently goes negative (cross-moneda path).

  The same bug applies to DAC items: the DAC consumes into the same pedido,
  so the cash item (pedido_compra) at full saldo + DAC together over-impute.

Fix — Model A (net cash items):
  The pedido cash item must be NET of NCs/DAC applied to that pedido.
  net = saldo_pendiente − Σ(NC for this pedido) − DAC_for_this_pedido.
  At pay: net_item + NC + DAC = full saldo → pedido ends at 0 with no 422.

Strict TDD: tests run RED against current code, GREEN after the fix.

Test plan:
  1. test_nc_netted_item_pays_pedido_to_zero — the primary regression.
     pedido 30M, NC 5M applied at CREATE, OP item 25M (net), pay → success,
     pedido saldo 0.
  2. test_nc_full_item_raises_422 — documents the broken path.
     pedido 30M, NC 5M applied, OP item 30M (full) → 422 at pay.
  3. test_dac_netted_item_pays_pedido_to_zero — same for DAC.
     pedido 30M, DAC 5M, cash item 25M, pay → success, pedido saldo 0.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.caja import Caja, CajaTipoDocumento
from app.models.empresa import Empresa
from app.models.nota_credito_local import NotaCreditoLocal
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import Proveedor
from app.models.usuario import AuthProvider, RolUsuario, Usuario


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def empresa(db) -> Empresa:
    emp = Empresa(nombre="Empresa NCNet Test", activo=True)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture()
def proveedor(db) -> Proveedor:
    prov = Proveedor(nombre="Proveedor NCNet Test", origen="manual", activo=True)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture()
def user(db) -> Usuario:
    u = Usuario(
        username="ncnet_user",
        email="ncnet@test.com",
        nombre="NCNet User",
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
        nombre="Caja NCNet Test",
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


def _make_pedido(db, *, empresa_id, proveedor_id, user_id, monto, numero) -> PedidoCompra:
    ped = PedidoCompra(
        numero=numero,
        empresa_id=empresa_id,
        proveedor_id=proveedor_id,
        moneda="ARS",
        monto=Decimal(str(monto)),
        estado="aprobado",
        creado_por_id=user_id,
    )
    db.add(ped)
    db.flush()
    return ped


def _make_nc(db, *, empresa_id, proveedor_id, user_id, monto, numero) -> NotaCreditoLocal:
    nc = NotaCreditoLocal(
        numero=numero,
        empresa_id=empresa_id,
        proveedor_id=proveedor_id,
        moneda="ARS",
        monto=Decimal(str(monto)),
        fecha_emision=date(2026, 1, 1),
        motivo="Test NC",
        estado="aprobado",
        tipo="credito",
        creado_por_id=user_id,
    )
    db.add(nc)
    db.flush()
    return nc


def _apply_nc_to_pedido(db, *, nc, pedido, monto, user_id) -> None:
    """Simula imputar_nc_a_pedido para setup del estado post-CREATE."""
    from app.services.ordenes_pago_service import imputar_nc_a_pedido

    imputar_nc_a_pedido(db, nc=nc, pedido=pedido, monto=Decimal(str(monto)), creado_por_id=user_id)
    db.flush()


import json

from sqlalchemy import text


def _make_op(db, *, empresa_id, proveedor_id, user_id, monto_total, numero, moneda="ARS") -> int:
    db.execute(
        text(
            """
            INSERT INTO ordenes_pago
              (numero, empresa_id, proveedor_id, moneda, monto_total,
               modo_imputacion, estado, actualizar_tc_pedido, creado_por_id)
            VALUES
              (:num, :emp, :prov, :mon, :monto, 'especifica', 'pendiente', 0, :uid)
            """
        ),
        {
            "num": numero,
            "emp": empresa_id,
            "prov": proveedor_id,
            "mon": moneda,
            "monto": float(monto_total),
            "uid": user_id,
        },
    )
    db.flush()
    return int(db.execute(text("SELECT last_insert_rowid()")).scalar())


def _seed_items(db, *, op_id, items, user_id) -> None:
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


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — NET item (the fix) → success, pedido saldo 0
# ─────────────────────────────────────────────────────────────────────────────


def test_nc_netted_item_pays_pedido_to_zero(db, empresa, proveedor, user, caja) -> None:
    """
    PRIMARY REGRESSION TEST.

    Sequence:
      1. pedido 30M created.
      2. NC 5M applied to pedido (at CREATE time) → pedido saldo = 25M.
      3. OP created with item = 25M (NET — saldo minus NC), monto_total = 25M.
      4. ejecutar_pago → must succeed (no 422).
      5. pedido saldo must be 0 after pay.

    This is the CORRECT model: item + NC together cover the full pedido.
    """
    from app.services import ordenes_pago_service, pedidos_service

    pedido = _make_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=30_000_000,
        numero="PED-NCNET-001",
    )
    nc = _make_nc(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=5_000_000,
        numero="NC-NCNET-001",
    )

    # Step 2: apply NC to pedido (simulates what happens at CREATE).
    _apply_nc_to_pedido(db, nc=nc, pedido=pedido, monto=5_000_000, user_id=user.id)

    # Verify: pedido saldo is now 25M.
    saldo_post_nc = pedidos_service.calcular_saldo_pendiente_pedido(db, pedido.id)
    assert saldo_post_nc == Decimal("25000000"), f"Expected 25M saldo, got {saldo_post_nc}"

    # Step 3: OP with NET item (25M, not full 30M).
    op_id = _make_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=25_000_000,  # NET = 30M - 5M NC
        numero="OP-NCNET-001",
    )
    _seed_items(
        db,
        op_id=op_id,
        items=[{"tipo": "pedido_compra", "id": pedido.id, "monto": 25_000_000}],  # NET
        user_id=user.id,
    )

    # Step 4: pay — must NOT raise 422.
    op = ordenes_pago_service.ejecutar_pago(
        db,
        orden_pago_id=op_id,
        caja_id=caja.id,
        fecha_pago_real=date(2026, 1, 1),
        user_id=user.id,
    )
    assert op.estado == "pagado"

    # Step 5: pedido saldo must be 0 (net item 25M + NC 5M = 30M full coverage).
    saldo_final = pedidos_service.calcular_saldo_pendiente_pedido(db, pedido.id)
    assert saldo_final == Decimal("0"), f"Expected pedido saldo 0, got {saldo_final}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — FULL item (the broken path) → must raise 422
# ─────────────────────────────────────────────────────────────────────────────


def test_nc_full_item_raises_422(db, empresa, proveedor, user, caja) -> None:
    """
    DOCUMENTS THE BUG — the old broken path.

    Sequence:
      1. pedido 30M.
      2. NC 5M applied → pedido saldo = 25M.
      3. OP with item = 30M (FULL, wrong — old frontend behavior).
      4. ejecutar_pago → must raise 422 (item exceeds saldo).

    This documents why the old model was wrong and confirms the guard works.
    """
    from fastapi import HTTPException

    from app.services import ordenes_pago_service, pedidos_service

    pedido = _make_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=30_000_000,
        numero="PED-NCNET-002",
    )
    nc = _make_nc(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=5_000_000,
        numero="NC-NCNET-002",
    )
    _apply_nc_to_pedido(db, nc=nc, pedido=pedido, monto=5_000_000, user_id=user.id)

    saldo_post_nc = pedidos_service.calcular_saldo_pendiente_pedido(db, pedido.id)
    assert saldo_post_nc == Decimal("25000000")

    # OP with FULL item (30M, the broken old behavior).
    op_id = _make_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=30_000_000,  # FULL — wrong, over-imputes
        numero="OP-NCNET-002",
    )
    _seed_items(
        db,
        op_id=op_id,
        items=[{"tipo": "pedido_compra", "id": pedido.id, "monto": 30_000_000}],  # FULL
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


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — DAC net item (same bug applies to DAC)
# ─────────────────────────────────────────────────────────────────────────────


def test_dac_netted_item_pays_pedido_to_zero(db, empresa, proveedor, user, caja) -> None:
    """
    DAC variant of the over-imputation bug.

    Sequence:
      1. pedido 30M.
      2. Seed a DAC of 5M via a prior pago_a_cuenta OP (fully paid).
      3. OP with cash item = 25M (NET), DAC 5M applied to same pedido.
         monto_total = 25M (cash only, DAC is a credit).
      4. ejecutar_pago → must succeed, pedido saldo 0.

    In current broken model, cash item 25M + DAC 5M → 30M imputed to pedido ✓
    But if the cash item were 30M + DAC 5M → 35M imputed → pedido saldo -5M (bug).
    This test verifies the NET item model works for DAC too.
    """
    from app.services import ordenes_pago_service, pedidos_service

    pedido = _make_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=30_000_000,
        numero="PED-NCNET-003",
    )

    # Seed a DAC via a prior a_cuenta OP (5M pago_a_cuenta).
    pac_op_id = _make_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=5_000_000,
        numero="OP-NCNET-003-PAC",
    )
    _seed_items(
        db,
        op_id=pac_op_id,
        items=[{"tipo": "pago_a_cuenta", "id": None, "monto": 5_000_000}],
        user_id=user.id,
    )
    pac_op = ordenes_pago_service.ejecutar_pago(
        db,
        orden_pago_id=pac_op_id,
        caja_id=caja.id,
        fecha_pago_real=date(2026, 1, 1),
        user_id=user.id,
    )
    assert pac_op.estado == "pagado"

    # Recover the created DAC id.
    from sqlalchemy import text as _text

    dac_id = int(
        db.execute(
            _text("SELECT id FROM dinero_a_cuenta WHERE origen_op_id = :op_id LIMIT 1"),
            {"op_id": pac_op_id},
        ).scalar_one()
    )
    db.flush()

    # OP: cash item = 25M (net), DAC 5M applied to pedido.
    op_id = _make_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=25_000_000,  # NET cash = 30M - 5M DAC
        numero="OP-NCNET-003",
    )
    _seed_items(
        db,
        op_id=op_id,
        items=[
            {"tipo": "pedido_compra", "id": pedido.id, "monto": 25_000_000},  # NET
            {
                "tipo": "dinero_a_cuenta",
                "id": dac_id,
                "monto": 5_000_000,
                "destino_tipo": "pedido_compra",
                "destino_id": pedido.id,
            },
        ],
        user_id=user.id,
    )

    # Pay — must NOT raise 422.
    op = ordenes_pago_service.ejecutar_pago(
        db,
        orden_pago_id=op_id,
        caja_id=caja.id,
        fecha_pago_real=date(2026, 1, 1),
        user_id=user.id,
    )
    assert op.estado == "pagado"

    # Pedido saldo must be 0: 25M(cash) + 5M(DAC) = 30M full coverage.
    saldo_final = pedidos_service.calcular_saldo_pendiente_pedido(db, pedido.id)
    assert saldo_final == Decimal("0"), f"Expected pedido saldo 0, got {saldo_final}"
