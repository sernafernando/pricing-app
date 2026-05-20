"""
T2.7–T2.10 — Tests for F2 CC sign branch in cc_proveedor_service.aplicar_imputacion.

Verifies that:
  - NC with tipo='credito' → HABER movement (reduces debt).
  - NC with tipo='debito'  → DEBE movement  (increases debt).
  - Backfilled rows (tipo='credito') behave identically to before (regression guard).
  - Reversal of an ND (tipo='debito') emits HABER (inverts the original DEBE).

These are unit-level tests using the shared DB fixture from conftest.py.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.empresa import Empresa
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import cc_proveedor_service, imputaciones_service, ncs_locales_service, pedidos_service


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=10, nombre="Empresa F2 Sign Test", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(
        id=10,
        nombre="Proveedor F2 Sign Test",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=999,
    )
    db.add(prov)
    db.flush()
    return prov


def _make_pedido_ars(db, empresa, proveedor, active_user, monto: Decimal = Decimal("1000")):
    """Create and approve an ARS pedido."""
    pedido = pedidos_service.crear_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=monto,
        creado_por_id=active_user.id,
    )
    pedidos_service.transicionar(db, pedido_id=pedido.id, accion="enviar_aprobacion", user_id=active_user.id)
    pedidos_service.transicionar(db, pedido_id=pedido.id, accion="aprobar", user_id=active_user.id)
    return pedido


def _make_nc_aprobada(db, empresa, proveedor, active_user, monto: Decimal, tipo: str = "credito"):
    """Create and approve a NC local with given tipo."""
    nc = ncs_locales_service.crear(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=monto,
        fecha_emision=date.today(),
        motivo="varianza TC test",
        creado_por_id=active_user.id,
        tipo=tipo,
    )
    ncs_locales_service.transicionar(db, nc_id=nc.id, accion="enviar_aprobacion", user_id=active_user.id)
    ncs_locales_service.transicionar(db, nc_id=nc.id, accion="aprobar", user_id=active_user.id)
    return nc


# ---------------------------------------------------------------------------
# T2.7 — NC tipo='credito' generates HABER
# ---------------------------------------------------------------------------


class TestCCSignF2:
    def test_nc_tipo_credito_emite_haber(self, db, empresa, proveedor, active_user):
        """T2.7: NC with tipo='credito' → HABER movement (reduces debt)."""
        pedido = _make_pedido_ars(db, empresa, proveedor, active_user, Decimal("800"))
        nc = _make_nc_aprobada(db, empresa, proveedor, active_user, Decimal("200"), tipo="credito")

        imp = imputaciones_service.crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc.id,
            destino_tipo="pedido_compra",
            destino_id=pedido.id,
            monto_imputado=Decimal("200"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
        )
        movs = cc_proveedor_service.aplicar_imputacion(db, imputacion_id=imp.id)

        assert len(movs) == 1
        mov = movs[0]
        assert mov.tipo == "haber", f"Expected 'haber' for tipo='credito', got '{mov.tipo}'"
        assert mov.monto == Decimal("200")

    def test_nc_tipo_debito_emite_debe(self, db, empresa, proveedor, active_user):
        """T2.8: NC with tipo='debito' (ND) → DEBE movement (increases debt)."""
        pedido = _make_pedido_ars(db, empresa, proveedor, active_user, Decimal("800"))
        nc = _make_nc_aprobada(db, empresa, proveedor, active_user, Decimal("50000"), tipo="debito")

        imp = imputaciones_service.crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc.id,
            destino_tipo="pedido_compra",
            destino_id=pedido.id,
            monto_imputado=Decimal("50000"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
        )
        movs = cc_proveedor_service.aplicar_imputacion(db, imputacion_id=imp.id)

        assert len(movs) == 1
        mov = movs[0]
        assert mov.tipo == "debe", f"Expected 'debe' for tipo='debito', got '{mov.tipo}'"
        assert mov.monto == Decimal("50000")

    def test_reversal_nd_debito_emite_haber(self, db, empresa, proveedor, active_user):
        """T2.10: Reversal of an ND (tipo='debito') emits HABER — cancels the original DEBE."""
        pedido = _make_pedido_ars(db, empresa, proveedor, active_user, Decimal("800"))
        nd = _make_nc_aprobada(db, empresa, proveedor, active_user, Decimal("50000"), tipo="debito")

        imp = imputaciones_service.crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nd.id,
            destino_tipo="pedido_compra",
            destino_id=pedido.id,
            monto_imputado=Decimal("50000"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
        )
        # Apply original imputation → should emit DEBE.
        movs_orig = cc_proveedor_service.aplicar_imputacion(db, imputacion_id=imp.id)
        assert movs_orig[0].tipo == "debe"

        # Now reverse: revertir_imputaciones_de_origen creates reversal imputaciones
        # and calls aplicar_imputacion for each → should emit HABER.
        reversals = imputaciones_service.revertir_imputaciones_de_origen(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nd.id,
            user_id=active_user.id,
            motivo="cancelacion ND varianza TC",
        )
        assert len(reversals) == 1
        rev_imp = reversals[0]
        assert rev_imp.es_reversal is True

        # Fetch the CC movement created for the reversal.
        # Reversal CC movements link via origen_tipo='reimputacion' + origen_id=rev_imp.id.
        rev_mov = (
            db.query(CCProveedorMovimiento)
            .filter(
                CCProveedorMovimiento.origen_tipo == "reimputacion",
                CCProveedorMovimiento.origen_id == rev_imp.id,
            )
            .first()
        )
        assert rev_mov is not None, "Reversal should have created a CC movement"
        assert rev_mov.tipo == "haber", f"Reversal of ND (tipo='debito') should emit HABER, got '{rev_mov.tipo}'"

    def test_backfilled_credito_rows_behave_identically(self, db, empresa, proveedor, active_user):
        """T2.9: Existing NC rows (backfilled tipo='credito') produce same CC sign as before (HABER)."""
        pedido = _make_pedido_ars(db, empresa, proveedor, active_user, Decimal("500"))
        # Simulate a "backfilled" NC — created without explicit tipo (defaults to 'credito').
        nc = _make_nc_aprobada(db, empresa, proveedor, active_user, Decimal("100"))
        assert nc.tipo == "credito"  # verify the default

        imp = imputaciones_service.crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc.id,
            destino_tipo="pedido_compra",
            destino_id=pedido.id,
            monto_imputado=Decimal("100"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
        )
        movs = cc_proveedor_service.aplicar_imputacion(db, imputacion_id=imp.id)

        assert len(movs) == 1
        assert movs[0].tipo == "haber", "Backfilled credito NC should still produce HABER"
