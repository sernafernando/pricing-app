"""
Test — CC por pedido: varianza_tc_neta / varianza_tc_pendiente en endpoint.

REQ-FX-CC-001: GET /cc-proveedor/{id}/por-pedido debe incluir los campos
varianza_tc_neta y varianza_tc_pendiente por cada grupo.

REQ-FX-CC-002: Un pedido USD pagado en ARS a TC distinto al original debe
devolver varianza_tc_neta != 0 y varianza_tc_pendiente = True en la respuesta.

TDD strict — tests written BEFORE the implementation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.tipo_cambio import TipoCambio
from app.models.usuario import Usuario  # noqa: F401 (type hint only — fixture from conftest)

BASE = "/api/administracion/compras"

_seq = 0


def _next_num(prefix: str = "PC") -> str:
    global _seq
    _seq += 1
    return f"{prefix}-CCFX-{_seq:04d}"


@pytest.fixture
def con_permisos():
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=True),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(nombre="Empresa CC FX Test", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        nombre="Proveedor CC FX",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=88801,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def tc_rows(db) -> None:
    """TC USD: 1000 on day 1, 1400 on day 2."""
    db.add(TipoCambio(fecha=date(2026, 2, 1), moneda="USD", compra=Decimal("1000"), venta=Decimal("1010")))
    db.add(TipoCambio(fecha=date(2026, 2, 2), moneda="USD", compra=Decimal("1400"), venta=Decimal("1410")))
    db.flush()


def _build_usd_pedido_con_varianza(
    db,
    empresa: Empresa,
    proveedor: Proveedor,
    user_id: int,
    *,
    tc_orig: Decimal,
    tc_pago: Decimal,
    monto_usd: Decimal = Decimal("100"),
) -> PedidoCompra:
    """
    Crea el escenario completo: pedido USD + DEBE en CC + OrdenPago ARS a TC distinto
    + Imputacion caso-B + HABER en CC.

    Para que calcular_varianza_tc_batch lo detecte como Caso-B necesita:
      - PedidoCompra con moneda=USD, tipo_cambio_original=tc_orig
      - OrdenPago con moneda=ARS, tipo_cambio=tc_pago
      - Imputacion con origen_tipo='orden_pago', destino_tipo='pedido_compra'
        (tc efectivo se resuelve via resolver_tc_efectivo_pedido_batch que
         prioriza tipo_cambio_manual → None, luego usa TC histórico del día de pago)
      - CCProveedorMovimiento DEBE (origen_tipo='pedido_compra') y HABER (origen_tipo='imputacion')
    """
    pedido = PedidoCompra(
        numero=_next_num("PC"),
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="USD",
        monto=monto_usd,
        tipo_cambio=tc_orig,
        tipo_cambio_original=tc_orig,
        tipo_cambio_manual=tc_pago,  # TC efectivo que usó el pago
        estado="pagado",
        creado_por_id=user_id,
    )
    db.add(pedido)
    db.flush()

    # DEBE en CC
    debe_mov = CCProveedorMovimiento(
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        fecha_movimiento=date(2026, 2, 1),
        tipo="debe",
        monto=monto_usd,
        moneda="USD",
        tipo_cambio_a_ars=tc_orig,
        origen_tipo="pedido_compra",
        origen_id=pedido.id,
        descripcion=f"DEBE {pedido.numero}",
        creado_por_id=user_id,
    )
    db.add(debe_mov)
    db.flush()

    # OrdenPago ARS (Caso-B: pagó en pesos a TC diferente)
    op = OrdenPago(
        numero=_next_num("OP"),
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto_total=monto_usd * tc_pago,
        tipo_cambio=tc_pago,
        modo_imputacion="especifica",
        actualizar_tc_pedido=False,
        estado="pagado",
        creado_por_id=user_id,
    )
    db.add(op)
    db.flush()

    # Imputacion Caso-B: origen=orden_pago, destino=pedido_compra
    imp = Imputacion(
        origen_tipo="orden_pago",
        origen_id=op.id,
        destino_tipo="pedido_compra",
        destino_id=pedido.id,
        monto_imputado=monto_usd,
        moneda_imputada="USD",
        tipo_cambio=tc_pago,
        proveedor_id=proveedor.id,
        creado_por_id=user_id,
        es_reversal=False,
    )
    db.add(imp)
    db.flush()

    # HABER en CC (vinculado a la imputacion)
    haber_mov = CCProveedorMovimiento(
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        fecha_movimiento=date(2026, 2, 2),
        tipo="haber",
        monto=monto_usd,
        moneda="USD",
        tipo_cambio_a_ars=tc_pago,
        origen_tipo="imputacion",
        origen_id=imp.id,
        descripcion=f"HABER {pedido.numero} @ {tc_pago}",
        creado_por_id=user_id,
    )
    db.add(haber_mov)
    db.flush()

    return pedido


# ---------------------------------------------------------------------------
# REQ-FX-CC-001: Los campos existen en la respuesta (aunque sean cero)
# ---------------------------------------------------------------------------


def test_por_pedido_campos_varianza_presentes(client, db, con_permisos, empresa, proveedor, active_user, auth_headers):
    """REQ-FX-CC-001: varianza_tc_neta y varianza_tc_pendiente presentes en respuesta."""
    pedido = PedidoCompra(
        numero=_next_num("PC"),
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="USD",
        monto=Decimal("50"),
        tipo_cambio=Decimal("1000"),
        tipo_cambio_original=Decimal("1000"),
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(pedido)
    db.flush()

    mov = CCProveedorMovimiento(
        proveedor_id=proveedor.id,
        empresa_id=empresa.id,
        fecha_movimiento=date(2026, 2, 1),
        tipo="debe",
        monto=Decimal("50"),
        moneda="USD",
        tipo_cambio_a_ars=Decimal("1000"),
        origen_tipo="pedido_compra",
        origen_id=pedido.id,
        descripcion="DEBE test",
        creado_por_id=active_user.id,
    )
    db.add(mov)
    db.commit()

    resp = client.get(f"{BASE}/cc-proveedor/{proveedor.id}/por-pedido", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) >= 1

    grupo = next((g for g in data if g["pedido_compra_id"] == pedido.id), None)
    assert grupo is not None, "No se encontró el pedido en la respuesta"
    assert "varianza_tc_neta" in grupo, "Falta campo varianza_tc_neta"
    assert "varianza_tc_pendiente" in grupo, "Falta campo varianza_tc_pendiente"


# ---------------------------------------------------------------------------
# REQ-FX-CC-002: Pedido USD saldado a TC distinto → varianza != 0
# ---------------------------------------------------------------------------


def test_por_pedido_varianza_diferencial_tc(
    client, db, con_permisos, empresa, proveedor, active_user, auth_headers, tc_rows
):
    """REQ-FX-CC-002: USD saldado en ARS a TC 1400 vs original 1000 → varianza != 0 y pendiente=True."""
    tc_orig = Decimal("1000")
    tc_pago = Decimal("1400")

    pedido = _build_usd_pedido_con_varianza(db, empresa, proveedor, active_user.id, tc_orig=tc_orig, tc_pago=tc_pago)
    db.commit()

    resp = client.get(f"{BASE}/cc-proveedor/{proveedor.id}/por-pedido", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    grupo = next((g for g in data if g["pedido_compra_id"] == pedido.id), None)
    assert grupo is not None, f"Pedido {pedido.id} no en respuesta. Grupos: {[g['pedido_compra_id'] for g in data]}"

    varianza_neta = Decimal(str(grupo["varianza_tc_neta"]))
    varianza_pendiente = grupo["varianza_tc_pendiente"]

    assert varianza_neta != Decimal("0"), (
        f"Se esperaba varianza_tc_neta != 0, pero fue {varianza_neta}. "
        "El pedido USD pagado a TC 1400 vs original 1000 debe generar diferencial."
    )
    assert varianza_pendiente is True, f"Se esperaba varianza_tc_pendiente=True, pero fue {varianza_pendiente}"
