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
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CCMovimientoResponse(BaseModel):
    """Movimiento individual del libro mayor de CC proveedor.

    `origen_descripcion` es un nombre legible derivado (batch-enriquecido por
    el router) para que la UI cronológica no muestre `origen_tipo #id` crudo.
    Mapping:
      - orden_pago          → "OP {numero}"
      - nota_credito_local  → "NC {numero}"
      - ajuste_pedido       → "Ajuste pedido {numero}"
      - ajuste_manual       → "Ajuste manual"
      - nota_credito_erp    → "NC ERP {ct_docnumber}"
      - pedido_compra       → "Pedido {numero}"
    Fallback (origen huérfano o tipo desconocido): `"{origen_tipo} #{id}"`.
    """

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

    # Nombre derivado (batch-enriquecido por el router) — ver docstring.
    origen_descripcion: str | None = None

    # F6 — ARS projection fields (§2.6, §7.2, AD-11).
    # Computed on read by cc_proveedor_service; NOT stored in DB.
    # ARS movements: monto_ars = monto, tc_aplicado = None.
    # USD movements tied to a pedido: monto_ars = monto * tc_efectivo_pedido.
    monto_ars: Decimal | None = None
    tc_aplicado: Decimal | None = None
    # varianza_tc_ars — display-only (design §4.1, REQ-MM-007).
    # = (tc_op - tc_pedido_snapshot) * usd_imputado for settled USD movements.
    # None for ARS movements, DEBE movements, or when TC data is missing.
    varianza_tc_ars: Decimal | None = None

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
    # F6 — cumulative ARS saldo across all movements (§7.3).
    # Sum of monto_ars with CC sign convention (debe positive, haber negative).
    saldo_ars: Decimal | None = None


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
    pedido_tipo_cambio: Optional[Decimal] = None
    # Saldo pendiente en la moneda del pedido (= monto - imputaciones efectivas).
    # Si pedido es USD, este es el saldo USD; el frontend multiplica por
    # pedido_tipo_cambio para mostrar el equivalente ARS.
    pedido_saldo_pendiente: Optional[Decimal] = None
    # TC ponderado por aporte de imputaciones cross-moneda al pedido (FR-008).
    # 4 decimales. None si el pedido no tiene imps cross-moneda.
    tc_ponderado: Optional[Decimal] = None
    # Diferencial de tipo de cambio neto en ARS (REQ-FX-CC-001).
    # Positivo → el proveedor cobró de más (ND pendiente); negativo → el proveedor
    # cobró de menos (NC pendiente). Cero para pedidos ARS o sin Caso-B.
    varianza_tc_neta: Decimal = Decimal("0")
    # True cuando abs(varianza_tc_neta) > VARIANZA_TC_THRESHOLD_ARS (1 ARS).
    # Señal para el frontend de mostrar badge "Falta aplicar NC/ND".
    varianza_tc_pendiente: bool = False
    movimientos: list[CCMovimientoResponse]


class AjusteCCManualRequest(BaseModel):
    """Body del POST /cc-proveedor/{id}/ajuste-manual (sub-batch 5.H).

    Requiere permiso crítico `administracion.ajustar_cc_proveedor_manual`.
    Genera un movimiento append-only `tipo='ajuste'` con
    `origen_tipo='ajuste_manual'`. NO modifica movimientos previos.

    `signo_ajuste=+1` (debe) suma deuda; `-1` (haber) resta deuda.
    """

    empresa_id: int = Field(..., gt=0)
    fecha_movimiento: date
    signo_ajuste: int = Field(..., description="+1 = debe (aumenta deuda), -1 = haber")
    monto: Decimal = Field(..., gt=0)
    moneda: str = Field(..., pattern="^(ARS|USD)$", max_length=3)
    motivo: str = Field(..., min_length=3, max_length=500)


class PagoRapidoRequest(BaseModel):
    """Body del POST /cc-proveedor/{proveedor_id}/pago-rapido (sub-batch 5.G).

    Crea una OP modo `a_cuenta` + ejecuta el pago en un solo request.
    Deja trazabilidad completa: número OP, evento, caja_movimiento,
    caja_documento, imputación a saldo del proveedor.

    El resultado es equivalente a hacer crear+ejecutar_pago por separado
    pero con un solo click desde el tab CC Proveedores.
    """

    empresa_id: int = Field(..., gt=0)
    caja_id: int = Field(..., gt=0)
    moneda: str = Field(..., pattern="^(ARS|USD)$", max_length=3)
    monto: Decimal = Field(..., gt=0)
    fecha_pago_real: date
    tipo_cambio: Decimal | None = Field(None, gt=0)
    observaciones: str | None = Field(None, max_length=500)


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

    # Nombre derivado (batch-enriquecido por el router) para que la UI no
    # tenga que adivinar el proveedor a partir del ID.
    proveedor_nombre: str | None = None

    model_config = ConfigDict(from_attributes=True)
