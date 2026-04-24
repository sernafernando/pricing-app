"""
Tests unitarios de `reconciliar_diario` (COMPRAS-3.6).

Cubre:
  - Sin movimientos → 0 comparaciones, 0 divergencias.
  - 1 divergencia ARS → 1 log + 1 alerta + 1 notificación.
  - Diferencia dentro de tolerancia → estado='ok', sin alerta.
  - Tolerancias distintas por moneda — ARS > USD por default.
  - Sin snapshot para el proveedor → skip (no compara).
  - Idempotencia: correr 2 veces con la misma fecha rebota por UNIQUE.
  - Validación: tolerancias debe tener ARS y USD.

Los tests inyectan snapshots directamente en `cuentas_corrientes_proveedores`
(tabla sincronizada del ERP) usando el mismo SessionLocal del conftest.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.alerta import Alerta
from app.models.cc_reconciliacion_log import CCReconciliacionLog
from app.models.cuenta_corriente_proveedor import CuentaCorrienteProveedor
from app.models.empresa import Empresa
from app.models.notificacion import Notificacion
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services.cc_proveedor_service import (
    insertar_mov,
    reconciliar_diario,
)


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=1, nombre="Empresa Recon Test", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(
        id=100,
        nombre="Proveedor Recon ARS",
        supp_id=100,
        activo=True,
        origen=OrigenProveedor.ERP.value,
    )
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def proveedor2(db) -> Proveedor:
    prov = Proveedor(
        id=200,
        nombre="Proveedor Recon USD",
        supp_id=200,
        activo=True,
        origen=OrigenProveedor.ERP.value,
    )
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def tolerancias_default() -> dict[str, Decimal]:
    return {"ARS": Decimal("100.00"), "USD": Decimal("1.00")}


def _insertar_snapshot(db, *, proveedor_id: int, pendiente: Decimal) -> None:
    """Inserta una fila en cuentas_corrientes_proveedores (snapshot ERP)."""
    cc = CuentaCorrienteProveedor(
        bra_id=1,
        id_proveedor=proveedor_id,
        proveedor=f"Prov {proveedor_id}",
        monto_total=pendiente,
        monto_abonado=Decimal("0"),
        pendiente=pendiente,
    )
    db.add(cc)
    db.flush()


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestToleranciasValidacion:
    def test_tolerancias_sin_ars_raise(self, db):
        with pytest.raises(ValueError, match="ARS"):
            reconciliar_diario(
                db,
                fecha_corrida=date.today(),
                tolerancias={"USD": Decimal("1")},
            )

    def test_tolerancias_sin_usd_raise(self, db):
        with pytest.raises(ValueError, match="USD"):
            reconciliar_diario(
                db,
                fecha_corrida=date.today(),
                tolerancias={"ARS": Decimal("100")},
            )


class TestReconciliarSinDivergencias:
    def test_sin_movimientos_retorna_cero(self, db, tolerancias_default):
        resumen = reconciliar_diario(
            db,
            fecha_corrida=date.today(),
            tolerancias=tolerancias_default,
        )
        assert resumen == {
            "proveedores_procesados": 0,
            "comparaciones": 0,
            "divergencias": 0,
            "alertas_creadas": 0,
            "notificaciones_creadas": 0,
        }

    def test_dentro_de_tolerancia_no_crea_alerta(self, db, empresa, proveedor, tolerancias_default):
        # Movimiento: debe=1000 ARS. Snapshot: 1050 ARS. Diferencia=50 < 100 (tolerancia ARS).
        insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 4, 10),
            tipo="debe",
            monto=Decimal("1000"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=None,
        )
        _insertar_snapshot(db, proveedor_id=proveedor.id, pendiente=Decimal("1050"))

        resumen = reconciliar_diario(
            db,
            fecha_corrida=date(2026, 4, 20),
            tolerancias=tolerancias_default,
        )

        assert resumen["proveedores_procesados"] == 1
        assert resumen["comparaciones"] == 1
        assert resumen["divergencias"] == 0
        assert resumen["alertas_creadas"] == 0

        # Fila de log existe con estado='ok'
        log = db.query(CCReconciliacionLog).filter_by(proveedor_id=proveedor.id).one()
        assert log.estado == "ok"
        assert log.tolerancia_aplicada == Decimal("100.00")
        assert log.diferencia == Decimal("50")


class TestReconciliarConDivergencias:
    def test_una_divergencia_ars_crea_alerta_y_notif(self, db, empresa, proveedor, admin_user, tolerancias_default):
        # Sub-batch 2: el fan-out de notificaciones ahora se hace vía
        # `crear_notificaciones_para_permisos` (permiso efectivo) en vez del
        # hardcode por `RolUsuario.ADMIN`. Para que el admin_user del conftest
        # (rol=ADMIN sin overrides) matchee, seedeamos el permiso
        # correspondiente a su rol.
        from app.models.permiso import Permiso, RolPermisoBase  # noqa: PLC0415

        p = Permiso(
            codigo="administracion.gestionar_ordenes_compra",
            nombre="Gestionar órdenes de compra",
            categoria="administracion",
            orden=1,
        )
        db.add(p)
        db.flush()
        db.add(RolPermisoBase(rol_id=admin_user.rol_id, permiso_id=p.id))
        db.flush()

        # Mayor=2000 ARS, snapshot=1000 ARS, diferencia=1000 > 100 → divergencia
        insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 4, 10),
            tipo="debe",
            monto=Decimal("2000"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=None,
        )
        _insertar_snapshot(db, proveedor_id=proveedor.id, pendiente=Decimal("1000"))

        resumen = reconciliar_diario(
            db,
            fecha_corrida=date(2026, 4, 20),
            tolerancias=tolerancias_default,
        )

        assert resumen["divergencias"] == 1
        assert resumen["alertas_creadas"] == 1
        assert resumen["notificaciones_creadas"] == 1

        log = db.query(CCReconciliacionLog).filter_by(proveedor_id=proveedor.id).one()
        assert log.estado == "divergencia"
        assert log.diferencia == Decimal("1000")
        assert log.alerta_id is not None
        assert log.notificacion_id is not None

        # Alerta tiene rol ADMIN
        alerta = db.query(Alerta).filter_by(id=log.alerta_id).one()
        assert "ADMIN" in alerta.roles_destinatarios
        assert alerta.variant == "warning"
        assert alerta.activo is True

        # Notificación está dirigida al admin y tiene severidad WARNING
        notif = db.query(Notificacion).filter_by(id=log.notificacion_id).one()
        assert notif.user_id == admin_user.id
        assert notif.tipo == "cc_reconciliacion_divergencia"

    def test_sin_snapshot_se_saltea(self, db, empresa, proveedor, tolerancias_default):
        insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 4, 10),
            tipo="debe",
            monto=Decimal("999"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=None,
        )
        # no insertamos snapshot

        resumen = reconciliar_diario(
            db,
            fecha_corrida=date(2026, 4, 20),
            tolerancias=tolerancias_default,
        )

        assert resumen["proveedores_procesados"] == 1
        assert resumen["comparaciones"] == 0  # sin snapshot → skip
        assert resumen["divergencias"] == 0

    def test_moneda_usd_sin_snapshot_map_no_compara(self, db, empresa, proveedor2, tolerancias_default):
        """La política actual: el snapshot `cuentas_corrientes_proveedores`
        NO diferencia moneda, así que USD siempre queda sin comparación."""
        insertar_mov(
            db,
            proveedor_id=proveedor2.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 4, 10),
            tipo="debe",
            monto=Decimal("50"),
            moneda="USD",
            origen_tipo="factura_erp",
            origen_id=None,
        )
        _insertar_snapshot(db, proveedor_id=proveedor2.id, pendiente=Decimal("50000"))  # ARS

        resumen = reconciliar_diario(
            db,
            fecha_corrida=date(2026, 4, 20),
            tolerancias=tolerancias_default,
        )

        # El único movimiento es USD, el snapshot solo aplica para ARS →
        # 0 comparaciones porque no hay mov ARS ni hay mapping USD.
        assert resumen["comparaciones"] == 0


class TestToleranciaPorMoneda:
    def test_tolerancia_ars_distinta_que_usd(self, db, empresa, proveedor, tolerancias_default):
        """Con tolerancia ARS=100 y USD=1, una diferencia de 50 ARS es OK
        pero una de 50 USD sería una divergencia severa."""
        insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 4, 10),
            tipo="debe",
            monto=Decimal("1050"),  # mayor=1050
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=None,
        )
        _insertar_snapshot(db, proveedor_id=proveedor.id, pendiente=Decimal("1000"))  # snap=1000

        resumen = reconciliar_diario(
            db,
            fecha_corrida=date(2026, 4, 20),
            tolerancias=tolerancias_default,
        )

        # Diferencia=50, tolerancia ARS=100 → 'ok'
        assert resumen["divergencias"] == 0
        log = db.query(CCReconciliacionLog).filter_by(proveedor_id=proveedor.id).one()
        assert log.estado == "ok"
        assert log.tolerancia_aplicada == Decimal("100.00")

    def test_tolerancia_custom_mas_estricta(self, db, empresa, proveedor):
        """Con tolerancia ARS=10, la misma diferencia de 50 ahora es divergencia."""
        insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 4, 10),
            tipo="debe",
            monto=Decimal("1050"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=None,
        )
        _insertar_snapshot(db, proveedor_id=proveedor.id, pendiente=Decimal("1000"))

        resumen = reconciliar_diario(
            db,
            fecha_corrida=date(2026, 4, 20),
            tolerancias={"ARS": Decimal("10"), "USD": Decimal("1")},
        )

        assert resumen["divergencias"] == 1
        log = db.query(CCReconciliacionLog).filter_by(proveedor_id=proveedor.id).one()
        assert log.estado == "divergencia"
        assert log.tolerancia_aplicada == Decimal("10")


class TestIdempotencia:
    def test_rerun_misma_fecha_rebota_por_unique(self, db, empresa, proveedor, tolerancias_default):
        """La UNIQUE (fecha_corrida, proveedor_id, moneda) debe bloquear
        la segunda corrida con la misma fecha. El caller (cron) debe
        capturar IntegrityError y rollbackear."""
        from sqlalchemy.exc import IntegrityError

        insertar_mov(
            db,
            proveedor_id=proveedor.id,
            empresa_id=empresa.id,
            fecha_movimiento=date(2026, 4, 10),
            tipo="debe",
            monto=Decimal("1000"),
            moneda="ARS",
            origen_tipo="factura_erp",
            origen_id=None,
        )
        _insertar_snapshot(db, proveedor_id=proveedor.id, pendiente=Decimal("1050"))

        fecha = date(2026, 4, 20)
        r1 = reconciliar_diario(db, fecha_corrida=fecha, tolerancias=tolerancias_default)
        db.flush()
        assert r1["comparaciones"] == 1

        # Segunda corrida con misma fecha → UNIQUE violation al flush
        with pytest.raises(IntegrityError):
            reconciliar_diario(db, fecha_corrida=fecha, tolerancias=tolerancias_default)
