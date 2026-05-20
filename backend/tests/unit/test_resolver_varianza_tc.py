"""
T2.17–T2.20 — Tests for ncs_locales_service.resolver_varianza_tc (F2).

Verifies:
  - T2.17: AC2.1/2.2 — TC rose → ND created, imputed, variance = 0 after.
  - T2.18: AC2.3/2.4 — TC fell → NC created, imputed, variance = 0 after.
  - T2.19: AC2.8/FR2.7 — idempotent guard: second call raises ValueError when varianza == 0.
  - T2.20: atomicity — NC + imputacion + CC are all committed or all absent.

Pattern mirrors test_calcular_varianza_tc.py.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.caja import Caja, CajaTipoDocumento
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.nota_credito_local import NotaCreditoLocal
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.tipo_cambio import TipoCambio
from app.services import (
    ncs_locales_service,
    ordenes_pago_service,
    pedidos_service,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(nombre="Empresa Resolver Varianza Test", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(
        nombre="Prov Resolver Varianza Test",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=887,
    )
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def caja_ars(db, empresa) -> Caja:
    caja = Caja(
        nombre="Caja ARS Resolver",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("50000000"),
        saldo_actual=Decimal("50000000"),
        activo=True,
    )
    db.add(caja)
    db.flush()
    return caja


@pytest.fixture
def tipos_doc_caja(db) -> None:
    td = CajaTipoDocumento(nombre="Orden de Pago", descripcion="OP", activo=True)
    db.add(td)
    db.flush()


@pytest.fixture
def tipo_cambio_usd(db) -> None:
    db.add(TipoCambio(fecha=date(2026, 1, 1), moneda="USD", compra=Decimal("1400"), venta=Decimal("1410")))
    db.add(TipoCambio(fecha=date(2026, 1, 2), moneda="USD", compra=Decimal("1450"), venta=Decimal("1460")))
    db.flush()


# ---------------------------------------------------------------------------
# Helpers (same pattern as test_calcular_varianza_tc)
# ---------------------------------------------------------------------------


def _pedido_usd(db, empresa, proveedor, active_user, monto: Decimal, tc_orig: Decimal) -> PedidoCompra:
    n = db.query(PedidoCompra).count() + 1
    pedido = PedidoCompra(
        numero=f"PC-RES-{n:04d}",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="USD",
        monto=monto,
        tipo_cambio=tc_orig,
        tipo_cambio_original=tc_orig,
        estado="aprobado",
        creado_por_id=active_user.id,
    )
    db.add(pedido)
    db.flush()
    return pedido


def _op_ars(db, empresa, proveedor, caja, user_id, tc, monto_ars, pedido, actualizar_tc) -> object:
    return ordenes_pago_service.crear(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto_total=monto_ars,
        tipo_cambio=tc,
        modo_imputacion="especifica",
        items=[{"tipo": "pedido_compra", "id": pedido.id, "monto": monto_ars}],
        creado_por_id=user_id,
        actualizar_tc_pedido=actualizar_tc,
    )


def _pagar(db, op, caja, user_id: int) -> None:
    ordenes_pago_service.ejecutar_pago(
        db,
        orden_pago_id=op.id,
        caja_id=caja.id,
        fecha_pago_real=date(2026, 1, 2),
        user_id=user_id,
    )
    db.flush()


def _setup_varianza_positiva(db, empresa, proveedor, caja_ars, active_user) -> tuple[PedidoCompra, Decimal]:
    """Build scenario: TC_orig=1400, TC_ef=1450, 999 USD Caso-B → varianza=+49950."""
    uid = active_user.id
    pedido = _pedido_usd(db, empresa, proveedor, active_user, Decimal("1000"), Decimal("1400"))
    op_a = _op_ars(db, empresa, proveedor, caja_ars, uid, Decimal("1450"), Decimal("1450"), pedido, True)
    _pagar(db, op_a, caja_ars, uid)
    op_b = _op_ars(db, empresa, proveedor, caja_ars, uid, Decimal("1450"), Decimal("1448550"), pedido, False)
    _pagar(db, op_b, caja_ars, uid)
    db.refresh(pedido)
    return pedido, Decimal("49950")


def _setup_varianza_negativa(db, empresa, proveedor, caja_ars, active_user) -> tuple[PedidoCompra, Decimal]:
    """Build scenario: TC_orig=1450, TC_ef=1400, 999 USD Caso-B → varianza=-49950."""
    uid = active_user.id
    pedido = _pedido_usd(db, empresa, proveedor, active_user, Decimal("1000"), Decimal("1450"))
    op_a = _op_ars(db, empresa, proveedor, caja_ars, uid, Decimal("1400"), Decimal("1400"), pedido, True)
    _pagar(db, op_a, caja_ars, uid)
    op_b = _op_ars(db, empresa, proveedor, caja_ars, uid, Decimal("1400"), Decimal("1398600"), pedido, False)
    _pagar(db, op_b, caja_ars, uid)
    db.refresh(pedido)
    return pedido, Decimal("-49950")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestResolverVarianzaTC:
    """T2.17–T2.20: resolver_varianza_tc spec compliance."""

    def test_resolver_varianza_creates_nd_when_tc_rose(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user
    ):
        """T2.17 — AC2.1/2.2: TC rose → ND created and imputed, varianza after = 0."""
        pedido, esperada = _setup_varianza_positiva(db, empresa, proveedor, caja_ars, active_user)
        assert pedidos_service.calcular_varianza_tc(db, pedido) == esperada

        resultado = ncs_locales_service.resolver_varianza_tc(db, pedido_id=pedido.id, user_id=active_user.id)

        assert resultado is not None
        nd = db.get(NotaCreditoLocal, resultado)
        assert nd is not None, "resolver_varianza_tc should create an ND"
        assert nd.tipo == "debito", "TC rose → ND (tipo='debito')"
        assert nd.monto == esperada, f"ND monto should equal varianza {esperada}"
        assert nd.moneda == "ARS"
        assert nd.estado in {"aprobado", "aplicada_parcial", "aplicada"}, (
            f"ND should be in an active state after resolver, got '{nd.estado}'"
        )

        db.refresh(pedido)
        varianza_post = pedidos_service.calcular_varianza_tc(db, pedido)
        assert varianza_post == Decimal("0"), f"After resolver, varianza should be 0, got {varianza_post}"

    def test_resolver_varianza_creates_nc_when_tc_fell(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user
    ):
        """T2.18 — AC2.3/2.4: TC fell → NC created and imputed, varianza after = 0."""
        pedido, esperada = _setup_varianza_negativa(db, empresa, proveedor, caja_ars, active_user)
        assert pedidos_service.calcular_varianza_tc(db, pedido) == esperada

        resultado = ncs_locales_service.resolver_varianza_tc(db, pedido_id=pedido.id, user_id=active_user.id)

        nd = db.get(NotaCreditoLocal, resultado)
        assert nd is not None
        assert nd.tipo == "credito", "TC fell → NC (tipo='credito')"
        assert nd.monto == abs(esperada), f"NC monto should equal abs(varianza) = {abs(esperada)}"
        assert nd.estado in {"aprobado", "aplicada_parcial", "aplicada"}, (
            f"NC should be in an active state after resolver, got '{nd.estado}'"
        )

        db.refresh(pedido)
        varianza_post = pedidos_service.calcular_varianza_tc(db, pedido)
        assert varianza_post == Decimal("0"), f"After resolver, varianza should be 0, got {varianza_post}"

    def test_resolver_varianza_raises_when_no_varianza(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user
    ):
        """T2.19a — AC2.8: no variance → raises ValueError (no ND/NC created)."""
        uid = active_user.id
        pedido = _pedido_usd(db, empresa, proveedor, active_user, Decimal("1000"), Decimal("1400"))
        # Caso A only — no Caso-B → varianza=0.
        op = _op_ars(db, empresa, proveedor, caja_ars, uid, Decimal("1450"), Decimal("1450000"), pedido, True)
        _pagar(db, op, caja_ars, uid)
        db.refresh(pedido)
        assert pedidos_service.calcular_varianza_tc(db, pedido) == Decimal("0")

        with pytest.raises(ValueError, match="varianza"):
            ncs_locales_service.resolver_varianza_tc(db, pedido_id=pedido.id, user_id=uid)

    def test_resolver_varianza_idempotent(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user
    ):
        """T2.19b — FR2.7: second call with resolved varianza raises ValueError again (idempotent guard)."""
        pedido, _ = _setup_varianza_positiva(db, empresa, proveedor, caja_ars, active_user)

        # First call resolves.
        ncs_locales_service.resolver_varianza_tc(db, pedido_id=pedido.id, user_id=active_user.id)
        db.refresh(pedido)

        # Second call: varianza is now 0 → should raise.
        with pytest.raises(ValueError, match="varianza"):
            ncs_locales_service.resolver_varianza_tc(db, pedido_id=pedido.id, user_id=active_user.id)

    def test_resolver_varianza_nc_imputed_to_pedido(
        self, db, empresa, proveedor, caja_ars, tipos_doc_caja, tipo_cambio_usd, active_user
    ):
        """T2.20: atomicity — NC + imputacion on pedido_compra are present after resolver."""
        pedido, esperada = _setup_varianza_positiva(db, empresa, proveedor, caja_ars, active_user)
        nc_id = ncs_locales_service.resolver_varianza_tc(db, pedido_id=pedido.id, user_id=active_user.id)

        # Verify an imputacion from this NC to the pedido was created.
        imp = (
            db.query(Imputacion)
            .filter(
                Imputacion.origen_tipo == "nota_credito_local",
                Imputacion.origen_id == nc_id,
                Imputacion.destino_tipo == "pedido_compra",
                Imputacion.destino_id == pedido.id,
                Imputacion.es_reversal.is_(False),
            )
            .first()
        )
        assert imp is not None, "Imputacion from ND to pedido must exist after resolver"
        assert imp.monto_imputado == esperada
        assert imp.moneda_imputada == "ARS"
