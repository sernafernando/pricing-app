"""
Tests de integración entre `imputaciones_service` y NCs locales (compras v2).

Cubre:
  - Whitelist acepta combos `(nota_credito_local, *)`.
  - Imputar NC local a pedido_compra: pedido pasa a pagado_parcial / pagado.
  - Imputar NC local total: NC pasa a aplicada.
  - Desimputar NC local: NC vuelve a aprobado / aplicada_parcial.
  - NC en estado != aprobado/aplicada_parcial NO puede ser origen.
  - Helper `revertir_imputaciones_de_origen` genera reversals para todas las
    imputaciones activas.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import imputaciones_service, ncs_locales_service, pedidos_service


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=1, nombre="EmpresaTest", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(id=1, nombre="Prov", activo=True, origen=OrigenProveedor.ERP.value, supp_id=42)
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def nc_aprobada(db, empresa, proveedor, active_user):
    nc = ncs_locales_service.crear(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("1000"),
        fecha_emision=date.today(),
        motivo="x",
        creado_por_id=active_user.id,
    )
    ncs_locales_service.transicionar(db, nc_id=nc.id, accion="enviar_aprobacion", user_id=active_user.id)
    ncs_locales_service.transicionar(db, nc_id=nc.id, accion="aprobar", user_id=active_user.id)
    return nc


@pytest.fixture
def pedido_aprobado(db, empresa, proveedor, active_user):
    pedido = pedidos_service.crear_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("700"),
        creado_por_id=active_user.id,
    )
    pedidos_service.transicionar(
        db, pedido_id=pedido.id, accion="enviar_aprobacion", user_id=active_user.id
    )
    pedidos_service.transicionar(db, pedido_id=pedido.id, accion="aprobar", user_id=active_user.id)
    return pedido


# ──────────────────────────────────────────────────────────────────────────
# Whitelist
# ──────────────────────────────────────────────────────────────────────────


class TestWhitelistConNCLocal:
    def test_combo_nc_local_pedido_compra_valido(self) -> None:
        assert ("nota_credito_local", "pedido_compra") in imputaciones_service.COMBOS_VALIDOS_V1

    def test_combo_nc_local_factura_erp_valido(self) -> None:
        assert ("nota_credito_local", "factura_erp") in imputaciones_service.COMBOS_VALIDOS_V1

    def test_combo_nc_local_saldo_valido(self) -> None:
        assert ("nota_credito_local", "saldo") in imputaciones_service.COMBOS_VALIDOS_V1


# ──────────────────────────────────────────────────────────────────────────
# Imputar NC local a pedido
# ──────────────────────────────────────────────────────────────────────────


class TestImputarNCLocalAPedido:
    def test_imputar_parcial_pedido_pasa_a_pagado_parcial(
        self, db, nc_aprobada, pedido_aprobado, proveedor, active_user
    ) -> None:
        from app.services import cc_proveedor_service

        imp = imputaciones_service.crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc_aprobada.id,
            destino_tipo="pedido_compra",
            destino_id=pedido_aprobado.id,
            monto_imputado=Decimal("300"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
        )
        cc_proveedor_service.aplicar_imputacion(db, imputacion_id=imp.id)
        # Caller orquesta el recalculo del pedido
        pedidos_service.aplicar_imputacion_a_pedido(
            db, pedido_id=pedido_aprobado.id, monto_imputado=Decimal("300")
        )
        db.refresh(pedido_aprobado)
        db.refresh(nc_aprobada)
        assert pedido_aprobado.estado == "pagado_parcial"
        assert nc_aprobada.estado == "aplicada_parcial"

    def test_imputar_total_pedido_y_nc_completas(
        self, db, nc_aprobada, pedido_aprobado, proveedor, active_user
    ) -> None:
        """Imputar exactamente el monto del pedido (700) y el de la NC (1000) NO
        coincide; testeamos imputar el monto del pedido (700) — la NC queda aplicada_parcial."""
        from app.services import cc_proveedor_service

        imp = imputaciones_service.crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc_aprobada.id,
            destino_tipo="pedido_compra",
            destino_id=pedido_aprobado.id,
            monto_imputado=Decimal("700"),  # cubre el pedido completo
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
        )
        cc_proveedor_service.aplicar_imputacion(db, imputacion_id=imp.id)
        pedidos_service.aplicar_imputacion_a_pedido(
            db, pedido_id=pedido_aprobado.id, monto_imputado=Decimal("700")
        )
        db.refresh(pedido_aprobado)
        db.refresh(nc_aprobada)
        assert pedido_aprobado.estado == "pagado"
        # NC tiene monto=1000 y solo se imputó 700 → aplicada_parcial
        assert nc_aprobada.estado == "aplicada_parcial"

    def test_imputar_nc_completa_pasa_a_aplicada(
        self, db, nc_aprobada, proveedor, active_user
    ) -> None:
        imputaciones_service.crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc_aprobada.id,
            destino_tipo="saldo",
            destino_id=None,
            monto_imputado=Decimal("1000"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
        )
        db.refresh(nc_aprobada)
        assert nc_aprobada.estado == "aplicada"

    def test_desimputar_nc_local_la_reabre(self, db, nc_aprobada, proveedor, active_user) -> None:
        imp = imputaciones_service.crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc_aprobada.id,
            destino_tipo="saldo",
            destino_id=None,
            monto_imputado=Decimal("1000"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
        )
        db.refresh(nc_aprobada)
        assert nc_aprobada.estado == "aplicada"

        imputaciones_service.desimputar(
            db, imputacion_id=imp.id, user_id=active_user.id, motivo="x"
        )
        db.refresh(nc_aprobada)
        assert nc_aprobada.estado == "aprobado"

    def test_nc_cancelada_no_puede_ser_origen(self, db, empresa, proveedor, active_user) -> None:
        from fastapi import HTTPException

        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            fecha_emision=date.today(),
            motivo="x",
            creado_por_id=active_user.id,
        )
        ncs_locales_service.transicionar(db, nc_id=nc.id, accion="cancelar", user_id=active_user.id)

        with pytest.raises(HTTPException) as exc:
            imputaciones_service.crear_imputacion(
                db,
                origen_tipo="nota_credito_local",
                origen_id=nc.id,
                destino_tipo="saldo",
                destino_id=None,
                monto_imputado=Decimal("50"),
                moneda_imputada="ARS",
                proveedor_id=proveedor.id,
                creado_por_id=active_user.id,
            )
        assert exc.value.status_code == 409


# ──────────────────────────────────────────────────────────────────────────
# Helper revertir_imputaciones_de_origen
# ──────────────────────────────────────────────────────────────────────────


class TestRevertirImputacionesDeOrigen:
    def test_revertir_genera_reversal_por_imputacion_activa(
        self, db, nc_aprobada, proveedor, active_user
    ) -> None:
        # Crear 2 imputaciones de la misma NC
        imp1 = imputaciones_service.crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc_aprobada.id,
            destino_tipo="saldo",
            destino_id=None,
            monto_imputado=Decimal("400"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
        )
        imp2 = imputaciones_service.crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc_aprobada.id,
            destino_tipo="saldo",
            destino_id=None,
            monto_imputado=Decimal("300"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
        )

        reversals = imputaciones_service.revertir_imputaciones_de_origen(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc_aprobada.id,
            user_id=active_user.id,
            motivo="cancelacion",
        )
        assert len(reversals) == 2
        # Cada reversal apunta a una de las imputaciones originales
        rev_ids = {r.reimputada_desde_id for r in reversals}
        assert rev_ids == {imp1.id, imp2.id}
        for rev in reversals:
            assert rev.es_reversal is True

    def test_revertir_skipea_imputaciones_ya_reimputadas(
        self, db, nc_aprobada, proveedor, active_user
    ) -> None:
        imp1 = imputaciones_service.crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc_aprobada.id,
            destino_tipo="saldo",
            destino_id=None,
            monto_imputado=Decimal("100"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
        )
        # Desimputar manualmente imp1 antes del revert masivo
        imputaciones_service.desimputar(db, imputacion_id=imp1.id, user_id=active_user.id, motivo="x")

        # Ahora revertir masivamente — imp1 ya está revertida, no debe crear otro reversal
        reversals = imputaciones_service.revertir_imputaciones_de_origen(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc_aprobada.id,
            user_id=active_user.id,
            motivo="x",
        )
        assert len(reversals) == 0

    def test_revertir_sin_imputaciones_devuelve_lista_vacia(
        self, db, nc_aprobada, active_user
    ) -> None:
        reversals = imputaciones_service.revertir_imputaciones_de_origen(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc_aprobada.id,
            user_id=active_user.id,
            motivo="x",
        )
        assert reversals == []
