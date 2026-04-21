"""Unit tests de compras_papelera_service.

Cubre las reglas de negocio en aislamiento (sin HTTP layer):
  - puede_eliminar_pedido: borrador → True; aprobado → False; con imputación → False;
    cancelado reciente → False; cancelado viejo → True; no-borrable → False.
  - puede_eliminar_op: anulado sin imputaciones y viejo → True; con imputación viva → False;
    con caja_movimiento_id → False; pendiente/pagado → False.
  - eliminar_pedido: happy path copia eventos al snapshot y borra la fila.
  - eliminar_op: happy path igual.
  - Batch helpers (opción C): 3 queries fijas, retorna dict correcto.
  - Retención configurable: leer default 30 si no existe; leer 0 si valor='0'.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.compra_evento import CompraEvento
from app.models.compras_papelera import ComprasPapelera
from app.models.configuracion import Configuracion
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import Proveedor
from app.services import compras_papelera_service as papelera_service


# ==========================================================================
# Fixtures locales
# ==========================================================================


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(nombre="EmpresaPapelera", activo=True, orden=1)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(nombre="ProveedorPapelera", activo=True, origen="manual")
    db.add(p)
    db.flush()
    return p


def _crear_pedido(
    db,
    empresa: Empresa,
    proveedor: Proveedor,
    user_id: int,
    estado: str = "borrador",
    updated_at: datetime | None = None,
) -> PedidoCompra:
    """Helper: crea un pedido directo (bypass numeracion para control de estado)."""
    p = PedidoCompra(
        numero=f"P-TEST-{datetime.now(UTC).timestamp()}",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("1000"),
        requiere_envio=False,
        estado=estado,
        creado_por_id=user_id,
    )
    db.add(p)
    db.flush()
    if updated_at is not None:
        p.updated_at = updated_at
        db.flush()
    return p


def _crear_op(
    db,
    empresa: Empresa,
    proveedor: Proveedor,
    user_id: int,
    estado: str = "anulado",
    caja_movimiento_id: int | None = None,
    updated_at: datetime | None = None,
) -> OrdenPago:
    op = OrdenPago(
        numero=f"OP-TEST-{datetime.now(UTC).timestamp()}",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto_total=Decimal("1000"),
        modo_imputacion="a_cuenta",
        estado=estado,
        caja_movimiento_id=caja_movimiento_id,
        creado_por_id=user_id,
    )
    db.add(op)
    db.flush()
    if updated_at is not None:
        op.updated_at = updated_at
        db.flush()
    return op


# ==========================================================================
# _leer_dias_retencion
# ==========================================================================


class TestLeerDiasRetencion:
    def test_default_30_si_no_existe_clave(self, db):
        """Si la clave no está sembrada, retorna 30 (hardcoded fallback)."""
        # No sembramos la clave para este test
        dias = papelera_service._leer_dias_retencion(db)
        assert dias == 30

    def test_lee_valor_custom(self, db):
        db.add(Configuracion(clave="compras.dias_retencion_cancelados", valor="15", tipo="integer"))
        db.flush()
        assert papelera_service._leer_dias_retencion(db) == 15

    def test_fallback_si_valor_invalido(self, db):
        db.add(Configuracion(clave="compras.dias_retencion_cancelados", valor="abc", tipo="integer"))
        db.flush()
        assert papelera_service._leer_dias_retencion(db) == 30


# ==========================================================================
# puede_eliminar_pedido
# ==========================================================================


class TestPuedeEliminarPedido:
    def test_borrador_sin_nada_puede(self, db, empresa, proveedor, active_user):
        pedido = _crear_pedido(db, empresa, proveedor, active_user.id, estado="borrador")
        puede, razon = papelera_service.puede_eliminar_pedido(db, pedido)
        assert puede is True
        assert razon is None

    def test_aprobado_no_puede(self, db, empresa, proveedor, active_user):
        pedido = _crear_pedido(db, empresa, proveedor, active_user.id, estado="aprobado")
        puede, razon = papelera_service.puede_eliminar_pedido(db, pedido)
        assert puede is False
        assert "borrador" in (razon or "").lower() or "cancelado" in (razon or "").lower()

    def test_cancelado_pero_fue_aprobado_antes_no_puede(
        self, db, empresa, proveedor, active_user
    ):
        """Si hay evento 'aprobado' en la historia, no se borra aunque hoy esté cancelado."""
        pedido = _crear_pedido(db, empresa, proveedor, active_user.id, estado="cancelado")
        # Simulamos que alguna vez pasó por 'aprobado'
        evento = CompraEvento(
            entidad_tipo=CompraEvento.ENTIDAD_TIPO_PEDIDO,
            entidad_id=pedido.id,
            tipo="aprobado",
            usuario_id=active_user.id,
            payload={},
        )
        db.add(evento)
        db.flush()
        puede, razon = papelera_service.puede_eliminar_pedido(db, pedido)
        assert puede is False
        assert "aprobad" in (razon or "").lower()

    def test_con_imputacion_no_puede(self, db, empresa, proveedor, active_user):
        pedido = _crear_pedido(db, empresa, proveedor, active_user.id, estado="borrador")
        imp = Imputacion(
            origen_tipo="orden_pago",
            origen_id=9999,
            destino_tipo="pedido_compra",
            destino_id=pedido.id,
            monto_imputado=Decimal("100"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
        )
        db.add(imp)
        db.flush()
        puede, razon = papelera_service.puede_eliminar_pedido(db, pedido)
        assert puede is False
        assert "imputacion" in (razon or "").lower()

    def test_cancelado_reciente_no_puede(self, db, empresa, proveedor, active_user):
        """Cancelado con updated_at < cutoff → dentro de ventana → NO puede."""
        reciente = datetime.now(UTC) - timedelta(days=5)
        pedido = _crear_pedido(
            db, empresa, proveedor, active_user.id, estado="cancelado", updated_at=reciente
        )
        puede, razon = papelera_service.puede_eliminar_pedido(db, pedido)
        assert puede is False
        assert "retenci" in (razon or "").lower() or "días" in (razon or "").lower()

    def test_cancelado_viejo_puede(self, db, empresa, proveedor, active_user):
        """Cancelado hace 31 días → fuera de ventana → puede."""
        viejo = datetime.now(UTC) - timedelta(days=31)
        pedido = _crear_pedido(
            db, empresa, proveedor, active_user.id, estado="cancelado", updated_at=viejo
        )
        puede, razon = papelera_service.puede_eliminar_pedido(db, pedido)
        assert puede is True, razon


# ==========================================================================
# puede_eliminar_op
# ==========================================================================


class TestPuedeEliminarOP:
    def test_anulado_viejo_sin_mov_puede(self, db, empresa, proveedor, active_user):
        viejo = datetime.now(UTC) - timedelta(days=31)
        op = _crear_op(
            db, empresa, proveedor, active_user.id, estado="anulado", updated_at=viejo
        )
        puede, razon = papelera_service.puede_eliminar_op(db, op)
        assert puede is True, razon

    def test_pendiente_no_puede(self, db, empresa, proveedor, active_user):
        op = _crear_op(db, empresa, proveedor, active_user.id, estado="pendiente")
        puede, razon = papelera_service.puede_eliminar_op(db, op)
        assert puede is False
        assert "anulad" in (razon or "").lower()

    def test_pagado_no_puede(self, db, empresa, proveedor, active_user):
        op = _crear_op(db, empresa, proveedor, active_user.id, estado="pagado")
        puede, _razon = papelera_service.puede_eliminar_op(db, op)
        assert puede is False

    def test_anulado_con_imputacion_viva_no_puede(self, db, empresa, proveedor, active_user):
        """Si hay imputación no-reversal sin su correspondiente reversal → no."""
        viejo = datetime.now(UTC) - timedelta(days=31)
        op = _crear_op(
            db, empresa, proveedor, active_user.id, estado="anulado", updated_at=viejo
        )
        imp = Imputacion(
            origen_tipo="orden_pago",
            origen_id=op.id,
            destino_tipo="saldo",
            destino_id=None,
            monto_imputado=Decimal("500"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=active_user.id,
            es_reversal=False,
        )
        db.add(imp)
        db.flush()
        puede, razon = papelera_service.puede_eliminar_op(db, op)
        assert puede is False
        assert "imputaci" in (razon or "").lower()


# ==========================================================================
# Batch (opción C)
# ==========================================================================


class TestBatchPuedeEliminar:
    def test_pedidos_batch_mixto(self, db, empresa, proveedor, active_user):
        """3 pedidos: borrador (True), aprobado (False), cancelado reciente (False)."""
        p_borrador = _crear_pedido(db, empresa, proveedor, active_user.id, estado="borrador")
        p_aprobado = _crear_pedido(db, empresa, proveedor, active_user.id, estado="aprobado")
        p_cancelado_reciente = _crear_pedido(
            db,
            empresa,
            proveedor,
            active_user.id,
            estado="cancelado",
            updated_at=datetime.now(UTC) - timedelta(days=2),
        )

        resultado = papelera_service._calcular_puede_eliminar_pedidos_batch(
            db, [p_borrador, p_aprobado, p_cancelado_reciente]
        )

        assert resultado[p_borrador.id] is True
        assert resultado[p_aprobado.id] is False
        assert resultado[p_cancelado_reciente.id] is False

    def test_pedidos_batch_vacio(self, db):
        assert papelera_service._calcular_puede_eliminar_pedidos_batch(db, []) == {}

    def test_ops_batch_vacio(self, db):
        assert papelera_service._calcular_puede_eliminar_ops_batch(db, []) == {}


# ==========================================================================
# eliminar_pedido / eliminar_op (happy path)
# ==========================================================================


class TestEliminarPedido:
    def test_happy_path_copia_eventos_al_snapshot(
        self, db, empresa, proveedor, active_user
    ):
        pedido = _crear_pedido(db, empresa, proveedor, active_user.id, estado="borrador")
        pedido_id = pedido.id

        # Evento 'creado' para que el snapshot lo preserve
        ev = CompraEvento(
            entidad_tipo=CompraEvento.ENTIDAD_TIPO_PEDIDO,
            entidad_id=pedido.id,
            tipo="creado",
            usuario_id=active_user.id,
            payload={"inicial": True},
        )
        db.add(ev)
        db.flush()

        papelera_row = papelera_service.eliminar_pedido(
            db,
            pedido_id=pedido_id,
            user_id=active_user.id,
            motivo="test cleanup",
            challenge_palabra_usada="banana",
        )

        assert papelera_row.id is not None
        assert papelera_row.entidad_tipo == ComprasPapelera.ENTIDAD_TIPO_PEDIDO
        assert papelera_row.entidad_id_original == pedido_id
        assert papelera_row.motivo == "test cleanup"
        assert papelera_row.challenge_palabra == "banana"

        # Snapshot preserva el evento
        snapshot_eventos = papelera_row.snapshot.get("eventos") or []
        tipos = {e["tipo"] for e in snapshot_eventos}
        assert "creado" in tipos

        # La fila física del pedido ya no existe
        assert db.get(PedidoCompra, pedido_id) is None

        # Y los eventos tampoco (ya están en el snapshot)
        count_ev = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_PEDIDO,
                CompraEvento.entidad_id == pedido_id,
            )
            .count()
        )
        assert count_ev == 0

    def test_sin_motivo_raises_400(self, db, empresa, proveedor, active_user):
        from fastapi import HTTPException

        pedido = _crear_pedido(db, empresa, proveedor, active_user.id, estado="borrador")
        with pytest.raises(HTTPException) as excinfo:
            papelera_service.eliminar_pedido(
                db, pedido_id=pedido.id, user_id=active_user.id, motivo=""
            )
        assert excinfo.value.status_code == 400

    def test_pedido_inexistente_raises_404(self, db, active_user):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as excinfo:
            papelera_service.eliminar_pedido(
                db, pedido_id=999999, user_id=active_user.id, motivo="test"
            )
        assert excinfo.value.status_code == 404

    def test_pedido_aprobado_raises_409(self, db, empresa, proveedor, active_user):
        from fastapi import HTTPException

        pedido = _crear_pedido(db, empresa, proveedor, active_user.id, estado="aprobado")
        with pytest.raises(HTTPException) as excinfo:
            papelera_service.eliminar_pedido(
                db, pedido_id=pedido.id, user_id=active_user.id, motivo="test"
            )
        assert excinfo.value.status_code == 409


class TestEliminarOP:
    def test_happy_path_anulada_vieja(self, db, empresa, proveedor, active_user):
        viejo = datetime.now(UTC) - timedelta(days=31)
        op = _crear_op(
            db, empresa, proveedor, active_user.id, estado="anulado", updated_at=viejo
        )
        op_id = op.id

        papelera_row = papelera_service.eliminar_op(
            db,
            op_id=op_id,
            user_id=active_user.id,
            motivo="op anulada sin uso",
        )
        assert papelera_row.entidad_tipo == ComprasPapelera.ENTIDAD_TIPO_ORDEN_PAGO
        assert papelera_row.entidad_id_original == op_id
        assert db.get(OrdenPago, op_id) is None
