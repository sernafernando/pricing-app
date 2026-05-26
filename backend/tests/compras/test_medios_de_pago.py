"""
T4.1 — Tests para NC + dinero a cuenta como medios de pago (PR4).

Strict TDD — tests se escriben ANTES del código de producción.

Cobertura:
  - test_consumir_dinero_a_cuenta_no_emite_cc          (AD-4, Risk 1 — GATE TEST)
  - test_invariante_saldo_cc_crear_luego_consumir_dac  (Risk 1 reconciliación)
  - test_consumo_parcial_crea_nuevo_disponible          (AC-4.2, Escenario 4.C)
  - test_consumo_full_marca_consumido                   (AC-4.2)
  - test_nc_como_cobertura_reduce_diferencia            (AC-4.1)
  - test_dinero_a_cuenta_cero_disponible_no_seleccionable (AC-4.4 backend)
  - test_cross_moneda_nc_sin_tc_rechaza                 (AC-4.5)
  - test_whitelist_combos_nuevos                        (FR-4.10)

Patrón de fixtures: sesión SQLite en memoria provista por conftest.py.
Servicios llamados directamente (sin HTTP client).
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
    emp = Empresa(nombre="Empresa MP Test", activo=True)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture()
def proveedor(db) -> Proveedor:
    prov = Proveedor(nombre="Proveedor MP Test", origen="manual", activo=True)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture()
def user(db) -> Usuario:
    u = Usuario(
        username="mp_user",
        email="mp@test.com",
        nombre="MP User",
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
        nombre="Caja MP Test",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("500000"),
        saldo_actual=Decimal("500000"),
        activo=True,
    )
    db.add(c)
    db.flush()
    # Seed del tipo de documento requerido por _registrar_egreso_en_fuente.
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
    moneda: str = "ARS",
    numero: str = "OP-MP-001",
    estado: str = "pendiente",
    modo_imputacion: str = "especifica",
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
    numero: str = "PED-MP-001",
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
    """Inserta un evento 'items_registrados' con los items como payload."""
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


def _crear_dac_disponible(
    db,
    *,
    proveedor_id: int,
    empresa_id: int,
    user_id: int,
    monto: float,
    moneda: str = "ARS",
    numero_op: str = "OP-DAC-SRC-001",
) -> DineroACuenta:
    """
    Crea un DineroACuenta disponible usando ordenes_pago_service.ejecutar_pago
    con item pago_a_cuenta, para que el haber ya esté en CC.
    Retorna la fila DineroACuenta creada.
    """
    from app.services import dinero_a_cuenta_service, ordenes_pago_service

    ped_id = _insert_pedido(
        db,
        empresa_id=empresa_id,
        proveedor_id=proveedor_id,
        user_id=user_id,
        monto=monto * 2,  # el pedido es más grande — solo pagamos parte
        numero=f"PED-DAC-SRC-{numero_op}",
        moneda=moneda,
    )
    op_id = _insert_op(
        db,
        empresa_id=empresa_id,
        proveedor_id=proveedor_id,
        user_id=user_id,
        monto_total=monto * 2,
        moneda=moneda,
        numero=numero_op,
    )
    # Items: un pedido parcial + pago_a_cuenta para cerrar diferencia.
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[
            {"tipo": "pedido_compra", "id": ped_id, "monto": monto},
            {"tipo": "pago_a_cuenta", "id": None, "monto": monto},
        ],
        user_id=user_id,
    )

    # Necesitamos caja para ejecutar pago — la usamos solo si moneda ARS.
    # Crear caja temporal para este helper.
    from app.models.caja import Caja, CajaTipoDocumento

    caja_tmp = Caja(
        nombre=f"Caja tmp {numero_op}",
        empresa_id=empresa_id,
        moneda=moneda,
        saldo_inicial=Decimal(str(monto * 10)),
        saldo_actual=Decimal(str(monto * 10)),
        activo=True,
    )
    db.add(caja_tmp)
    db.flush()

    # Verificar si ya existe tipo documento
    existing_td = db.execute(
        text("SELECT id FROM caja_tipo_documentos WHERE nombre = 'Orden de Pago' LIMIT 1")
    ).scalar()
    if not existing_td:
        td = CajaTipoDocumento(nombre="Orden de Pago")
        db.add(td)
        db.flush()

    ordenes_pago_service.ejecutar_pago(
        db,
        orden_pago_id=op_id,
        caja_id=caja_tmp.id,
        fecha_pago_real=date(2026, 1, 1),
        user_id=user_id,
    )

    dacs = dinero_a_cuenta_service.listar_por_proveedor(
        db,
        proveedor_id=proveedor_id,
        moneda=moneda,
        estado="disponible",
    )
    assert len(dacs) >= 1, "No se creó el DineroACuenta esperado"
    return dacs[-1]


# ──────────────────────────────────────────────────────────────────────────
# GATE TEST — AD-4: consumir DAC no emite movimiento CC
# ──────────────────────────────────────────────────────────────────────────


def test_consumir_dinero_a_cuenta_no_emite_cc(db, empresa, proveedor, user) -> None:
    """
    AD-4 / Risk 1 — GATE TEST (PR4).

    Consumir dinero a cuenta para cubrir un pedido NO debe emitir un nuevo
    movimiento cc_proveedor_movimiento. El haber ya entró al CC cuando se
    creó el DAC (pago_a_cuenta en ejecutar_pago, PR3). Emitir otro haber
    aquí sería doble conteo.

    Flujo:
      1. Crear DAC disponible (vía ejecutar_pago con pago_a_cuenta).
      2. Contar movimientos CC del proveedor ANTES de consumir.
      3. Consumir DAC en un nuevo pedido.
      4. Contar movimientos CC DESPUÉS — debe ser igual a ANTES.
    """
    from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
    from app.services import dinero_a_cuenta_service

    dac = _crear_dac_disponible(
        db,
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        user_id=user.id,
        monto=5000,
        numero_op="OP-GATE-001",
    )

    # Contar movimientos CC antes del consumo
    movs_antes = db.query(CCProveedorMovimiento).filter(CCProveedorMovimiento.proveedor_id == proveedor.id).count()

    # Crear pedido destino para el consumo
    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=5000,
        numero="PED-GATE-DST-001",
    )

    # Consumir el DAC (PR4 — T4.3)
    imputacion = dinero_a_cuenta_service.consumir(
        db,
        dinero_a_cuenta_id=dac.id,
        destino_tipo="pedido_compra",
        destino_id=ped_id,
        monto=Decimal("5000"),
        user_id=user.id,
    )

    # Verificar que se creó la imputación correcta
    assert imputacion is not None
    assert imputacion.origen_tipo == "dinero_a_cuenta"
    assert imputacion.origen_id == dac.id
    assert imputacion.destino_tipo == "pedido_compra"
    assert imputacion.destino_id == ped_id

    # CRÍTICO: el número de movimientos CC NO debe haber aumentado (AD-4)
    movs_despues = db.query(CCProveedorMovimiento).filter(CCProveedorMovimiento.proveedor_id == proveedor.id).count()
    assert movs_despues == movs_antes, (
        f"AD-4 VIOLADO: consumir DAC emitió {movs_despues - movs_antes} "
        f"movimiento(s) CC extra (doble conteo). "
        f"El haber ya está en CC desde la creación del DAC."
    )


# ──────────────────────────────────────────────────────────────────────────
# Risk 1 — reconciliación: saldo CC igual a pago directo
# ──────────────────────────────────────────────────────────────────────────


def test_invariante_saldo_cc_crear_luego_consumir_dac(db, empresa, proveedor, user) -> None:
    """
    Risk 1 reconciliación (AD-4): consumir un DAC NO debe modificar el saldo CC.

    El haber ya entró al CC cuando se creó el DAC (vía pago_a_cuenta en PR3).
    Consumir el DAC en un pedido es una reasignación interna — el saldo neto
    del CC proveedor no debe cambiar. Si cambia → doble conteo.

    Flujo:
      1. Crear DAC (ejecutar_pago con pago_a_cuenta) — saldo CC registrado.
      2. Capturar saldo CC ANTES del consumo.
      3. Consumir DAC en un pedido.
      4. Saldo CC DESPUÉS == saldo CC ANTES (invariante no-cambio).
    """
    from app.services import cc_proveedor_service, dinero_a_cuenta_service

    dac = _crear_dac_disponible(
        db,
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        user_id=user.id,
        monto=5000,
        numero_op="OP-RECON-001",
    )

    # Capturar saldo CC ANTES del consumo
    saldos_antes = cc_proveedor_service.calcular_saldo_por_moneda(db, proveedor_id=proveedor.id)
    saldo_antes = saldos_antes.get("ARS", Decimal("0"))

    # Crear pedido destino del consumo
    ped2_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=5000,
        numero="PED-RECON-002",
    )

    # Consumir el DAC en el segundo pedido
    dinero_a_cuenta_service.consumir(
        db,
        dinero_a_cuenta_id=dac.id,
        destino_tipo="pedido_compra",
        destino_id=ped2_id,
        monto=Decimal("5000"),
        user_id=user.id,
    )

    # Saldo CC DESPUÉS del consumo — debe ser idéntico al ANTES (AD-4).
    saldos_despues = cc_proveedor_service.calcular_saldo_por_moneda(db, proveedor_id=proveedor.id)
    saldo_despues = saldos_despues.get("ARS", Decimal("0"))

    assert saldo_despues == saldo_antes, (
        f"AD-4 VIOLADO: saldo CC cambió al consumir DAC. "
        f"Antes={saldo_antes}, Después={saldo_despues}. "
        f"El consumo emitió un movimiento CC extra (doble conteo)."
    )


# ──────────────────────────────────────────────────────────────────────────
# AC-4.2 / Escenario 4.C — Consumo parcial: se crea nuevo disponible
# ──────────────────────────────────────────────────────────────────────────


def test_consumo_parcial_crea_nuevo_disponible(db, empresa, proveedor, user) -> None:
    """
    AC-4.2 / Escenario 4.C:
    DAC disponible ARS 10.000. OP usa ARS 7.000.
    Después del consumo: DAC original → consumido; saldo disponible = ARS 3.000.

    PR4 implementa consumo parcial actualizando el estado cache del DAC.
    El saldo disponible derivado debe reflejar el remanente.
    """
    from app.services import dinero_a_cuenta_service

    dac = _crear_dac_disponible(
        db,
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        user_id=user.id,
        monto=10000,
        numero_op="OP-PARCIAL-001",
    )

    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=7000,
        numero="PED-PARCIAL-001",
    )

    # Consumir parcialmente: 7.000 de 10.000 disponibles
    dinero_a_cuenta_service.consumir(
        db,
        dinero_a_cuenta_id=dac.id,
        destino_tipo="pedido_compra",
        destino_id=ped_id,
        monto=Decimal("7000"),
        user_id=user.id,
    )

    # DAC original debe tener saldo disponible = 3.000 (derivado)
    saldo_restante = dinero_a_cuenta_service.calcular_saldo_disponible(db, dac.id)
    assert saldo_restante == Decimal("3000"), f"Saldo disponible esperado: 3.000. Obtenido: {saldo_restante}."

    # Estado debe ser 'consumido_parcial'
    db.refresh(dac)
    assert dac.estado == "consumido_parcial", f"Estado esperado: 'consumido_parcial'. Obtenido: '{dac.estado}'."


# ──────────────────────────────────────────────────────────────────────────
# AC-4.2 — Consumo total marca consumido
# ──────────────────────────────────────────────────────────────────────────


def test_consumo_full_marca_consumido(db, empresa, proveedor, user) -> None:
    """
    AC-4.2 / Escenario 4.A:
    DAC disponible ARS 5.000. OP usa ARS 5.000 completos.
    Después del consumo: DAC estado → 'consumido', saldo = 0.
    """
    from app.services import dinero_a_cuenta_service

    dac = _crear_dac_disponible(
        db,
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        user_id=user.id,
        monto=5000,
        numero_op="OP-FULL-001",
    )

    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=5000,
        numero="PED-FULL-001",
    )

    dinero_a_cuenta_service.consumir(
        db,
        dinero_a_cuenta_id=dac.id,
        destino_tipo="pedido_compra",
        destino_id=ped_id,
        monto=Decimal("5000"),
        user_id=user.id,
    )

    saldo = dinero_a_cuenta_service.calcular_saldo_disponible(db, dac.id)
    assert saldo == Decimal("0")

    db.refresh(dac)
    assert dac.estado == "consumido"


# ──────────────────────────────────────────────────────────────────────────
# AC-4.1 — NC como cobertura reduce la diferencia
# ──────────────────────────────────────────────────────────────────────────


def test_nc_como_cobertura_reduce_diferencia(db, empresa, proveedor, user, caja) -> None:
    """
    AC-4.1: una NC local aplicada en ncs_aplicadas cuenta en cobertura_total.
    OP monto_total=10.000, items pedido=7.000, NC=3.000 → diferencia=0 → se confirma.

    Verifica que validar_balance_op acepta la cobertura NC y que la OP
    llega a estado 'pagado'.
    """
    from app.services import ordenes_pago_service

    # Crear pedido de 7.000
    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=10_000,
        numero="PED-NC-001",
    )

    # Crear NC local de 3.000 ARS aprobada
    from app.models.nota_credito_local import NotaCreditoLocal

    nc = NotaCreditoLocal(
        numero="NC-MP-001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        tipo="credito",
        moneda="ARS",
        monto=Decimal("3000"),
        fecha_emision=date(2026, 1, 1),
        motivo="Test NC cobertura",
        estado="aprobado",
        creado_por_id=user.id,
    )
    db.add(nc)
    db.flush()
    nc_id = nc.id

    # Crear OP de 10.000 ARS
    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=10_000,
        numero="OP-NC-001",
    )

    # Items: pedido 7.000
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[{"tipo": "pedido_compra", "id": ped_id, "monto": 7_000}],
        user_id=user.id,
    )

    # Ejecutar pago con NC de 3.000 → diferencia = 0
    op = ordenes_pago_service.ejecutar_pago(
        db,
        orden_pago_id=op_id,
        caja_id=caja.id,
        fecha_pago_real=date(2026, 1, 1),
        user_id=user.id,
        ncs_pendientes=[{"nc_id": int(nc_id), "monto": 3000, "pedido_id": ped_id}],
    )

    assert op.estado == "pagado", f"La OP debería estar 'pagado' con NC como cobertura. Estado: '{op.estado}'."


# ──────────────────────────────────────────────────────────────────────────
# AC-4.4 — DAC sin saldo disponible: query retorna 0
# ──────────────────────────────────────────────────────────────────────────


def test_dinero_a_cuenta_cero_disponible_no_seleccionable(db, empresa, proveedor, user) -> None:
    """
    AC-4.4 backend: si el proveedor no tiene DAC disponible en ARS,
    calcular_componente_dinero_a_cuenta retorna 0 (no seleccionable).
    """
    from app.services.dinero_a_cuenta_service import calcular_componente_dinero_a_cuenta

    # Sin DAC registrado → componente = 0
    componente = calcular_componente_dinero_a_cuenta(db, proveedor_id=proveedor.id, moneda="ARS")
    assert componente == Decimal("0"), f"Con DAC vacío, componente debería ser 0. Obtenido: {componente}."


# ──────────────────────────────────────────────────────────────────────────
# AC-4.5 — Cross-moneda NC sin TC rechaza
# ──────────────────────────────────────────────────────────────────────────


def test_cross_moneda_nc_sin_tc_rechaza(db, empresa, proveedor, user, caja) -> None:
    """
    AC-4.5: NC en USD aplicada a OP ARS sin TC debe fallar.
    El backend rechaza la imputación cross-moneda sin tipo_cambio.
    """
    from fastapi import HTTPException

    from app.services import ordenes_pago_service

    # Pedido ARS
    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=10_000,
        moneda="ARS",
        numero="PED-CROSSNC-001",
    )

    # NC en USD
    from app.models.nota_credito_local import NotaCreditoLocal

    nc_usd = NotaCreditoLocal(
        numero="NC-USD-001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        tipo="credito",
        moneda="USD",
        monto=Decimal("100"),
        fecha_emision=date(2026, 1, 1),
        motivo="Test NC USD cross-moneda",
        estado="aprobado",
        creado_por_id=user.id,
    )
    db.add(nc_usd)
    db.flush()
    nc_usd_id = nc_usd.id

    # OP ARS de 10.000 con NC USD sin TC → debe rechazar cross-moneda
    op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=10_000,
        moneda="ARS",
        numero="OP-CROSSNC-001",
    )
    _seed_evento_items(
        db,
        op_id=op_id,
        items=[{"tipo": "pedido_compra", "id": ped_id, "monto": 10_000}],
        user_id=user.id,
    )

    # Sin TC → el backend debe rechazar la NC cross-moneda
    # La NC USD no tiene valor en ARS sin tipo_cambio definido.
    # El servicio debería rechazar con 400/422 porque la cobertura NC
    # no se puede computar en ARS (cross-moneda sin TC).
    with pytest.raises((HTTPException, ValueError)):
        ordenes_pago_service.ejecutar_pago(
            db,
            orden_pago_id=op_id,
            caja_id=caja.id,
            fecha_pago_real=date(2026, 1, 1),
            user_id=user.id,
            ncs_pendientes=[{"nc_id": int(nc_usd_id), "monto": 100, "pedido_id": ped_id}],
        )


# ──────────────────────────────────────────────────────────────────────────
# FR-4.10 — Whitelist combos nuevos aceptados
# ──────────────────────────────────────────────────────────────────────────


def test_whitelist_combos_nuevos(db) -> None:
    """
    FR-4.10: los combos ('dinero_a_cuenta','pedido_compra') y
    ('dinero_a_cuenta','factura_erp') deben estar en COMBOS_VALIDOS_V1.
    """
    from app.services.imputaciones_service import COMBOS_VALIDOS_V1

    assert ("dinero_a_cuenta", "pedido_compra") in COMBOS_VALIDOS_V1, (
        "Combo ('dinero_a_cuenta','pedido_compra') no está en COMBOS_VALIDOS_V1. Agregar en T4.2."
    )
    assert ("dinero_a_cuenta", "factura_erp") in COMBOS_VALIDOS_V1, (
        "Combo ('dinero_a_cuenta','factura_erp') no está en COMBOS_VALIDOS_V1. Agregar en T4.2."
    )


# ──────────────────────────────────────────────────────────────────────────
# WARNING 1 — Cross-moneda DAC sin TC rechaza (FR-4.9)
# ──────────────────────────────────────────────────────────────────────────


def test_cross_moneda_dac_sin_tc_rechaza(db, empresa, proveedor, user) -> None:
    """
    WARNING 1 (AC-W1): DAC en USD consumido en OP ARS sin tipo_cambio → 422.
    Simétrico a test_cross_moneda_nc_sin_tc_rechaza (AC-4.5).
    El guard se aplica en consumir() vía op_moneda + op_tipo_cambio.
    """
    from decimal import Decimal

    from fastapi import HTTPException

    from app.services import dinero_a_cuenta_service

    # OP stub en USD para satisfacer la FK origen_op_id del DAC.
    stub_op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=100,
        moneda="USD",
        numero="OP-W1-SRC-001",
    )

    dac = DineroACuenta(
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        monto=Decimal("100"),
        moneda="USD",
        estado="disponible",
        origen_op_id=stub_op_id,
        creado_por_id=user.id,
    )
    db.add(dac)
    db.flush()

    # Pedido ARS destino
    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=50_000,
        moneda="ARS",
        numero="PED-W1-001",
    )

    # consumir con op_moneda=ARS y sin TC → debe rechazar
    with pytest.raises(HTTPException) as exc_info:
        dinero_a_cuenta_service.consumir(
            db,
            dinero_a_cuenta_id=dac.id,
            destino_tipo="pedido_compra",
            destino_id=ped_id,
            monto=Decimal("50"),
            user_id=user.id,
            op_proveedor_id=proveedor.id,
            op_moneda="ARS",
            op_tipo_cambio=None,  # sin TC → cross-moneda inválido
        )
    assert exc_info.value.status_code == 422
    assert "cross-moneda" in exc_info.value.detail.lower() or "tipo_cambio" in exc_info.value.detail.lower()


# ──────────────────────────────────────────────────────────────────────────
# WARNING 2 — with_for_update: consumir sigue funcionando con el lock
# ──────────────────────────────────────────────────────────────────────────


def test_consumir_con_lock_funciona(db, empresa, proveedor, user) -> None:
    """
    WARNING 2: verificar que el SELECT FOR UPDATE en consumir() no rompe
    el flujo normal. SQLite no soporta row-level locking real pero no falla.
    """
    from decimal import Decimal

    from app.services import dinero_a_cuenta_service

    stub_op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto_total=500,
        moneda="ARS",
        numero="OP-W2-SRC-001",
    )

    dac = DineroACuenta(
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        monto=Decimal("500"),
        moneda="ARS",
        estado="disponible",
        origen_op_id=stub_op_id,
        creado_por_id=user.id,
    )
    db.add(dac)
    db.flush()

    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        user_id=user.id,
        monto=500,
        moneda="ARS",
        numero="PED-W2-001",
    )

    # Debe funcionar sin error — el FOR UPDATE es transparente en SQLite
    imputacion = dinero_a_cuenta_service.consumir(
        db,
        dinero_a_cuenta_id=dac.id,
        destino_tipo="pedido_compra",
        destino_id=ped_id,
        monto=Decimal("200"),
        user_id=user.id,
        op_proveedor_id=proveedor.id,
        op_moneda="ARS",
        op_tipo_cambio=None,
    )
    assert imputacion is not None
    saldo = dinero_a_cuenta_service.calcular_saldo_disponible(db, dac.id)
    assert saldo == Decimal("300")


# ──────────────────────────────────────────────────────────────────────────
# WARNING 3 — Proveedor cruzado rechaza (defensa en profundidad)
# ──────────────────────────────────────────────────────────────────────────


def test_consumir_proveedor_cruzado_rechaza(db, empresa, user) -> None:
    """
    WARNING 3 (AC-W3): DAC de proveedor A consumido en OP de proveedor B → 422.
    La consistencia proveedor DAC↔OP es obligatoria para que las imputaciones
    aterricen en el CC correcto.
    """
    from decimal import Decimal

    from fastapi import HTTPException

    from app.services import dinero_a_cuenta_service

    prov_a = Proveedor(nombre="Proveedor A W3", origen="manual", activo=True)
    prov_b = Proveedor(nombre="Proveedor B W3", origen="manual", activo=True)
    db.add(prov_a)
    db.add(prov_b)
    db.flush()

    # OP stub para FK origen_op_id (proveedor A)
    stub_op_id = _insert_op(
        db,
        empresa_id=empresa.id,
        proveedor_id=prov_a.id,
        user_id=user.id,
        monto_total=1000,
        moneda="ARS",
        numero="OP-W3-SRC-001",
    )

    # DAC de proveedor A
    dac = DineroACuenta(
        proveedor_id=prov_a.id,
        empresa_id=empresa.id,
        monto=Decimal("1000"),
        moneda="ARS",
        estado="disponible",
        origen_op_id=stub_op_id,
        creado_por_id=user.id,
    )
    db.add(dac)
    db.flush()

    # Pedido de proveedor B
    ped_id = _insert_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=prov_b.id,
        user_id=user.id,
        monto=1000,
        moneda="ARS",
        numero="PED-W3-001",
    )

    # Intentar consumir DAC de prov_a en OP de prov_b → 422
    with pytest.raises(HTTPException) as exc_info:
        dinero_a_cuenta_service.consumir(
            db,
            dinero_a_cuenta_id=dac.id,
            destino_tipo="pedido_compra",
            destino_id=ped_id,
            monto=Decimal("500"),
            user_id=user.id,
            op_proveedor_id=prov_b.id,  # distinto al dac.proveedor_id
            op_moneda="ARS",
            op_tipo_cambio=None,
        )
    assert exc_info.value.status_code == 422
    assert str(prov_a.id) in exc_info.value.detail or "proveedor" in exc_info.value.detail.lower()
