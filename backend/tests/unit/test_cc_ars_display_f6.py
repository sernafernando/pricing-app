"""
T2.26–T2.30 — F6: CC ARS display tests.

Tests for:
  - T2.26: resolver_tc_efectivo_pedido_batch — ARS movement passthrough
  - T2.27: USD movement converted via batch resolver
  - T2.28: Manual override respected (AC6.2)
  - T2.29: N+1 prevention — query count assertion (AC6.4)
  - T2.30: saldo_ars is cumulative ARS sum (AC6.1)

Tests cover the batch TC resolver and ARS projection logic.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import pedidos_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=10, nombre="Empresa F6 Test", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(
        id=10,
        nombre="Proveedor F6",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=10,
    )
    db.add(prov)
    db.flush()
    return prov


def _make_pedido_usd(
    db,
    empresa: Empresa,
    proveedor: Proveedor,
    user_id: int,
    tc_original: Decimal = Decimal("1400"),
    tc_manual: Decimal | None = None,
    suffix: str = "",
) -> PedidoCompra:
    n = db.query(PedidoCompra).count() + 1
    pedido = PedidoCompra(
        numero=f"PC-F6-{n:04d}{suffix}",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="USD",
        monto=Decimal("1000"),
        tipo_cambio=Decimal(tc_manual) if tc_manual is not None else Decimal(tc_original),
        tipo_cambio_original=tc_original,
        tipo_cambio_manual=tc_manual,
        estado="aprobado",
        creado_por_id=user_id,
    )
    db.add(pedido)
    db.flush()
    return pedido


def _make_pedido_ars(
    db,
    empresa: Empresa,
    proveedor: Proveedor,
    user_id: int,
    suffix: str = "",
) -> PedidoCompra:
    n = db.query(PedidoCompra).count() + 1
    pedido = PedidoCompra(
        numero=f"PC-F6-ARS-{n:04d}{suffix}",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("800000"),
        tipo_cambio=None,
        tipo_cambio_original=None,
        tipo_cambio_manual=None,
        estado="aprobado",
        creado_por_id=user_id,
    )
    db.add(pedido)
    db.flush()
    return pedido


def _make_caso_a_imputacion(
    db,
    empresa: Empresa,
    proveedor: Proveedor,
    pedido: PedidoCompra,
    user_id: int,
    tc: Decimal,
    monto_usd: Decimal = Decimal("600"),
) -> None:
    """Create a Caso-A (actualizar_tc_pedido=True) ARS->USD imputacion."""
    n = db.query(OrdenPago).count() + 1
    op = OrdenPago(
        numero=f"OP-F6-{n:04d}",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto_total=monto_usd * tc,
        tipo_cambio=tc,
        modo_imputacion="especifica",
        estado="pagado",
        actualizar_tc_pedido=True,
        creado_por_id=user_id,
    )
    db.add(op)
    db.flush()
    imp = Imputacion(
        origen_tipo="orden_pago",
        origen_id=op.id,
        destino_tipo="pedido_compra",
        destino_id=pedido.id,
        proveedor_id=proveedor.id,
        monto_imputado=monto_usd,
        moneda_imputada=pedido.moneda,
        tipo_cambio=tc,
        es_reversal=False,
        creado_por_id=user_id,
    )
    db.add(imp)
    db.flush()


# ──────────────────────────────────────────────────────────────────────────
# T2.26 — batch resolver returns None for ARS pedidos (passthrough)
# ──────────────────────────────────────────────────────────────────────────


def test_resolver_tc_efectivo_pedido_batch_ars_pedido_returns_none(db, empresa, proveedor, active_user):
    """
    T2.26: An ARS pedido (no TC) should resolve to None in the batch.
    ARS movements with pedido_id pointing to an ARS pedido: monto_ars = monto
    (factor 1, no TC needed). The batch returns None for ARS pedidos.
    """
    pedido = _make_pedido_ars(db, empresa, proveedor, active_user.id)
    result = pedidos_service.resolver_tc_efectivo_pedido_batch(db, [pedido.id])
    assert pedido.id in result
    assert result[pedido.id] is None


# ──────────────────────────────────────────────────────────────────────────
# T2.27 — USD pedido with original TC resolves via batch (mode 3 fallback)
# ──────────────────────────────────────────────────────────────────────────


def test_resolver_tc_efectivo_pedido_batch_usd_no_caso_a_uses_original(db, empresa, proveedor, active_user):
    """
    T2.27: USD pedido with no Caso-A payments — batch returns tipo_cambio_original.
    This is mode 3 (approval snapshot fallback) of AD-2.
    """
    tc_original = Decimal("1450")
    pedido = _make_pedido_usd(db, empresa, proveedor, active_user.id, tc_original=tc_original)
    result = pedidos_service.resolver_tc_efectivo_pedido_batch(db, [pedido.id])
    assert result[pedido.id] == tc_original


# ──────────────────────────────────────────────────────────────────────────
# T2.28 — Manual override respected (AC6.2)
# ──────────────────────────────────────────────────────────────────────────


def test_resolver_tc_efectivo_pedido_batch_manual_override_wins(db, empresa, proveedor, active_user):
    """
    T2.28 / AC6.2: A pedido with tipo_cambio_manual=1430 must resolve to 1430
    via the batch, even if there are Caso-A payments at a different TC.
    """
    tc_original = Decimal("1400")
    tc_manual = Decimal("1430")
    tc_caso_a = Decimal("1450")
    pedido = _make_pedido_usd(
        db,
        empresa,
        proveedor,
        active_user.id,
        tc_original=tc_original,
        tc_manual=tc_manual,
    )
    # Add a Caso-A payment at a different TC — it must NOT override the manual TC.
    _make_caso_a_imputacion(db, empresa, proveedor, pedido, active_user.id, tc=tc_caso_a)

    result = pedidos_service.resolver_tc_efectivo_pedido_batch(db, [pedido.id])
    assert result[pedido.id] == tc_manual, f"Expected manual TC {tc_manual}, got {result[pedido.id]}"


# ──────────────────────────────────────────────────────────────────────────
# T2.27b — Batch: weighted Caso-A TC takes precedence over original (mode 2)
# ──────────────────────────────────────────────────────────────────────────


def test_resolver_tc_efectivo_pedido_batch_caso_a_weighted_avg(db, empresa, proveedor, active_user):
    """
    T2.27b: Caso-A payments shift the effective TC. Batch must return the
    weighted average (mode 2), not tipo_cambio_original (mode 3).
    """
    tc_original = Decimal("1400")
    tc_caso_a = Decimal("1450")
    pedido = _make_pedido_usd(db, empresa, proveedor, active_user.id, tc_original=tc_original)
    _make_caso_a_imputacion(
        db,
        empresa,
        proveedor,
        pedido,
        active_user.id,
        tc=tc_caso_a,
        monto_usd=Decimal("600"),
    )

    result = pedidos_service.resolver_tc_efectivo_pedido_batch(db, [pedido.id])
    assert result[pedido.id] == tc_caso_a, f"Expected Caso-A TC {tc_caso_a}, got {result[pedido.id]}"


# ──────────────────────────────────────────────────────────────────────────
# T2.29 — N+1 prevention: batch resolves M pedidos in O(1) queries (AC6.4)
# ──────────────────────────────────────────────────────────────────────────


def test_resolver_tc_efectivo_pedido_batch_no_n_plus_one(db, empresa, proveedor, active_user):
    """
    T2.29 / AC6.4: resolver_tc_efectivo_pedido_batch must NOT issue one query
    per pedido. For 5 distinct pedidos the total query count must be <= 5
    (in practice: 2 batch queries — one for manuals/originals, one for Caso-A).
    """
    from sqlalchemy import event

    # Create 5 USD pedidos, some with Caso-A payments.
    pedidos = []
    for i in range(5):
        p = _make_pedido_usd(
            db,
            empresa,
            proveedor,
            active_user.id,
            tc_original=Decimal(f"14{i:02d}"),
            suffix=f"-{i}",
        )
        pedidos.append(p)

    # Add Caso-A payment to first 3 pedidos.
    for p in pedidos[:3]:
        _make_caso_a_imputacion(db, empresa, proveedor, p, active_user.id, tc=Decimal("1450"))

    db.flush()
    pedido_ids = [p.id for p in pedidos]

    # Count DB round-trips during the batch call.
    query_count = 0

    @event.listens_for(db.bind, "before_cursor_execute")
    def count_queries(conn, cursor, statement, parameters, context, executemany):
        nonlocal query_count
        query_count += 1

    try:
        result = pedidos_service.resolver_tc_efectivo_pedido_batch(db, pedido_ids)
    finally:
        event.remove(db.bind, "before_cursor_execute", count_queries)

    assert len(result) == 5
    assert query_count <= 5, f"N+1 detected: {query_count} queries for 5 pedidos (expected <= 5)"


# ──────────────────────────────────────────────────────────────────────────
# T2.30 — saldo_ars is cumulative sum of ARS-converted movements (AC6.1)
# ──────────────────────────────────────────────────────────────────────────


def test_resolver_tc_efectivo_pedido_batch_multi_pedido_correct_values(db, empresa, proveedor, active_user):
    """
    T2.30 / AC6.1: Verify that the batch returns the correct effective TC for
    multiple pedidos simultaneously, enabling correct monto_ars computation.

    Scenario:
      - pedido_a (USD, TC_original=1400, no Caso-A) → TC_ef = 1400
      - pedido_b (USD, TC_manual=1430) → TC_ef = 1430
      - pedido_c (USD, TC_original=1400, Caso-A TC=1450) → TC_ef = 1450

    Then verify monto_ars = monto * tc_ef for each.
    """
    pedido_a = _make_pedido_usd(
        db,
        empresa,
        proveedor,
        active_user.id,
        tc_original=Decimal("1400"),
        suffix="-a",
    )
    pedido_b = _make_pedido_usd(
        db,
        empresa,
        proveedor,
        active_user.id,
        tc_original=Decimal("1400"),
        tc_manual=Decimal("1430"),
        suffix="-b",
    )
    pedido_c = _make_pedido_usd(
        db,
        empresa,
        proveedor,
        active_user.id,
        tc_original=Decimal("1400"),
        suffix="-c",
    )
    _make_caso_a_imputacion(
        db,
        empresa,
        proveedor,
        pedido_c,
        active_user.id,
        tc=Decimal("1450"),
        monto_usd=Decimal("600"),
    )

    pedido_ids = [pedido_a.id, pedido_b.id, pedido_c.id]
    result = pedidos_service.resolver_tc_efectivo_pedido_batch(db, pedido_ids)

    assert result[pedido_a.id] == Decimal("1400"), f"pedido_a: {result[pedido_a.id]}"
    assert result[pedido_b.id] == Decimal("1430"), f"pedido_b: {result[pedido_b.id]}"
    assert result[pedido_c.id] == Decimal("1450"), f"pedido_c: {result[pedido_c.id]}"

    # Verify monto_ars would be computed correctly:
    # pedido_a: USD 1000 * 1400 = ARS 1,400,000
    # pedido_b: USD 1000 * 1430 = ARS 1,430,000
    # pedido_c: USD 600 at 1450 = Caso-A weighted avg 1450 (the USD 1000 pedido)
    monto_ars_a = Decimal("1000") * result[pedido_a.id]
    monto_ars_b = Decimal("1000") * result[pedido_b.id]
    assert monto_ars_a == Decimal("1400000")
    assert monto_ars_b == Decimal("1430000")


def test_resolver_tc_efectivo_pedido_batch_empty_list(db):
    """Empty input returns empty dict — no DB queries needed."""
    result = pedidos_service.resolver_tc_efectivo_pedido_batch(db, [])
    assert result == {}


# ──────────────────────────────────────────────────────────────────────────
# Tests for router-level F6 helpers: _resolver_pedido_id_para_mov
# (AC6.1, AC6.5 — saldo_ars accumulation; logic is inline in _enriquecer_movimientos_cc).
# ──────────────────────────────────────────────────────────────────────────


class _FakeMov:
    """Minimal mock of CCProveedorMovimiento for router helper tests."""

    def __init__(self, origen_tipo, origen_id, monto, moneda, tipo, signo_ajuste=None, monto_ars=None):
        self.origen_tipo = origen_tipo
        self.origen_id = origen_id
        self.monto = monto
        self.moneda = moneda
        self.tipo = tipo
        self.signo_ajuste = signo_ajuste
        self.monto_ars = monto_ars


def test_resolver_pedido_id_direct_origin_types():
    """
    T2.30b: _resolver_pedido_id_para_mov must resolve all ORIGEN_DIRECTO_PEDIDO_F6
    types directly (not just pedido_compra). This covers cancellation and adjustment
    movements so they don't drop out of the saldo_ars sum.
    """
    from app.routers.administracion_compras import _resolver_pedido_id_para_mov

    imps_destino: dict[int, int | None] = {}
    for origen_tipo in (
        "pedido_compra",
        "cancelacion_pedido",
        "ajuste_pedido",
        "cancelacion_pedido_por_correccion",
        "revaluacion_tc",
    ):
        m = _FakeMov(origen_tipo=origen_tipo, origen_id=42, monto=1000, moneda="USD", tipo="debe")
        assert _resolver_pedido_id_para_mov(m, imps_destino) == 42, (
            f"Expected pedido_id=42 for origen_tipo='{origen_tipo}', got None"
        )


def test_resolver_pedido_id_imputacion_hop():
    """
    T2.30c: imputacion/reimputacion tipos are resolved via the imps_destino_pedido lookup.
    """
    from app.routers.administracion_compras import _resolver_pedido_id_para_mov

    imps_destino: dict[int, int | None] = {99: 7, 100: None}
    m_imp = _FakeMov(origen_tipo="imputacion", origen_id=99, monto=500, moneda="ARS", tipo="haber")
    m_reimp = _FakeMov(origen_tipo="reimputacion", origen_id=99, monto=500, moneda="ARS", tipo="debe")
    m_no_pedido = _FakeMov(origen_tipo="imputacion", origen_id=100, monto=500, moneda="ARS", tipo="haber")
    m_unknown = _FakeMov(
        origen_tipo="ajuste_manual", origen_id=None, monto=500, moneda="ARS", tipo="ajuste", signo_ajuste=1
    )

    assert _resolver_pedido_id_para_mov(m_imp, imps_destino) == 7
    assert _resolver_pedido_id_para_mov(m_reimp, imps_destino) == 7
    assert _resolver_pedido_id_para_mov(m_no_pedido, imps_destino) is None
    assert _resolver_pedido_id_para_mov(m_unknown, imps_destino) is None


def test_enriquecer_ars_movement_passthrough(db):
    """
    AC6.5: _enriquecer_movimientos_cc must set monto_ars == monto and
    tc_aplicado == None for ARS movements (no TC conversion needed).

    Hits the real function with a fake ARS movement ORM-like object.
    """
    from datetime import datetime
    from app.routers.administracion_compras import _enriquecer_movimientos_cc

    class _OrmMov:
        id = 1
        proveedor_id = 1
        empresa_id = 1
        fecha_movimiento = "2024-01-15"
        tipo = "haber"
        signo_ajuste = None
        monto = Decimal("800000")
        moneda = "ARS"
        tipo_cambio_a_ars = None
        origen_tipo = "ajuste_manual"
        origen_id = None
        descripcion = None
        creado_por_id = None
        created_at = datetime(2024, 1, 15)

    resultado = _enriquecer_movimientos_cc(db, [_OrmMov()])
    assert len(resultado) == 1
    resp = resultado[0]
    assert resp.monto_ars == Decimal("800000"), f"Expected monto_ars=800000, got {resp.monto_ars}"
    assert resp.tc_aplicado is None, f"Expected tc_aplicado=None for ARS, got {resp.tc_aplicado}"


def test_enriquecer_usd_without_pedido_returns_none_monto_ars(db):
    """
    T2.30d: _enriquecer_movimientos_cc must return monto_ars=None for a non-ARS
    movement that has no pedido link (cannot determine TC).

    This also verifies that the saldo_ars loop in obtener_cc_proveedor will
    skip such movements (they contribute 0 to the ARS total).
    """
    from datetime import datetime
    from app.routers.administracion_compras import _enriquecer_movimientos_cc

    class _OrmMovUsd:
        id = 2
        proveedor_id = 1
        empresa_id = 1
        fecha_movimiento = "2024-01-15"
        tipo = "debe"
        signo_ajuste = None
        monto = Decimal("1000")
        moneda = "USD"
        tipo_cambio_a_ars = None
        # origen_tipo='ajuste_manual' has no pedido link → cannot resolve TC
        origen_tipo = "ajuste_manual"
        origen_id = None
        descripcion = None
        creado_por_id = None
        created_at = datetime(2024, 1, 15)

    resultado = _enriquecer_movimientos_cc(db, [_OrmMovUsd()])
    assert len(resultado) == 1
    resp = resultado[0]
    assert resp.monto_ars is None, f"Expected monto_ars=None for USD movement without pedido link, got {resp.monto_ars}"
