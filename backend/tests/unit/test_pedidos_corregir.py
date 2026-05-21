"""Tests unitarios de `pedidos_service.corregir_pedido` (Feature D).

Cubre:
  - Validaciones de estado del original (solo desde aprobado/pagado_*).
  - Bloqueo de cambio de moneda.
  - Herencia del clon: numero, proveedor, empresa, moneda, ct_transaction_id,
    adjuntos (mismo path_archivo).
  - Determinación del estado del clon:
      * cosméticos (observaciones, factura, fechas, envío) → clon aprobado.
      * monto → clon pendiente_aprobacion (tipo_cambio rejected via F5 — use PUT /tipo-cambio).
  - Transferencia de imputaciones (opción Z):
      * Cosméticos → reversal + nueva imputación inmediatos.
      * Financieros → imputaciones congeladas; reaplicación al aprobar el clon.
      * Rechazar clon → imputaciones en original quedan intactas.
  - Círculo cerrado: corregido_desde_id (clon) + corregido_a_id (original).
  - Eventos: `creado_por_correccion_de` (clon) + `cancelado_por_correccion`
    (original).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.cc_proveedor_movimiento import CCProveedorMovimiento
from app.models.compra_adjunto import CompraAdjunto
from app.models.compra_evento import CompraEvento
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import imputaciones_service, pedidos_service


# ──────────────────────────────────────────────────────────────────────────
# Fixtures (mismos que test_pedidos_service.py; duplicados por aislamiento)
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=1, nombre="Empresa Corregir Test", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(
        id=1,
        nombre="Proveedor Corregir",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=100,
    )
    db.add(prov)
    db.flush()
    return prov


def _crear_pedido_aprobado(
    db,
    empresa,
    proveedor,
    active_user,
    *,
    moneda="ARS",
    monto=Decimal("1000"),
    tipo_cambio=None,
    numero_factura=None,
    observaciones=None,
):
    """Helper: crea un pedido y lo aprueba manualmente (transición normal)."""
    p = pedidos_service.crear_pedido(
        db,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda=moneda,
        monto=monto,
        tipo_cambio=tipo_cambio,
        creado_por_id=active_user.id,
    )
    if numero_factura:
        p.numero_factura = numero_factura
    if observaciones:
        p.observaciones = observaciones
    pedidos_service.transicionar(db, pedido_id=p.id, accion="enviar_aprobacion", user_id=active_user.id)
    pedidos_service.transicionar(db, pedido_id=p.id, accion="aprobar", user_id=active_user.id)
    db.refresh(p)
    return p


# ──────────────────────────────────────────────────────────────────────────
# TestCorregirPedido — validaciones básicas + clonación
# ──────────────────────────────────────────────────────────────────────────


class TestCorregirPedido:
    def test_corregir_desde_borrador_raises_409(self, db, empresa, proveedor, active_user) -> None:
        p = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            creado_por_id=active_user.id,
        )
        # Queda en borrador
        with pytest.raises(HTTPException) as exc:
            pedidos_service.corregir_pedido(
                db,
                pedido_original_id=p.id,
                cambios={"observaciones": "x"},
                motivo_correccion="prueba motivo largo",
                user_id=active_user.id,
            )
        assert exc.value.status_code == 409

    def test_corregir_desde_cancelado_raises_409(self, db, empresa, proveedor, active_user) -> None:
        p = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            creado_por_id=active_user.id,
        )
        p.estado = "cancelado"
        db.flush()
        with pytest.raises(HTTPException) as exc:
            pedidos_service.corregir_pedido(
                db,
                pedido_original_id=p.id,
                cambios={"observaciones": "x"},
                motivo_correccion="motivo de prueba",
                user_id=active_user.id,
            )
        assert exc.value.status_code == 409

    def test_corregir_cambia_moneda_raises_400(self, db, empresa, proveedor, active_user) -> None:
        p = _crear_pedido_aprobado(db, empresa, proveedor, active_user, moneda="ARS")
        with pytest.raises(HTTPException) as exc:
            pedidos_service.corregir_pedido(
                db,
                pedido_original_id=p.id,
                cambios={"moneda": "USD"},
                motivo_correccion="no se puede cambiar moneda",
                user_id=active_user.id,
            )
        assert exc.value.status_code == 400
        assert "moneda" in exc.value.detail.lower()

    def test_corregir_cosmetico_observaciones_clon_queda_aprobado(self, db, empresa, proveedor, active_user) -> None:
        """Cambiar solo observaciones → clon nace aprobado."""
        p = _crear_pedido_aprobado(db, empresa, proveedor, active_user, observaciones="vieja")
        clon = pedidos_service.corregir_pedido(
            db,
            pedido_original_id=p.id,
            cambios={"observaciones": "nueva nota actualizada"},
            motivo_correccion="aclarar observación del contador",
            user_id=active_user.id,
        )
        db.refresh(p)
        db.refresh(clon)
        assert clon.estado == "aprobado"
        assert clon.observaciones == "nueva nota actualizada"
        assert p.estado == "cancelado"

    def test_corregir_cambia_monto_clon_queda_pendiente_aprobacion(self, db, empresa, proveedor, active_user) -> None:
        p = _crear_pedido_aprobado(db, empresa, proveedor, active_user, monto=Decimal("1000"))
        clon = pedidos_service.corregir_pedido(
            db,
            pedido_original_id=p.id,
            cambios={"monto": Decimal("1200")},
            motivo_correccion="ajuste por factura definitiva",
            user_id=active_user.id,
        )
        db.refresh(p)
        db.refresh(clon)
        assert clon.estado == "pendiente_aprobacion"
        assert clon.monto == Decimal("1200")
        assert p.estado == "cancelado"

    def test_corregir_rechaza_tipo_cambio_con_422(self, db, empresa, proveedor, active_user) -> None:
        """F5 — corregir_pedido must reject tipo_cambio with HTTP 422.

        TC corrections now go exclusively through PUT /pedidos/{id}/tipo-cambio
        (in-place, append-only CC audit trail). Passing tipo_cambio here would create
        a clone without the audit movement — an accounting hole.
        """
        p = _crear_pedido_aprobado(
            db,
            empresa,
            proveedor,
            active_user,
            moneda="USD",
            monto=Decimal("100"),
            tipo_cambio=Decimal("1000"),
        )
        with pytest.raises(HTTPException) as exc_info:
            pedidos_service.corregir_pedido(
                db,
                pedido_original_id=p.id,
                cambios={"tipo_cambio": Decimal("1250.00")},
                motivo_correccion="intento de cambio TC por correccion",
                user_id=active_user.id,
            )
        assert exc_info.value.status_code == 422
        assert "tipo_cambio" in str(exc_info.value.detail).lower()

    def test_original_queda_con_corregido_a_id_y_clon_con_corregido_desde_id(
        self, db, empresa, proveedor, active_user
    ) -> None:
        p = _crear_pedido_aprobado(db, empresa, proveedor, active_user)
        clon = pedidos_service.corregir_pedido(
            db,
            pedido_original_id=p.id,
            cambios={"numero_factura": "FA-NEW-001"},
            motivo_correccion="cambio número factura",
            user_id=active_user.id,
        )
        db.refresh(p)
        db.refresh(clon)
        assert p.corregido_a_id == clon.id
        assert clon.corregido_desde_id == p.id
        assert p.corregido_desde_id is None
        assert clon.corregido_a_id is None

    def test_ct_transaction_id_se_transfiere_original_a_clon(self, db, empresa, proveedor, active_user) -> None:
        p = _crear_pedido_aprobado(db, empresa, proveedor, active_user)
        p.ct_transaction_id = 99_888_777
        db.flush()
        clon = pedidos_service.corregir_pedido(
            db,
            pedido_original_id=p.id,
            cambios={"observaciones": "transferencia ct_transaction"},
            motivo_correccion="prueba transferencia ct",
            user_id=active_user.id,
        )
        db.refresh(p)
        db.refresh(clon)
        assert p.ct_transaction_id is None
        assert clon.ct_transaction_id == 99_888_777

    def test_clon_hereda_adjuntos_con_mismo_path(self, db, empresa, proveedor, active_user) -> None:
        p = _crear_pedido_aprobado(db, empresa, proveedor, active_user)
        # Crear 2 adjuntos en el original
        adj1 = CompraAdjunto(
            entidad_tipo=CompraAdjunto.ENTIDAD_TIPO_PEDIDO,
            entidad_id=p.id,
            nombre_archivo="factura.pdf",
            path_archivo="pedido_compra/1/abc_factura.pdf",
            mime_type="application/pdf",
            tamano_bytes=1234,
            tipo="factura",
            subido_por_id=active_user.id,
        )
        adj2 = CompraAdjunto(
            entidad_tipo=CompraAdjunto.ENTIDAD_TIPO_PEDIDO,
            entidad_id=p.id,
            nombre_archivo="presupuesto.pdf",
            path_archivo="pedido_compra/1/xyz_presupuesto.pdf",
            mime_type="application/pdf",
            tamano_bytes=5678,
            tipo="presupuesto",
            subido_por_id=active_user.id,
        )
        db.add_all([adj1, adj2])
        db.flush()

        clon = pedidos_service.corregir_pedido(
            db,
            pedido_original_id=p.id,
            cambios={"observaciones": "clonación adjuntos"},
            motivo_correccion="prueba adjuntos clonados",
            user_id=active_user.id,
        )
        db.flush()

        adjuntos_clon = (
            db.query(CompraAdjunto)
            .filter(
                CompraAdjunto.entidad_tipo == CompraAdjunto.ENTIDAD_TIPO_PEDIDO,
                CompraAdjunto.entidad_id == clon.id,
            )
            .order_by(CompraAdjunto.id.asc())
            .all()
        )
        assert len(adjuntos_clon) == 2
        # Mismo path físico (archivo inmutable reusado)
        paths_orig = {adj1.path_archivo, adj2.path_archivo}
        paths_clon = {a.path_archivo for a in adjuntos_clon}
        assert paths_orig == paths_clon

    def test_eventos_creado_y_cancelado_por_correccion_presentes(self, db, empresa, proveedor, active_user) -> None:
        p = _crear_pedido_aprobado(db, empresa, proveedor, active_user)
        clon = pedidos_service.corregir_pedido(
            db,
            pedido_original_id=p.id,
            cambios={"observaciones": "cambio observación"},
            motivo_correccion="test de eventos de corrección",
            user_id=active_user.id,
        )
        ev_clon = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_id == clon.id,
                CompraEvento.tipo == "creado_por_correccion_de",
            )
            .one()
        )
        ev_orig = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_id == p.id,
                CompraEvento.tipo == "cancelado_por_correccion",
            )
            .one()
        )
        assert ev_clon.payload["original_id"] == p.id
        assert ev_clon.payload["motivo"] == "test de eventos de corrección"
        assert ev_orig.payload["clon_id"] == clon.id
        assert ev_orig.payload["motivo"] == "test de eventos de corrección"


# ──────────────────────────────────────────────────────────────────────────
# TestCorregirConImputaciones — opción Z
# ──────────────────────────────────────────────────────────────────────────


def _crear_imputacion_directa(db, *, pedido, monto, proveedor, active_user) -> Imputacion:
    """Helper: inserta imputación destino pedido_compra para simular un pago."""
    # Usamos origen_tipo='orden_pago' con un ID dummy (no validamos existencia
    # del origen acá — es un test aislado del service de pedidos). En producción
    # viene de ordenes_pago_service.ejecutar_pago.
    imp = imputaciones_service.crear_imputacion(
        db,
        origen_tipo="orden_pago",
        origen_id=9_999_000 + pedido.id,  # ID ficticio pero único
        destino_tipo="pedido_compra",
        destino_id=pedido.id,
        monto_imputado=monto,
        moneda_imputada=pedido.moneda,
        proveedor_id=proveedor.id,
        creado_por_id=active_user.id,
    )
    return imp


class TestCorregirPedidoConImputaciones:
    def test_correccion_cosmetica_reaplica_imputaciones_inmediato(self, db, empresa, proveedor, active_user) -> None:
        """Pedido aprobado con 1 imputación. Corrección cosmética →
        clon nace aprobado, imputación original pasa a reversal, nueva
        imputación apunta al clon."""
        p = _crear_pedido_aprobado(db, empresa, proveedor, active_user, monto=Decimal("500"))
        imp = _crear_imputacion_directa(
            db, pedido=p, monto=Decimal("300"), proveedor=proveedor, active_user=active_user
        )
        imp_id_original = imp.id

        clon = pedidos_service.corregir_pedido(
            db,
            pedido_original_id=p.id,
            cambios={"numero_factura": "FA-COSMETICA"},
            motivo_correccion="cambio solo factura",
            user_id=active_user.id,
        )
        db.flush()

        # Reversal debe existir sobre la imputación original
        reversal = (
            db.query(Imputacion)
            .filter(
                Imputacion.reimputada_desde_id == imp_id_original,
                Imputacion.es_reversal.is_(True),
            )
            .one()
        )
        assert reversal.destino_id == p.id  # apunta al original (es reversal)

        # Nueva imputación apunta al clon
        nuevas_en_clon = (
            db.query(Imputacion)
            .filter(
                Imputacion.destino_tipo == "pedido_compra",
                Imputacion.destino_id == clon.id,
                Imputacion.es_reversal.is_(False),
            )
            .all()
        )
        assert len(nuevas_en_clon) == 1
        assert nuevas_en_clon[0].monto_imputado == Decimal("300")

    def test_correccion_financiera_difiere_reaplicacion_imputaciones_siguen_en_original(
        self, db, empresa, proveedor, active_user
    ) -> None:
        """Cambio de monto → clon nace pendiente_aprobacion. Imputaciones
        quedan CONGELADAS en el original (no se crean reversals aún)."""
        p = _crear_pedido_aprobado(db, empresa, proveedor, active_user, monto=Decimal("1000"))
        imp = _crear_imputacion_directa(
            db, pedido=p, monto=Decimal("400"), proveedor=proveedor, active_user=active_user
        )

        clon = pedidos_service.corregir_pedido(
            db,
            pedido_original_id=p.id,
            cambios={"monto": Decimal("1500")},
            motivo_correccion="ajuste monto por factura real",
            user_id=active_user.id,
        )
        db.flush()

        # Imputación original intacta, sin reversal
        reversals = (
            db.query(Imputacion)
            .filter(
                Imputacion.reimputada_desde_id == imp.id,
                Imputacion.es_reversal.is_(True),
            )
            .all()
        )
        assert reversals == []

        # El evento del clon trae imputaciones_pendientes_reaplicar
        ev_clon = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_id == clon.id,
                CompraEvento.tipo == "creado_por_correccion_de",
            )
            .one()
        )
        assert imp.id in ev_clon.payload["imputaciones_pendientes_reaplicar"]

    def test_aprobar_clon_financiero_dispara_transferencia_de_imputaciones(
        self, db, empresa, proveedor, active_user
    ) -> None:
        """Clon pendiente → aprobar → ejecuta reversals en original + nuevas
        imputaciones en clon + CC ajuste de cancelación del original."""
        p = _crear_pedido_aprobado(db, empresa, proveedor, active_user, monto=Decimal("1000"))
        imp = _crear_imputacion_directa(
            db, pedido=p, monto=Decimal("400"), proveedor=proveedor, active_user=active_user
        )

        clon = pedidos_service.corregir_pedido(
            db,
            pedido_original_id=p.id,
            cambios={"monto": Decimal("1200")},
            motivo_correccion="cambio financiero",
            user_id=active_user.id,
        )
        # Al aprobar el clon se dispara la transferencia
        pedidos_service.transicionar(db, pedido_id=clon.id, accion="aprobar", user_id=active_user.id)
        db.flush()
        db.refresh(clon)

        # 1. Reversal existe sobre la imputación original
        reversal = (
            db.query(Imputacion)
            .filter(
                Imputacion.reimputada_desde_id == imp.id,
                Imputacion.es_reversal.is_(True),
            )
            .one()
        )
        assert reversal.destino_id == p.id

        # 2. Nueva imputación apuntando al clon
        nuevas = (
            db.query(Imputacion)
            .filter(
                Imputacion.destino_tipo == "pedido_compra",
                Imputacion.destino_id == clon.id,
                Imputacion.es_reversal.is_(False),
            )
            .all()
        )
        assert len(nuevas) == 1
        assert nuevas[0].monto_imputado == Decimal("400")

        # 3. CC: haber de cancelación del original (ajuste signo -1 origen
        # 'cancelacion_pedido_por_correccion')
        cancelacion = (
            db.query(CCProveedorMovimiento)
            .filter(
                CCProveedorMovimiento.origen_tipo == "cancelacion_pedido_por_correccion",
                CCProveedorMovimiento.origen_id == p.id,
            )
            .all()
        )
        assert len(cancelacion) == 1
        assert cancelacion[0].signo_ajuste == -1

        # 4. Evento imputaciones_reaplicadas_por_correccion presente
        ev = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_id == clon.id,
                CompraEvento.tipo == "imputaciones_reaplicadas_por_correccion",
            )
            .one()
        )
        assert imp.id in ev.payload["imputaciones_origen_transferidas"]

    def test_rechazar_clon_financiero_no_toca_imputaciones_original(self, db, empresa, proveedor, active_user) -> None:
        """Clon pendiente → rechazar → imputaciones en original quedan intactas
        (no se ejecuta transferencia). El original sigue cancelado (D.2)."""
        p = _crear_pedido_aprobado(db, empresa, proveedor, active_user, monto=Decimal("1000"))
        imp = _crear_imputacion_directa(
            db, pedido=p, monto=Decimal("250"), proveedor=proveedor, active_user=active_user
        )

        clon = pedidos_service.corregir_pedido(
            db,
            pedido_original_id=p.id,
            cambios={"monto": Decimal("900")},
            motivo_correccion="cambio que se rechaza luego",
            user_id=active_user.id,
        )
        # Rechazar el clon (cancelar definitivamente desde pendiente_aprobacion)
        pedidos_service.transicionar(
            db,
            pedido_id=clon.id,
            accion="rechazar_cancelar",
            user_id=active_user.id,
            motivo="no aplica el cambio",
        )
        db.flush()

        # Imputación original sigue viva (sin reversal)
        reversals = (
            db.query(Imputacion)
            .filter(
                Imputacion.reimputada_desde_id == imp.id,
                Imputacion.es_reversal.is_(True),
            )
            .all()
        )
        assert reversals == []

        # El clon no tiene ninguna imputación (nunca se transfirió)
        nuevas_clon = (
            db.query(Imputacion)
            .filter(
                Imputacion.destino_tipo == "pedido_compra",
                Imputacion.destino_id == clon.id,
            )
            .all()
        )
        assert nuevas_clon == []
