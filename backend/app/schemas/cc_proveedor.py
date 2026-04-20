"""
Schemas Pydantic v2 para Cuenta Corriente de Proveedor (design §1.5, §9.4).

Expone:
  - Movimientos del libro mayor propio (cc_proveedor_movimientos).
  - Saldo agregado por moneda (calculado server-side).
  - Agrupación por pedido de compra (útil para drill-down UI).
  - Log de reconciliación diario (cc_reconciliacion_log).
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CCMovimientoResponse(BaseModel):
    """Movimiento individual del libro mayor de CC proveedor."""

    id: int
    proveedor_id: int
    empresa_id: int
    fecha_movimiento: date
    tipo: str = Field(..., pattern="^(debe|haber|ajuste)$")
    signo_ajuste: int | None = None
    monto: Decimal
    moneda: str = Field(..., pattern="^(ARS|USD)$")
    tipo_cambio_a_ars: Decimal | None = None
    origen_tipo: str = Field(..., max_length=32)
    origen_id: int | None = None
    descripcion: str | None = None
    creado_por_id: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SaldoPorMoneda(BaseModel):
    """Saldo agregado de un proveedor en una moneda concreta."""

    moneda: str = Field(..., pattern="^(ARS|USD)$")
    saldo: Decimal
    movimientos_count: int = Field(..., ge=0)


class CCProveedorDetalle(BaseModel):
    """Vista completa de la CC de un proveedor (endpoint /cc-proveedor/{id})."""

    proveedor_id: int
    nombre_proveedor: str
    saldos: list[SaldoPorMoneda]
    movimientos: list[CCMovimientoResponse]


class CCAgrupadoPorPedido(BaseModel):
    """CC agrupada por pedido de compra (drill-down para UI).

    Incluye metadata del pedido y los movimientos asociados — el
    frontend los agrupa en accordions por pedido.
    """

    pedido_compra_id: int
    pedido_numero: str
    pedido_estado: str
    pedido_monto: Decimal
    pedido_moneda: str = Field(..., pattern="^(ARS|USD)$")
    movimientos: list[CCMovimientoResponse]


class CCReconciliacionLogResponse(BaseModel):
    """Fila del log diario de reconciliación CC."""

    id: int
    fecha_corrida: date
    proveedor_id: int
    moneda: str = Field(..., pattern="^(ARS|USD)$")
    saldo_libro_mayor: Decimal
    saldo_snapshot: Decimal
    diferencia: Decimal
    tolerancia_aplicada: Decimal
    estado: str = Field(..., pattern="^(ok|divergencia)$")
    nota: str | None = None
    alerta_id: int | None = None
    notificacion_id: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
