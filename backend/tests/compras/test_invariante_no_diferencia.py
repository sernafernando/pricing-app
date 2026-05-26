"""
T3.1 — Tests para el invariante no-diferencia (AC-3.1..AC-3.6, Escenarios 3.A/3.B/3.C).

Strict TDD — estos tests se escriben ANTES del código de producción.

Cobertura:
  - test_op_pendiente_no_balanceada_se_puede_editar         (AC-3.4)
  - test_confirmacion_rechaza_diferencia_no_cero             (AC-3.1, Escenario 3.C)
  - test_confirmacion_rechaza_over_allocation                (AC-3.6)
  - test_confirmacion_acepta_diferencia_cero_exacto          (AC-3.3, Escenario 3.B)
  - test_pago_a_cuenta_crea_dinero_a_cuenta                  (AC-3.2, Escenario 3.A)
  - test_no_pago_a_cuenta_no_crea_dinero_a_cuenta            (AC-3.3)
  - test_escenario_3a_mixta_con_pago_a_cuenta                (Escenario 3.A numérico)
  - test_escenario_3b_cobertura_exacta                       (Escenario 3.B numérico)
  - test_escenario_3c_rechazo_diferencia_positiva            (Escenario 3.C numérico)

Patrón de fixtures: sesión SQLite en memoria provista por conftest.py.
Las OPs se crean vía raw INSERT (igual a op_stub de test_dinero_a_cuenta_service.py)
para no depender del router, luego ejecutar_pago se llama directamente.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models.caja import Caja, CajaTipoDocumento
from app.models.dinero_a_cuenta import DineroACuenta
from app.models.empresa import Empresa
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import Proveedor
from app.models.usuario import AuthProvider, RolUsuario, Usuario


# ──────────────────────────────────────────────────────────────────────────
# Fixtures base
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def empresa(db) -> Empresa:
    emp = Empresa(nombre="Empresa Inv Test", activo=True)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture()
def proveedor(db) -> Proveedor:
    prov = Proveedor(nombre="Proveedor Inv Test", origen="manual", activo=True)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture()
def user(db) -> Usuario:
    u = Usuario(
        username="inv_user",
        email="inv@test.com",
        nombre="Inv User",
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
    """Caja ARS con saldo suficiente para ejecutar pagos en tests."""
    c = Caja(
        nombre="Caja Inv Test",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("100000"),
        saldo_actual=Decimal("100000"),
        activo=True,
    )
    db.add(c)
    db.flush()
    # Seed del tipo de documento requerido por _registrar_egreso_en_fuente.
    # El nombre debe coincidir con TIPO_DOC_ORDEN_PAGO = "Orden de Pago".
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
    numero: str = "OP-INV-001",
    estado: str = "pendiente",
) -> int:
    """Inserta una OP mínima y devuelve su id."""
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
    op_id = db.execute(text("SELECT last_insert_rowid()")).scalar()
    return int(op_id)


def _insert_pedido(
    db,
    *,
    empresa_id: int,
    proveedor_id: int,
    user_id: int,
    monto: float,
    moneda: str = "ARS",
    numero: str = "PED-INV-001",
    estado: str = "aprobado",
) -> int:
    """Inserta un pedido de compra aprobado y devuelve su id."""
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
    """
    Inserta un evento 'items_registrados' con los items como payload,
    simulando lo que hace ordenes_pago_service.crear() (usa _registrar_evento
    con tipo EVENTO_ITEMS_REGISTRADOS = 'items_registrados').
    """
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
# AC-3.4 — Draft editables (el invariante NO se aplica al crear/editar)
# ──────────────────────────────────────────────────────────────────────────


def test_op_pendiente_no_balanceada_se_puede_editar(db, empresa, proveedor, user) -> None:
    """
    Una OP en estado 'pendiente' con diferencia != 0 puede crearse y actualizarse
    sin error. El invariante solo se aplica al confirmar (ejecutar_pago).
    """
    from app.services import ordenes_pago_service

    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=10_000,
        numero="PED-AC34-001",
    )

    # Crear OP con items que suman MENOS que monto_total (diferencia != 0).
    # Esto no debe lanzar excepción — los drafts son editables.
    op = ordenes_pago_service.crear(
        db,
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        moneda="ARS",
        monto_total=Decimal("10000"),
        modo_imputacion="mixta",
        items=[{"tipo": "pedido_compra", "id": ped_id, "monto": 8000}],
        creado_por_id=user.id,
    )
    assert op.estado == "pendiente"
    # No se lanzó excepción → draft aceptado con diferencia != 0.


# ──────────────────────────────────────────────────────────────────────────
# AC-3.1 / Escenario 3.C — Rechazo confirmación con diferencia != 0
# ──────────────────────────────────────────────────────────────────────────


def test_confirmacion_rechaza_diferencia_no_cero(db, empresa, proveedor, user, caja) -> None:
    """
    Confirmar una OP donde la cobertura (items pedido) < monto_total → 422.
    Escenario 3.C: monto_total=15.000, items=12.000, diferencia=3.000 → rechazo.
    """
    from fastapi import HTTPException

    from app.services import ordenes_pago_service

    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=15_000,
        numero="PED-3C-001",
    )

    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=15_000,
        modo_imputacion="mixta",
        numero="OP-3C-001",
    )
    # Items cubren solo 12.000 → diferencia = 3.000 != 0
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[{"tipo": "pedido_compra", "id": ped_id, "monto": 12_000}],
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
    assert "diferencia" in exc_info.value.detail.lower() or "balancea" in exc_info.value.detail.lower()


# ──────────────────────────────────────────────────────────────────────────
# AC-3.6 — Over-allocation también se rechaza (diferencia < 0)
# ──────────────────────────────────────────────────────────────────────────


def test_confirmacion_rechaza_over_allocation(db, empresa, proveedor, user, caja) -> None:
    """
    Cobertura total > monto_total también es diferencia != 0 → 422.
    monto_total=10.000, items pedido=10.000, pago_a_cuenta=2.000 → cobertura=12.000.
    """
    from fastapi import HTTPException

    from app.services import ordenes_pago_service

    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=10_000,
        numero="PED-OA-001",
    )

    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=10_000,
        modo_imputacion="especifica",
        numero="OP-OA-001",
    )
    # items pedido 10.000 + pago_a_cuenta 2.000 = 12.000 > 10.000 (over-allocation)
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[
            {"tipo": "pedido_compra", "id": ped_id, "monto": 10_000},
            {"tipo": "pago_a_cuenta", "id": None, "monto": 2_000},
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


# ──────────────────────────────────────────────────────────────────────────
# AC-3.3 / Escenario 3.B — Diferencia cero exacto (cobertura completa, sin pago_a_cuenta)
# ──────────────────────────────────────────────────────────────────────────


def test_confirmacion_acepta_diferencia_cero_exacto(db, empresa, proveedor, user, caja) -> None:
    """
    OP con cobertura exacta → confirma correctamente, sin crear dinero_a_cuenta.
    Escenario 3.B: monto_total=15.000, item=15.000 → Diferencia=0 → pagado.
    """
    from app.services import ordenes_pago_service

    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=15_000,
        numero="PED-3B-001",
    )

    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=15_000,
        modo_imputacion="especifica",
        numero="OP-3B-001",
    )
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[{"tipo": "pedido_compra", "id": ped_id, "monto": 15_000}],
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
    # Sin dinero_a_cuenta creado
    dac_count = db.query(DineroACuenta).filter(DineroACuenta.origen_op_id == op_id).count()
    assert dac_count == 0


# ──────────────────────────────────────────────────────────────────────────
# AC-3.2 / Escenario 3.A — pago_a_cuenta crea DineroACuenta en confirmación
# ──────────────────────────────────────────────────────────────────────────


def test_pago_a_cuenta_crea_dinero_a_cuenta(db, empresa, proveedor, user, caja) -> None:
    """
    OP con item pago_a_cuenta=2.000 + pedido=8.000 (total=10.000) → en confirmación
    se crea una fila DineroACuenta disponible de ARS 2.000.
    """
    from app.services import ordenes_pago_service

    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=10_000,
        numero="PED-PAC-001",
    )

    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=10_000,
        modo_imputacion="mixta",
        numero="OP-PAC-001",
    )
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[
            {"tipo": "pedido_compra", "id": ped_id, "monto": 8_000},
            {"tipo": "pago_a_cuenta", "id": None, "monto": 2_000},
        ],
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

    # Debe existir exactamente un DineroACuenta disponible de 2.000 ARS.
    dacs = db.query(DineroACuenta).filter(DineroACuenta.origen_op_id == op_id).all()
    assert len(dacs) == 1
    dac = dacs[0]
    assert dac.monto == Decimal("2000")
    assert dac.moneda == "ARS"
    assert dac.estado == "disponible"
    assert dac.proveedor_id == proveedor.id
    assert dac.empresa_id == empresa.id


# ──────────────────────────────────────────────────────────────────────────
# AC-3.3 — Sin pago_a_cuenta no se crea DineroACuenta
# ──────────────────────────────────────────────────────────────────────────


def test_no_pago_a_cuenta_no_crea_dinero_a_cuenta(db, empresa, proveedor, user, caja) -> None:
    """
    Cobertura exacta sin pago_a_cuenta → ninguna fila DineroACuenta creada.
    """
    from app.services import ordenes_pago_service

    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=10_000,
        numero="PED-NOPAC-001",
    )

    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=10_000,
        modo_imputacion="especifica",
        numero="OP-NOPAC-001",
    )
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[{"tipo": "pedido_compra", "id": ped_id, "monto": 10_000}],
        user_id=user.id,
    )

    ordenes_pago_service.ejecutar_pago(
        db,
        orden_pago_id=op_id,
        caja_id=caja.id,
        fecha_pago_real=date(2026, 1, 1),
        user_id=user.id,
    )

    dac_count = db.query(DineroACuenta).filter(DineroACuenta.origen_op_id == op_id).count()
    assert dac_count == 0


# ──────────────────────────────────────────────────────────────────────────
# Escenario 3.A numérico — cobertura parcial + pago_a_cuenta
# ──────────────────────────────────────────────────────────────────────────


def test_escenario_3a_mixta_con_pago_a_cuenta(db, empresa, proveedor, user, caja) -> None:
    """
    Escenario 3.A:
      monto_total = 15.000 ARS
      pedido A   = 10.000 ARS
      pedido B   =  3.000 ARS
      pago_a_cuenta = 2.000 ARS
      cobertura = 15.000 → Diferencia = 0 → pagado + DAC creado
    """
    from app.services import ordenes_pago_service

    ped_a = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=10_000,
        numero="PED-3A-A",
    )
    ped_b = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=3_000,
        numero="PED-3A-B",
    )

    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=15_000,
        modo_imputacion="mixta",
        numero="OP-3A-001",
    )
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[
            {"tipo": "pedido_compra", "id": ped_a, "monto": 10_000},
            {"tipo": "pedido_compra", "id": ped_b, "monto": 3_000},
            {"tipo": "pago_a_cuenta", "id": None, "monto": 2_000},
        ],
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
    dacs = db.query(DineroACuenta).filter(DineroACuenta.origen_op_id == op_id).all()
    assert len(dacs) == 1
    assert dacs[0].monto == Decimal("2000")
    assert dacs[0].estado == "disponible"


# ──────────────────────────────────────────────────────────────────────────
# Escenario 3.B numérico — cobertura exacta
# ──────────────────────────────────────────────────────────────────────────


def test_escenario_3b_cobertura_exacta(db, empresa, proveedor, user, caja) -> None:
    """
    Escenario 3.B:
      monto_total = 15.000, pedido A = 15.000 → Diferencia = 0 → pagado, sin DAC.
    """
    from app.services import ordenes_pago_service

    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=15_000,
        numero="PED-3B-2",
    )
    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=15_000,
        modo_imputacion="especifica",
        numero="OP-3B-002",
    )
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[{"tipo": "pedido_compra", "id": ped_id, "monto": 15_000}],
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
    assert db.query(DineroACuenta).filter(DineroACuenta.origen_op_id == op_id).count() == 0


# ──────────────────────────────────────────────────────────────────────────
# Escenario 3.C numérico — rechazo diferencia positiva
# ──────────────────────────────────────────────────────────────────────────


def test_escenario_3c_rechazo_diferencia_positiva(db, empresa, proveedor, user, caja) -> None:
    """
    Escenario 3.C:
      monto_total = 15.000, items = 12.000 → diferencia = 3.000 → 422.
    """
    from fastapi import HTTPException

    from app.services import ordenes_pago_service

    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=15_000,
        numero="PED-3C-2",
    )
    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=15_000,
        modo_imputacion="mixta",
        numero="OP-3C-002",
    )
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[{"tipo": "pedido_compra", "id": ped_id, "monto": 12_000}],
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
