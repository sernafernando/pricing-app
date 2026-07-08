"""
Servicio de Banco — Bank account module.

Gestiona cuentas bancarias (BancoEmpresa), movimientos (BancoMovimiento)
con balance atómico usando SELECT FOR UPDATE (mirrors CajaService pattern).

Convención de saldo:
- monto siempre positivo; el tipo (ingreso/egreso) determina dirección
- saldo_posterior = snapshot del saldo de la cuenta DESPUÉS de cada movimiento
- saldo_actual en BancoEmpresa = denormalizado, updated transaccionalmente
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session, joinedload

from app.models.banco_empresa import BancoEmpresa
from app.models.banco_movimiento import BancoMovimiento

# Sentinel: distinguishes "not passed" from "explicitly passed as None"
_UNSET = object()


class BancoService:
    """Servicio para operaciones de cuenta bancaria."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ──────────────────────────────────────────────
    # BancoEmpresa CRUD
    # ──────────────────────────────────────────────

    def listar_bancos(
        self,
        activo: Optional[bool] = None,
        empresa_id: Optional[int] = None,
    ) -> list[BancoEmpresa]:
        """Lista cuentas bancarias con filtros opcionales."""
        query = self.db.query(BancoEmpresa)
        if activo is not None:
            query = query.filter(BancoEmpresa.activo == activo)
        if empresa_id is not None:
            query = query.filter(BancoEmpresa.empresa_id == empresa_id)
        return query.order_by(BancoEmpresa.banco).all()

    def obtener_banco(self, banco_id: int) -> BancoEmpresa:
        """Obtiene banco por ID o lanza 404."""
        banco = self.db.query(BancoEmpresa).filter(BancoEmpresa.id == banco_id).first()
        if not banco:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Cuenta bancaria {banco_id} no encontrada",
            )
        return banco

    def crear_banco(
        self,
        banco: str,
        empresa_id: Optional[int],
        moneda: str,
        saldo_inicial: Decimal,
        tipo_cuenta: Optional[str] = None,
        cbu: Optional[str] = None,
        alias: Optional[str] = None,
        numero_cuenta: Optional[str] = None,
        sucursal: Optional[str] = None,
        titular: Optional[str] = None,
        cuit_titular: Optional[str] = None,
        notas: Optional[str] = None,
    ) -> BancoEmpresa:
        """Crea cuenta bancaria con saldo_actual = saldo_inicial."""
        banco_obj = BancoEmpresa(
            banco=banco,
            empresa_id=empresa_id,
            moneda=moneda,
            saldo_inicial=saldo_inicial,
            saldo_actual=saldo_inicial,  # Initialize running balance
            tipo_cuenta=tipo_cuenta,
            cbu=cbu,
            alias=alias,
            numero_cuenta=numero_cuenta,
            sucursal=sucursal,
            titular=titular,
            cuit_titular=cuit_titular,
            notas=notas,
        )
        self.db.add(banco_obj)
        self.db.flush()
        return banco_obj

    def actualizar_banco(
        self,
        banco_id: int,
        banco: Optional[str] = None,
        tipo_cuenta: Optional[str] = None,
        cbu: Optional[str] = None,
        alias: Optional[str] = None,
        numero_cuenta: Optional[str] = None,
        sucursal: Optional[str] = None,
        moneda: Optional[str] = None,
        titular: Optional[str] = None,
        cuit_titular: Optional[str] = None,
        saldo_inicial: Optional[Decimal] = None,
        notas: Optional[str] = None,
        activo: Optional[bool] = None,
        empresa_id: object = _UNSET,
    ) -> BancoEmpresa:
        """Actualiza campos de una cuenta bancaria.

        empresa_id uses a sentinel default so that passing empresa_id=None
        explicitly clears the field (assigns to NULL), whereas not passing it
        leaves the existing value unchanged.
        """
        banco_obj = self.obtener_banco(banco_id)
        if banco is not None:
            banco_obj.banco = banco
        if tipo_cuenta is not None:
            banco_obj.tipo_cuenta = tipo_cuenta
        if cbu is not None:
            banco_obj.cbu = cbu
        if alias is not None:
            banco_obj.alias = alias
        if numero_cuenta is not None:
            banco_obj.numero_cuenta = numero_cuenta
        if sucursal is not None:
            banco_obj.sucursal = sucursal
        if moneda is not None:
            banco_obj.moneda = moneda
        if titular is not None:
            banco_obj.titular = titular
        if cuit_titular is not None:
            banco_obj.cuit_titular = cuit_titular
        if saldo_inicial is not None:
            banco_obj.saldo_inicial = saldo_inicial
        if notas is not None:
            banco_obj.notas = notas
        if activo is not None:
            banco_obj.activo = activo
        # empresa_id: only update when explicitly passed (even if None)
        if empresa_id is not _UNSET:
            banco_obj.empresa_id = empresa_id  # type: ignore[assignment]
        self.db.flush()
        return banco_obj

    # ──────────────────────────────────────────────
    # Movimientos
    # ──────────────────────────────────────────────

    def registrar_movimiento(
        self,
        banco_id: int,
        fecha: date,
        detalle: str,
        tipo: str,
        monto: Decimal,
        user_id: Optional[int] = None,
        observaciones: Optional[str] = None,
        origen: str = "manual",
    ) -> BancoMovimiento:
        """
        Registra un movimiento con balance atómico.

        Uses SELECT FOR UPDATE to lock the banco row,
        calculates saldo_posterior, creates BancoMovimiento,
        and updates banco.saldo_actual — all in one transaction.
        Caller owns the commit; this method only flushes.
        """
        # SELECT FOR UPDATE — lock the banco row
        banco = self.db.query(BancoEmpresa).filter(BancoEmpresa.id == banco_id).with_for_update().first()
        if not banco:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Cuenta bancaria {banco_id} no encontrada",
            )

        # Calculate new balance
        saldo_actual = Decimal(str(banco.saldo_actual))
        monto_dec = Decimal(str(monto))
        if tipo == "ingreso":
            saldo_posterior = saldo_actual + monto_dec
        else:
            saldo_posterior = saldo_actual - monto_dec
            if saldo_posterior < Decimal("0"):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(f"Saldo insuficiente. Saldo actual: {saldo_actual}, monto solicitado: {monto_dec}"),
                )

        # Create movement record
        movimiento = BancoMovimiento(
            banco_id=banco_id,
            fecha=fecha,
            detalle=detalle,
            tipo=tipo,
            monto=monto_dec,
            saldo_posterior=saldo_posterior,
            origen=origen,
            registrado_por_id=user_id,
            observaciones=observaciones,
        )
        self.db.add(movimiento)

        # Update running balance
        banco.saldo_actual = saldo_posterior
        self.db.flush()
        return movimiento

    def obtener_movimientos(
        self,
        banco_id: int,
        page: int = 1,
        page_size: int = 50,
        fecha_desde: Optional[date] = None,
        fecha_hasta: Optional[date] = None,
        tipo: Optional[str] = None,
    ) -> tuple[list[BancoMovimiento], int, dict]:
        """
        Returns (items, total_count, summary_dict).

        summary_dict: {total_ingresos, total_egresos, saldo_periodo}
        """
        query = (
            self.db.query(BancoMovimiento)
            .options(joinedload(BancoMovimiento.registrado_por))
            .filter(BancoMovimiento.banco_id == banco_id)
        )
        if fecha_desde:
            query = query.filter(BancoMovimiento.fecha >= fecha_desde)
        if fecha_hasta:
            query = query.filter(BancoMovimiento.fecha <= fecha_hasta)
        if tipo:
            query = query.filter(BancoMovimiento.tipo == tipo)

        total = query.count()

        # Summary
        summary_query = self.db.query(
            BancoMovimiento.tipo,
            sa_func.sum(BancoMovimiento.monto).label("total"),
        ).filter(BancoMovimiento.banco_id == banco_id)
        if fecha_desde:
            summary_query = summary_query.filter(BancoMovimiento.fecha >= fecha_desde)
        if fecha_hasta:
            summary_query = summary_query.filter(BancoMovimiento.fecha <= fecha_hasta)
        if tipo:
            summary_query = summary_query.filter(BancoMovimiento.tipo == tipo)

        summary_rows = summary_query.group_by(BancoMovimiento.tipo).all()
        total_ingresos = Decimal("0")
        total_egresos = Decimal("0")
        for row in summary_rows:
            if row.tipo == "ingreso":
                total_ingresos = Decimal(str(row.total or 0))
            elif row.tipo == "egreso":
                total_egresos = Decimal(str(row.total or 0))

        summary = {
            "total_ingresos": float(total_ingresos),
            "total_egresos": float(total_egresos),
            "saldo_periodo": float(total_ingresos - total_egresos),
        }

        # Paginated items
        offset = (page - 1) * page_size
        items = (
            query.order_by(BancoMovimiento.fecha.desc(), BancoMovimiento.id.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )
        return items, total, summary

    def recalcular_saldo(self, banco_id: int) -> Decimal:
        """Repair utility: recomputes saldo_actual and corrects saldo_posterior snapshots.

        This is the ONE sanctioned exception to the append-only invariant — it
        mutates saldo_posterior on existing rows to correct drift caused by manual
        DB fixes or data-import errors. It MUST NOT be called in the normal
        payment flow; it is a controlled reconciliation tool only.
        """
        banco = self.obtener_banco(banco_id)
        saldo = Decimal(str(banco.saldo_inicial))

        movimientos = (
            self.db.query(BancoMovimiento)
            .filter(BancoMovimiento.banco_id == banco_id)
            .order_by(BancoMovimiento.fecha.asc(), BancoMovimiento.id.asc())
            .all()
        )
        for mov in movimientos:
            monto = Decimal(str(mov.monto))
            if mov.tipo == "ingreso":
                saldo += monto
            else:
                saldo -= monto
            mov.saldo_posterior = saldo

        banco.saldo_actual = saldo
        self.db.flush()
        return saldo
