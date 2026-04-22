"""
Tests de `ncs_locales_service` (compras v2 — NCs locales).

Cubre:
  - `crear`: estado inicial, validaciones de monto/moneda/motivo/TC, evento.
  - `editar`: solo borrador, validaciones.
  - `transicionar`: matriz de transiciones válidas + inválidas.
  - Decisión T.6: aprobar NO inserta movimiento CC.
  - `cancelar_aprobado` con imputaciones activas: revierte vía
    `imputaciones_service.revertir_imputaciones_de_origen`.
  - `aplicar_imputacion_a_nc`: transiciones automáticas
    (aprobado → aplicada_parcial → aplicada).
  - `vincular_factura_erp` y `desvincular_factura_erp`.
  - Numeración formato NC-XX-YYYY-NNNNN.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.compra_evento import CompraEvento
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.nota_credito_local import NotaCreditoLocal
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import ncs_locales_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(id=1, nombre="EmpresaNCs", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        id=1,
        nombre="ProveedorNCs",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=42,
    )
    db.add(p)
    db.flush()
    return p


# ──────────────────────────────────────────────────────────────────────────
# crear
# ──────────────────────────────────────────────────────────────────────────


class TestCrearNCLocal:
    def test_crear_nc_ars_ok(self, db, empresa, proveedor, active_user) -> None:
        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("5000.00"),
            fecha_emision=date(2026, 4, 22),
            motivo="Devolución por mercadería defectuosa",
            creado_por_id=active_user.id,
        )
        assert nc.id is not None
        assert nc.estado == "borrador"
        assert nc.numero.startswith("NC-01-")
        assert nc.moneda == "ARS"
        assert nc.monto == Decimal("5000.00")
        assert nc.tipo_cambio is None
        assert nc.motivo == "Devolución por mercadería defectuosa"
        assert nc.aprobado_por_id is None

    def test_crear_nc_usd_con_tc_ok(self, db, empresa, proveedor, active_user) -> None:
        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="USD",
            monto=Decimal("100.00"),
            tipo_cambio=Decimal("1200.50"),
            fecha_emision=date(2026, 4, 22),
            motivo="Bonificación trimestral",
            creado_por_id=active_user.id,
        )
        assert nc.moneda == "USD"
        assert nc.tipo_cambio == Decimal("1200.50")

    def test_crear_nc_usd_sin_tc_autollena_del_dia(self, db, empresa, proveedor, active_user) -> None:
        from app.models.tipo_cambio import TipoCambio

        tc = TipoCambio(fecha=date.today(), moneda="USD", compra=1100.0, venta=1150.0)
        db.add(tc)
        db.flush()

        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="USD",
            monto=Decimal("50"),
            fecha_emision=date.today(),
            motivo="Ajuste",
            creado_por_id=active_user.id,
        )
        assert nc.tipo_cambio == Decimal("1150.0")

    def test_crear_nc_ars_con_tc_raises_400(self, db, empresa, proveedor, active_user) -> None:
        with pytest.raises(HTTPException) as exc:
            ncs_locales_service.crear(
                db,
                empresa_id=empresa.id,
                proveedor_id=proveedor.id,
                moneda="ARS",
                monto=Decimal("100"),
                tipo_cambio=Decimal("1000"),
                fecha_emision=date.today(),
                motivo="m",
                creado_por_id=active_user.id,
            )
        assert exc.value.status_code == 400
        assert "tipo_cambio" in exc.value.detail.lower()

    def test_crear_nc_monto_cero_raises_400(self, db, empresa, proveedor, active_user) -> None:
        with pytest.raises(HTTPException) as exc:
            ncs_locales_service.crear(
                db,
                empresa_id=empresa.id,
                proveedor_id=proveedor.id,
                moneda="ARS",
                monto=Decimal("0"),
                fecha_emision=date.today(),
                motivo="m",
                creado_por_id=active_user.id,
            )
        assert exc.value.status_code == 400

    def test_crear_nc_sin_motivo_raises_400(self, db, empresa, proveedor, active_user) -> None:
        with pytest.raises(HTTPException) as exc:
            ncs_locales_service.crear(
                db,
                empresa_id=empresa.id,
                proveedor_id=proveedor.id,
                moneda="ARS",
                monto=Decimal("100"),
                fecha_emision=date.today(),
                motivo="   ",  # solo whitespace
                creado_por_id=active_user.id,
            )
        assert exc.value.status_code == 400
        assert "motivo" in exc.value.detail.lower()

    def test_crear_nc_registra_evento(self, db, empresa, proveedor, active_user) -> None:
        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            fecha_emision=date.today(),
            motivo="Prueba",
            creado_por_id=active_user.id,
        )
        eventos = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_tipo == "nota_credito_local",
                CompraEvento.entidad_id == nc.id,
                CompraEvento.tipo == "nc_creada",
            )
            .all()
        )
        assert len(eventos) == 1
        assert eventos[0].payload["numero"] == nc.numero

    def test_numero_formato_nc_xx_yyyy_nnnnn(self, db, empresa, proveedor, active_user) -> None:
        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            fecha_emision=date.today(),
            motivo="Prueba",
            creado_por_id=active_user.id,
        )
        # Formato: NC-{empresa_id:02d}-{anio:04d}-{nuevo:05d}
        partes = nc.numero.split("-")
        assert partes[0] == "NC"
        assert partes[1] == "01"
        assert len(partes[2]) == 4  # año
        assert len(partes[3]) == 5  # correlativo


# ──────────────────────────────────────────────────────────────────────────
# editar
# ──────────────────────────────────────────────────────────────────────────


class TestEditarNCLocal:
    def test_editar_borrador_ok(self, db, empresa, proveedor, active_user) -> None:
        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            fecha_emision=date.today(),
            motivo="Original",
            creado_por_id=active_user.id,
        )
        actualizada = ncs_locales_service.editar(
            db,
            nc_id=nc.id,
            user_id=active_user.id,
            monto=Decimal("250"),
            motivo="Corregido",
        )
        assert actualizada.monto == Decimal("250")
        assert actualizada.motivo == "Corregido"

    def test_editar_estado_no_borrador_raises_409(self, db, empresa, proveedor, active_user) -> None:
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
        ncs_locales_service.transicionar(db, nc_id=nc.id, accion="enviar_aprobacion", user_id=active_user.id)
        with pytest.raises(HTTPException) as exc:
            ncs_locales_service.editar(db, nc_id=nc.id, user_id=active_user.id, monto=Decimal("999"))
        assert exc.value.status_code == 409


# ──────────────────────────────────────────────────────────────────────────
# transicionar — matriz
# ──────────────────────────────────────────────────────────────────────────


class TestTransicionarNCLocal:
    def _crear_nc(self, db, empresa, proveedor, user) -> NotaCreditoLocal:
        return ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("1000"),
            fecha_emision=date.today(),
            motivo="x",
            creado_por_id=user.id,
        )

    def test_borrador_a_pendiente(self, db, empresa, proveedor, active_user) -> None:
        nc = self._crear_nc(db, empresa, proveedor, active_user)
        nc = ncs_locales_service.transicionar(
            db, nc_id=nc.id, accion="enviar_aprobacion", user_id=active_user.id
        )
        assert nc.estado == "pendiente_aprobacion"

    def test_pendiente_a_aprobado_no_inserta_cc(self, db, empresa, proveedor, active_user) -> None:
        """DECISIÓN T.6: aprobar NO inserta movimiento CC."""
        nc = self._crear_nc(db, empresa, proveedor, active_user)
        ncs_locales_service.transicionar(db, nc_id=nc.id, accion="enviar_aprobacion", user_id=active_user.id)

        cc_count_antes = db.query(CCProveedorMovimiento).filter_by(proveedor_id=proveedor.id).count()
        nc = ncs_locales_service.transicionar(db, nc_id=nc.id, accion="aprobar", user_id=active_user.id)
        cc_count_despues = db.query(CCProveedorMovimiento).filter_by(proveedor_id=proveedor.id).count()

        assert nc.estado == "aprobado"
        assert nc.aprobado_por_id == active_user.id
        # CRÍTICO: NO se insertó NINGÚN movimiento CC al aprobar.
        assert cc_count_antes == cc_count_despues

    def test_transicion_invalida_raises_400(self, db, empresa, proveedor, active_user) -> None:
        nc = self._crear_nc(db, empresa, proveedor, active_user)
        with pytest.raises(HTTPException) as exc:
            ncs_locales_service.transicionar(db, nc_id=nc.id, accion="aprobar", user_id=active_user.id)
        assert exc.value.status_code == 400

    def test_borrador_a_cancelado(self, db, empresa, proveedor, active_user) -> None:
        nc = self._crear_nc(db, empresa, proveedor, active_user)
        nc = ncs_locales_service.transicionar(db, nc_id=nc.id, accion="cancelar", user_id=active_user.id)
        assert nc.estado == "cancelado"

    def test_pendiente_a_rechazado_devolver(self, db, empresa, proveedor, active_user) -> None:
        nc = self._crear_nc(db, empresa, proveedor, active_user)
        ncs_locales_service.transicionar(db, nc_id=nc.id, accion="enviar_aprobacion", user_id=active_user.id)
        nc = ncs_locales_service.transicionar(
            db, nc_id=nc.id, accion="rechazar_devolver", user_id=active_user.id, motivo="Falta info"
        )
        assert nc.estado == "rechazado"

    def test_rechazado_reabrir_a_borrador(self, db, empresa, proveedor, active_user) -> None:
        nc = self._crear_nc(db, empresa, proveedor, active_user)
        ncs_locales_service.transicionar(db, nc_id=nc.id, accion="enviar_aprobacion", user_id=active_user.id)
        ncs_locales_service.transicionar(
            db, nc_id=nc.id, accion="rechazar_devolver", user_id=active_user.id, motivo="x"
        )
        nc = ncs_locales_service.transicionar(db, nc_id=nc.id, accion="reabrir", user_id=active_user.id)
        assert nc.estado == "borrador"

    def test_aprobado_cancelar_aprobado_revierte_imputaciones(
        self, db, empresa, proveedor, active_user
    ) -> None:
        """cancelar_aprobado debe revertir imputaciones activas vía helper."""
        from app.services import imputaciones_service

        nc = self._crear_nc(db, empresa, proveedor, active_user)
        ncs_locales_service.transicionar(db, nc_id=nc.id, accion="enviar_aprobacion", user_id=active_user.id)
        ncs_locales_service.transicionar(db, nc_id=nc.id, accion="aprobar", user_id=active_user.id)

        # Crear una imputación NC → saldo (no necesita pedido para este test)
        imp = imputaciones_service.crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc.id,
            destino_tipo="saldo",
            destino_id=None,
            monto_imputado=Decimal("400"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
        )
        # Tras imputar, la NC quedó en aplicada_parcial.
        db.refresh(nc)
        assert nc.estado == "aplicada_parcial"

        # Cancelar aprobada (desde aplicada_parcial)
        nc = ncs_locales_service.transicionar(
            db,
            nc_id=nc.id,
            accion="cancelar_aprobado",
            user_id=active_user.id,
            motivo="Error de carga",
        )
        assert nc.estado == "cancelado"

        # Debe haber un reversal de la imputación original
        reversals = (
            db.query(Imputacion)
            .filter(
                Imputacion.reimputada_desde_id == imp.id,
                Imputacion.es_reversal.is_(True),
            )
            .all()
        )
        assert len(reversals) == 1


# ──────────────────────────────────────────────────────────────────────────
# aplicar_imputacion_a_nc — transiciones automáticas
# ──────────────────────────────────────────────────────────────────────────


class TestAplicarImputacionANC:
    @pytest.fixture
    def nc_aprobada(self, db, empresa, proveedor, active_user) -> NotaCreditoLocal:
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

    def test_imputacion_parcial_pasa_a_aplicada_parcial(self, db, nc_aprobada, proveedor, active_user) -> None:
        from app.services import imputaciones_service

        imputaciones_service.crear_imputacion(
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
        db.refresh(nc_aprobada)
        assert nc_aprobada.estado == "aplicada_parcial"

    def test_imputacion_total_pasa_a_aplicada(self, db, nc_aprobada, proveedor, active_user) -> None:
        from app.services import imputaciones_service

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

    def test_imputacion_excede_saldo_raises_400(self, db, nc_aprobada, proveedor, active_user) -> None:
        from app.services import imputaciones_service

        with pytest.raises(HTTPException) as exc:
            imputaciones_service.crear_imputacion(
                db,
                origen_tipo="nota_credito_local",
                origen_id=nc_aprobada.id,
                destino_tipo="saldo",
                destino_id=None,
                monto_imputado=Decimal("1500"),
                moneda_imputada="ARS",
                proveedor_id=proveedor.id,
                creado_por_id=active_user.id,
            )
        assert exc.value.status_code == 400
        assert "excede" in exc.value.detail.lower() or "saldo" in exc.value.detail.lower()

    def test_nc_no_aprobada_no_puede_ser_origen(self, db, empresa, proveedor, active_user) -> None:
        from app.services import imputaciones_service

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
        # Sigue en borrador
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
# CC: imputar NC genera HABER
# ──────────────────────────────────────────────────────────────────────────


class TestCCImpactoAlImputar:
    def test_imputar_nc_genera_haber_en_cc(self, db, empresa, proveedor, active_user) -> None:
        """Al imputar la NC (aprobada), SI se genera HABER en CC."""
        from app.services import cc_proveedor_service, imputaciones_service

        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("500"),
            fecha_emision=date.today(),
            motivo="x",
            creado_por_id=active_user.id,
        )
        ncs_locales_service.transicionar(db, nc_id=nc.id, accion="enviar_aprobacion", user_id=active_user.id)
        ncs_locales_service.transicionar(db, nc_id=nc.id, accion="aprobar", user_id=active_user.id)

        cc_count_antes = db.query(CCProveedorMovimiento).filter_by(proveedor_id=proveedor.id).count()

        imp = imputaciones_service.crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc.id,
            destino_tipo="saldo",
            destino_id=None,
            monto_imputado=Decimal("500"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
        )
        # Caller orquestador (en endpoint sería cc_proveedor_service.aplicar_imputacion)
        cc_proveedor_service.aplicar_imputacion(db, imputacion_id=imp.id)

        cc_count_despues = db.query(CCProveedorMovimiento).filter_by(proveedor_id=proveedor.id).count()
        assert cc_count_despues == cc_count_antes + 1

        ult_mov = (
            db.query(CCProveedorMovimiento)
            .filter_by(proveedor_id=proveedor.id)
            .order_by(CCProveedorMovimiento.id.desc())
            .first()
        )
        assert ult_mov.tipo == "haber"
        assert ult_mov.monto == Decimal("500")


# ──────────────────────────────────────────────────────────────────────────
# vincular_factura_erp / desvincular_factura_erp
# ──────────────────────────────────────────────────────────────────────────


# Helper: crear vista y NC en ERP para los tests de vinculación.
@pytest.fixture
def setup_erp_nc(db, proveedor):
    """Inserta una NC del ERP (sd_iscreditnote=true) que matchea con el proveedor."""
    from app.models.commercial_transaction import CommercialTransaction
    from app.models.tb_sale_document import SaleDocument

    sd = SaleDocument(
        sd_id=103,
        sd_desc="NC Compra",
        sd_ispurchase=True,
        sd_iscreditnote=True,
        sd_isannulment=False,
        sd_plusorminus=-1,
    )
    db.add(sd)
    ct = CommercialTransaction(
        ct_transaction=99001,
        sd_id=103,
        comp_id=1,
        bra_id=1,
        supp_id=42,
        ct_docNumber="NCERP-001",
        ct_total=750.0,
        ct_isCancelled=False,
    )
    db.add(ct)
    db.flush()
    return ct


class TestVincularFacturaERP:
    def test_vincular_sin_ajuste_ok(self, db, empresa, proveedor, active_user, setup_erp_nc) -> None:
        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("750"),
            fecha_emision=date.today(),
            motivo="x",
            creado_por_id=active_user.id,
        )
        nc = ncs_locales_service.vincular_factura_erp(
            db,
            nc_local_id=nc.id,
            ct_transaction=99001,
            user_id=active_user.id,
        )
        assert nc.ct_transaction_id == 99001

        ev = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_tipo == "nota_credito_local",
                CompraEvento.entidad_id == nc.id,
                CompraEvento.tipo == "nc_factura_erp_vinculada",
            )
            .first()
        )
        assert ev is not None

    def test_vincular_con_ajuste_ok(self, db, empresa, proveedor, active_user, setup_erp_nc) -> None:
        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("700"),
            fecha_emision=date.today(),
            motivo="x",
            creado_por_id=active_user.id,
        )
        nc = ncs_locales_service.vincular_factura_erp(
            db,
            nc_local_id=nc.id,
            ct_transaction=99001,
            user_id=active_user.id,
            ajustar_monto=True,
            nuevo_monto=Decimal("750"),
            motivo_ajuste="ERP trajo 750, no 700",
        )
        assert nc.ct_transaction_id == 99001
        assert nc.monto == Decimal("750")

        ev = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_tipo == "nota_credito_local",
                CompraEvento.entidad_id == nc.id,
                CompraEvento.tipo == "nc_monto_ajustado_por_erp",
            )
            .first()
        )
        assert ev is not None
        assert ev.payload["monto_anterior"] == "700"
        assert ev.payload["monto_nuevo"] == "750"

    def test_vincular_ya_vinculada_a_otra_raises_409(
        self, db, empresa, proveedor, active_user, setup_erp_nc
    ) -> None:
        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("750"),
            fecha_emision=date.today(),
            motivo="x",
            creado_por_id=active_user.id,
        )
        nc.ct_transaction_id = 88888  # otra ct previa
        db.flush()
        with pytest.raises(HTTPException) as exc:
            ncs_locales_service.vincular_factura_erp(
                db,
                nc_local_id=nc.id,
                ct_transaction=99001,
                user_id=active_user.id,
            )
        assert exc.value.status_code == 409

    def test_vincular_ct_inexistente_raises_400(
        self, db, empresa, proveedor, active_user, setup_erp_nc
    ) -> None:
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
        with pytest.raises(HTTPException) as exc:
            ncs_locales_service.vincular_factura_erp(
                db,
                nc_local_id=nc.id,
                ct_transaction=88888,  # no existe
                user_id=active_user.id,
            )
        assert exc.value.status_code == 400

    def test_desvincular_ok(self, db, empresa, proveedor, active_user, setup_erp_nc) -> None:
        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("750"),
            fecha_emision=date.today(),
            motivo="x",
            creado_por_id=active_user.id,
        )
        ncs_locales_service.vincular_factura_erp(
            db, nc_local_id=nc.id, ct_transaction=99001, user_id=active_user.id
        )
        nc = ncs_locales_service.desvincular_factura_erp(db, nc_local_id=nc.id, user_id=active_user.id)
        assert nc.ct_transaction_id is None

    def test_desvincular_sin_ct_raises_400(self, db, empresa, proveedor, active_user) -> None:
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
        with pytest.raises(HTTPException) as exc:
            ncs_locales_service.desvincular_factura_erp(db, nc_local_id=nc.id, user_id=active_user.id)
        assert exc.value.status_code == 400


# ──────────────────────────────────────────────────────────────────────────
# Reversal de imputación reabre la NC
# ──────────────────────────────────────────────────────────────────────────


class TestRecalcularEstadoPorImputaciones:
    def test_desimputar_nc_aplicada_total_vuelve_aprobado(
        self, db, empresa, proveedor, active_user
    ) -> None:
        from app.services import imputaciones_service

        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("500"),
            fecha_emision=date.today(),
            motivo="x",
            creado_por_id=active_user.id,
        )
        ncs_locales_service.transicionar(db, nc_id=nc.id, accion="enviar_aprobacion", user_id=active_user.id)
        ncs_locales_service.transicionar(db, nc_id=nc.id, accion="aprobar", user_id=active_user.id)

        imp = imputaciones_service.crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc.id,
            destino_tipo="saldo",
            destino_id=None,
            monto_imputado=Decimal("500"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
        )
        db.refresh(nc)
        assert nc.estado == "aplicada"

        # Desimputar → la NC vuelve a aprobado
        imputaciones_service.desimputar(db, imputacion_id=imp.id, user_id=active_user.id, motivo="error")
        db.refresh(nc)
        assert nc.estado == "aprobado"
