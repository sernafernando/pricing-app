"""
T5.1 — Regression tests: ejecutar_pago accepts valid payloads after PR5 UX changes.

Verifies that all 5 medios de pago still work correctly end-to-end after
the frontend UX rework in PR5. These are regression tests — they test the
backend directly (service layer), not through HTTP, to ensure nothing broke.

Coverage:
  - test_payload_un_item_cobertura_exacta              — single item, no excedente
  - test_payload_un_item_con_pago_a_cuenta             — single item + pago a cuenta
  - test_payload_multi_item_cobertura_exacta           — 2 items covering full total
  - test_payload_nc_como_cobertura                     — items + NC reduces diferencia
  - test_payload_dac_como_cobertura                    — items + dinero a cuenta
  - test_payload_diferencia_cero_gate_rechaza          — invariante sigue activa post-PR5

Fixtures: reutilizan el patrón de test_invariante_no_diferencia.py.
Items se inyectan vía evento 'items_registrados' (como hace el servicio crear()).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models.caja import Caja, CajaTipoDocumento
from app.models.dinero_a_cuenta import DineroACuenta
from app.models.empresa import Empresa
from app.models.nota_credito_local import NotaCreditoLocal
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import Proveedor
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services import ordenes_pago_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures base
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def empresa(db) -> Empresa:
    emp = Empresa(nombre="Empresa Sync Test", activo=True)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture()
def proveedor(db) -> Proveedor:
    prov = Proveedor(nombre="Proveedor Sync Test", origen="manual", activo=True)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture()
def user(db) -> Usuario:
    u = Usuario(
        username="sync_user",
        email="sync@test.com",
        nombre="Sync User",
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
        nombre="Caja Sync Test",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("1000000"),
        saldo_actual=Decimal("1000000"),
        activo=True,
    )
    db.add(c)
    db.flush()
    td = CajaTipoDocumento(nombre="Orden de Pago")
    db.add(td)
    db.flush()
    return c


# ──────────────────────────────────────────────────────────────────────────
# Helpers (patrón idéntico a test_invariante_no_diferencia.py)
# ──────────────────────────────────────────────────────────────────────────


def _insert_op(
    db,
    *,
    empresa_id: int,
    proveedor_id: int,
    user_id: int,
    monto_total: float,
    moneda: str = "ARS",
    numero: str = "OP-SYNC-001",
    estado: str = "pendiente",
    modo_imputacion: str = "especifica",
) -> int:
    db.execute(
        text(
            """
            INSERT INTO ordenes_pago
              (numero, empresa_id, proveedor_id, moneda, monto_total,
               modo_imputacion, estado, actualizar_tc_pedido, creado_por_id)
            VALUES
              (:num, :emp, :prov, :mon, :monto, :modo, :estado, 0, :uid)
            """
        ),
        {
            "num": numero,
            "emp": empresa_id,
            "prov": proveedor_id,
            "mon": moneda,
            "monto": monto_total,
            "modo": modo_imputacion,
            "estado": estado,
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
    moneda: str = "ARS",
    numero: str = "PED-SYNC-001",
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
    """Inyecta un evento items_registrados — así lo hace el servicio crear()."""
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


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


def test_payload_un_item_cobertura_exacta(db, empresa, proveedor, user, caja):
    """
    Single item equal to monto_total — the happy path that single-item auto-sync enables.
    PR5 UX: user changes total → single item auto-syncs → diferencia=0 → confirms.
    Backend must accept and confirm without error.
    """
    monto = 15_000.0
    pedido_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=monto,
        numero="PED-S-001",
    )
    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=monto,
        numero="OP-S-001",
    )
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[{"tipo": "pedido_compra", "id": pedido_id, "monto": monto}],
        user_id=user.id,
    )

    ordenes_pago_service.ejecutar_pago(
        db,
        orden_pago_id=op_id,
        caja_id=caja.id,
        fecha_pago_real=date.today(),
        user_id=user.id,
    )

    estado = db.execute(text("SELECT estado FROM ordenes_pago WHERE id = :id"), {"id": op_id}).scalar()
    assert estado == "pagado", "OP single-item cobertura exacta debe quedar pagada"


def test_payload_un_item_con_pago_a_cuenta(db, empresa, proveedor, user, caja):
    """
    Single item + pago_a_cuenta covering diferencia — should confirm and create DAC.
    PR5 UX: user sets pago_a_cuenta explicitly to cover excess → diferencia=0.
    """
    monto_total = 20_000.0
    monto_pedido = 15_000.0
    monto_pac = 5_000.0
    pedido_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=monto_pedido,
        numero="PED-S-002",
    )
    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=monto_total,
        modo_imputacion="mixta",
        numero="OP-S-002",
    )
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[
            {"tipo": "pedido_compra", "id": pedido_id, "monto": monto_pedido},
            {"tipo": "pago_a_cuenta", "id": None, "monto": monto_pac},
        ],
        user_id=user.id,
    )

    ordenes_pago_service.ejecutar_pago(
        db,
        orden_pago_id=op_id,
        caja_id=caja.id,
        fecha_pago_real=date.today(),
        user_id=user.id,
    )

    estado = db.execute(text("SELECT estado FROM ordenes_pago WHERE id = :id"), {"id": op_id}).scalar()
    assert estado == "pagado"

    dac_monto = db.execute(
        text("SELECT monto FROM dinero_a_cuenta WHERE proveedor_id = :pid"),
        {"pid": proveedor.id},
    ).scalar()
    assert Decimal(str(dac_monto)) == Decimal("5000.00"), (
        "pago_a_cuenta debe crear dinero_a_cuenta con el monto correcto"
    )


def test_payload_multi_item_cobertura_exacta(db, empresa, proveedor, user, caja):
    """
    Two items summing exactly to monto_total.
    PR5 UX: multi-item path shows warning but does NOT reset items.
    Backend must still accept after user manually balances.
    """
    pedido1_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=8_000.0,
        numero="PED-S-003a",
    )
    pedido2_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=7_000.0,
        numero="PED-S-003b",
    )
    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=15_000.0,
        numero="OP-S-003",
    )
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[
            {"tipo": "pedido_compra", "id": pedido1_id, "monto": 8_000.0},
            {"tipo": "pedido_compra", "id": pedido2_id, "monto": 7_000.0},
        ],
        user_id=user.id,
    )

    ordenes_pago_service.ejecutar_pago(
        db,
        orden_pago_id=op_id,
        caja_id=caja.id,
        fecha_pago_real=date.today(),
        user_id=user.id,
    )

    estado = db.execute(text("SELECT estado FROM ordenes_pago WHERE id = :id"), {"id": op_id}).scalar()
    assert estado == "pagado"


def test_payload_nc_como_cobertura(db, empresa, proveedor, user, caja):
    """
    NC applied as medio de pago reduces diferencia.
    PR5 UX: NC listed in Medios de pago section — backend invariante still holds.

    Model: monto_total = 10.000 (full OP amount debited from caja).
           items pedido = 7.000, NC = 3.000. Cobertura = 7.000 + 3.000 = 10.000.
    """
    monto_total = 10_000.0
    monto_item_pedido = 7_000.0
    monto_nc = 3_000.0
    pedido_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=monto_total,
        numero="PED-S-004",
    )
    nc = NotaCreditoLocal(
        numero="NC-S-004",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        tipo="credito",
        moneda="ARS",
        monto=Decimal(str(monto_nc)),
        fecha_emision=date.today(),
        motivo="NC test regresion PR5",
        estado="aprobado",
        creado_por_id=user.id,
    )
    db.add(nc)
    db.flush()

    # OP monto_total = full OP; items + NC = full coverage
    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=monto_total,
        numero="OP-S-004",
    )
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[{"tipo": "pedido_compra", "id": pedido_id, "monto": monto_item_pedido}],
        user_id=user.id,
    )

    ordenes_pago_service.ejecutar_pago(
        db,
        orden_pago_id=op_id,
        caja_id=caja.id,
        fecha_pago_real=date.today(),
        ncs_pendientes=[{"nc_id": nc.id, "monto": monto_nc, "pedido_id": pedido_id}],
        user_id=user.id,
    )

    estado = db.execute(text("SELECT estado FROM ordenes_pago WHERE id = :id"), {"id": op_id}).scalar()
    assert estado == "pagado"


def test_payload_dac_como_cobertura(db, empresa, proveedor, user, caja):
    """
    Dinero a cuenta used as medio de pago — consumir path still works post-PR5.
    PR5 UX: DAC listed in Medios de pago section alongside NC/efectivo.

    Model: monto_total = 20.000 (full OP, debited from caja).
           items: pedido_compra monto=12.000 (cash portion) + DAC monto=8.000.
           cobertura = 12.000 + 8.000 = 20.000 == monto_total. Invariante OK.
    """
    monto_total = 20_000.0
    monto_dac = 8_000.0
    monto_efectivo_pedido = 12_000.0

    pedido_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=monto_total,
        numero="PED-S-005",
    )

    # Simulate a previously created DAC (from a prior pago_a_cuenta)
    op_origen_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=monto_dac,
        estado="pagado",
        numero="OP-S-005-orig",
    )
    dac = DineroACuenta(
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        monto=Decimal(str(monto_dac)),
        moneda="ARS",
        estado="disponible",
        origen_op_id=op_origen_id,
        creado_por_id=user.id,
    )
    db.add(dac)
    db.flush()

    # monto_total = 20.000 (caja debits 20.000); items: cash portion + DAC
    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=monto_total,
        numero="OP-S-005",
    )
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[
            {"tipo": "pedido_compra", "id": pedido_id, "monto": monto_efectivo_pedido},
            {
                "tipo": "dinero_a_cuenta",
                "id": dac.id,
                "monto": monto_dac,
                "destino_tipo": "pedido_compra",
                "destino_id": pedido_id,
            },
        ],
        user_id=user.id,
    )

    ordenes_pago_service.ejecutar_pago(
        db,
        orden_pago_id=op_id,
        caja_id=caja.id,
        fecha_pago_real=date.today(),
        user_id=user.id,
    )

    estado = db.execute(text("SELECT estado FROM ordenes_pago WHERE id = :id"), {"id": op_id}).scalar()
    assert estado == "pagado"
    dac_estado = db.execute(text("SELECT estado FROM dinero_a_cuenta WHERE id = :id"), {"id": dac.id}).scalar()
    assert dac_estado == "consumido"


def test_payload_diferencia_cero_gate_rechaza_desbalanceado(db, empresa, proveedor, user, caja):
    """
    Invariante no-diferencia: backend still rejects payloads with diferencia != 0 post-PR5.
    PR5 UX gate is diferencia===0; backend enforces the same in ejecutar_pago.
    """
    from fastapi import HTTPException

    pedido_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=10_000.0,
        numero="PED-S-006",
    )
    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=10_000.0,
        numero="OP-S-006",
    )
    # Items only cover 7000 — diferencia = 3000 != 0
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[{"tipo": "pedido_compra", "id": pedido_id, "monto": 7_000.0}],
        user_id=user.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op_id,
            caja_id=caja.id,
            fecha_pago_real=date.today(),
            user_id=user.id,
        )

    assert exc_info.value.status_code == 422, "Backend debe rechazar con 422 cuando diferencia != 0"
