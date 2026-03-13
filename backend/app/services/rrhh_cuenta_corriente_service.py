"""
Servicio de cuenta corriente de empleados — Phase 6.

Gestiona compras de empleados (cargos) y pagos/deducciones (abonos).
Soporta cuotas para compras financiadas con liquidación mensual.

Convención de saldo:
- Positivo = el empleado DEBE
- Negativo = la empresa debe al empleado (crédito)
- Los montos en movimientos son siempre positivos; el tipo determina dirección.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.rrhh_cuenta_corriente import (
    RRHHCuentaCorriente,
    RRHHCuentaCorrienteMovimiento,
    TipoMovimientoCC,
)


class CuentaCorrienteService:
    """Servicio para operaciones de cuenta corriente de empleados."""

    def __init__(self, db: Session):
        self.db = db

    def obtener_o_crear_cuenta(self, empleado_id: int) -> RRHHCuentaCorriente:
        """
        Obtiene la cuenta corriente del empleado.
        Si no existe, la crea con saldo 0 (lazy creation).
        """
        cuenta = self.db.query(RRHHCuentaCorriente).filter(RRHHCuentaCorriente.empleado_id == empleado_id).first()
        if not cuenta:
            cuenta = RRHHCuentaCorriente(
                empleado_id=empleado_id,
                saldo=Decimal("0"),
            )
            self.db.add(cuenta)
            self.db.flush()  # get id without full commit
        return cuenta

    def registrar_cargo(
        self,
        empleado_id: int,
        monto: Decimal,
        concepto: str,
        registrado_por_id: int,
        descripcion: Optional[str] = None,
        item_id: Optional[int] = None,
        ct_transaction: Optional[int] = None,
        cuotas: int = 1,
    ) -> RRHHCuentaCorrienteMovimiento:
        """
        Registra una compra (cargo) en la cuenta del empleado.

        Si cuotas > 1, registra el cargo completo como un solo movimiento
        con cuota_numero=None, cuota_total=cuotas. Las cuotas individuales
        se generan con liquidacion_mensual().

        Args:
            empleado_id: ID del empleado
            monto: Monto total de la compra (siempre positivo)
            concepto: Descripción de la compra
            registrado_por_id: Usuario que registra
            descripcion: Descripción adicional (opcional)
            item_id: ID del item ERP (opcional)
            ct_transaction: ID de transacción comercial (opcional)
            cuotas: Cantidad de cuotas (1 = pago único)

        Returns:
            El movimiento de cargo creado
        """
        if monto <= 0:
            raise ValueError("El monto del cargo debe ser positivo")
        if cuotas < 1:
            raise ValueError("Las cuotas deben ser al menos 1")

        cuenta = self.obtener_o_crear_cuenta(empleado_id)

        # Actualizar saldo: cargo suma
        nuevo_saldo = Decimal(str(cuenta.saldo)) + monto
        cuenta.saldo = nuevo_saldo

        movimiento = RRHHCuentaCorrienteMovimiento(
            cuenta_id=cuenta.id,
            empleado_id=empleado_id,
            tipo=TipoMovimientoCC.CARGO.value,
            monto=monto,
            fecha=date.today(),
            concepto=concepto,
            descripcion=descripcion,
            item_id=item_id,
            ct_transaction=ct_transaction,
            cuota_numero=None if cuotas <= 1 else None,
            cuota_total=cuotas if cuotas > 1 else None,
            saldo_posterior=nuevo_saldo,
            registrado_por_id=registrado_por_id,
        )
        self.db.add(movimiento)
        self.db.flush()
        return movimiento

    def registrar_abono(
        self,
        empleado_id: int,
        monto: Decimal,
        concepto: str,
        registrado_por_id: int,
        descripcion: Optional[str] = None,
        cuota_numero: Optional[int] = None,
        cuota_total: Optional[int] = None,
    ) -> RRHHCuentaCorrienteMovimiento:
        """
        Registra un pago/deducción (abono) en la cuenta del empleado.

        Args:
            empleado_id: ID del empleado
            monto: Monto del abono (siempre positivo)
            concepto: Descripción del abono
            registrado_por_id: Usuario que registra
            descripcion: Descripción adicional (opcional)
            cuota_numero: Número de cuota (para pagos en cuotas)
            cuota_total: Total de cuotas (para pagos en cuotas)

        Returns:
            El movimiento de abono creado
        """
        if monto <= 0:
            raise ValueError("El monto del abono debe ser positivo")

        cuenta = self.obtener_o_crear_cuenta(empleado_id)

        # Actualizar saldo: abono resta
        nuevo_saldo = Decimal(str(cuenta.saldo)) - monto
        cuenta.saldo = nuevo_saldo

        movimiento = RRHHCuentaCorrienteMovimiento(
            cuenta_id=cuenta.id,
            empleado_id=empleado_id,
            tipo=TipoMovimientoCC.ABONO.value,
            monto=monto,
            fecha=date.today(),
            concepto=concepto,
            descripcion=descripcion,
            cuota_numero=cuota_numero,
            cuota_total=cuota_total,
            saldo_posterior=nuevo_saldo,
            registrado_por_id=registrado_por_id,
        )
        self.db.add(movimiento)
        self.db.flush()
        return movimiento

    def liquidacion_mensual(
        self,
        mes: int,
        anio: int,
        registrado_por_id: int,
    ) -> dict:
        """
        Genera abonos mensuales para empleados con cargos en cuotas pendientes.

        Busca movimientos tipo CARGO que tienen cuota_total > 1 y calcula
        cuántas cuotas ya fueron abonadas. Si quedan cuotas pendientes,
        genera un abono por el monto de la cuota.

        Args:
            mes: Mes de la liquidación (1-12)
            anio: Año de la liquidación
            registrado_por_id: Usuario que ejecuta la liquidación

        Returns:
            { "procesados": int, "abonos_generados": int, "monto_total": Decimal }
        """
        # Buscar cargos con cuotas (cuota_total > 1)
        cargos_con_cuotas = (
            self.db.query(RRHHCuentaCorrienteMovimiento)
            .filter(
                RRHHCuentaCorrienteMovimiento.tipo == TipoMovimientoCC.CARGO.value,
                RRHHCuentaCorrienteMovimiento.cuota_total.isnot(None),
                RRHHCuentaCorrienteMovimiento.cuota_total > 1,
            )
            .all()
        )

        procesados = 0
        abonos_generados = 0
        monto_total = Decimal("0")

        for cargo in cargos_con_cuotas:
            # Contar cuántos abonos de cuota ya existen para este cargo
            # Identificamos las cuotas de un cargo por: mismo empleado, mismo concepto
            # con cuota_total == cargo.cuota_total y tipo == ABONO
            abonos_existentes = (
                self.db.query(RRHHCuentaCorrienteMovimiento)
                .filter(
                    RRHHCuentaCorrienteMovimiento.empleado_id == cargo.empleado_id,
                    RRHHCuentaCorrienteMovimiento.tipo == TipoMovimientoCC.ABONO.value,
                    RRHHCuentaCorrienteMovimiento.cuota_total == cargo.cuota_total,
                    RRHHCuentaCorrienteMovimiento.concepto == f"Cuota - {cargo.concepto}",
                )
                .count()
            )

            if abonos_existentes >= cargo.cuota_total:
                # Ya se pagaron todas las cuotas
                continue

            procesados += 1
            cuota_siguiente = abonos_existentes + 1
            monto_cuota = Decimal(str(cargo.monto)) / cargo.cuota_total

            # Redondear a 2 decimales
            monto_cuota = round(monto_cuota, 2)

            # En la última cuota, ajustar por diferencia de redondeo
            if cuota_siguiente == cargo.cuota_total:
                monto_pagado = monto_cuota * (cargo.cuota_total - 1)
                monto_cuota = Decimal(str(cargo.monto)) - monto_pagado

            self.registrar_abono(
                empleado_id=cargo.empleado_id,
                monto=monto_cuota,
                concepto=f"Cuota - {cargo.concepto}",
                registrado_por_id=registrado_por_id,
                descripcion=(f"Liquidación {mes:02d}/{anio} - Cuota {cuota_siguiente}/{cargo.cuota_total}"),
                cuota_numero=cuota_siguiente,
                cuota_total=cargo.cuota_total,
            )
            abonos_generados += 1
            monto_total += monto_cuota

        return {
            "procesados": procesados,
            "abonos_generados": abonos_generados,
            "monto_total": monto_total,
        }
