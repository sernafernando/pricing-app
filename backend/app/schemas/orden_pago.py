"""
Schemas Pydantic v2 para OrdenPago (design §1.3, §9.2).

Incluye contratos de:
  - Creación con items (imputaciones) + flag anti-doble-contabilización.
  - Ejecución del pago (integración Caja).
  - Detección de duplicado ERP — payload del HTTP 409 POSIBLE_DUPLICADO_OP_ERP.

`ct_transaction` del ERP es BIGINT (verificado en modelo real).
Moneda OP debe coincidir con la caja al pagar (D7, HTTP 422 si no).
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


MODOS_IMPUTACION: tuple[str, ...] = ("especifica", "a_cuenta", "mixta")
ESTADOS_OP: tuple[str, ...] = ("pendiente", "pagado", "anulado", "cancelado")


class ImputacionItem(BaseModel):
    """Item dentro del body de creación de OP.

    `tipo` ∈ {'pedido_compra','factura_erp','saldo'}. `id` obligatorio
    salvo cuando `tipo == 'saldo'`. `numero_factura` es informativo para
    matching posterior cuando el pedido no tiene `ct_transaction_id` aún.
    """

    tipo: str = Field(..., max_length=32)
    id: int | None = None
    monto: Decimal = Field(..., gt=0)
    numero_factura: str | None = Field(None, max_length=50)


class OrdenPagoBase(BaseModel):
    """Campos comunes de la orden de pago."""

    empresa_id: int
    proveedor_id: int
    moneda: str = Field(..., pattern="^(ARS|USD)$", max_length=3)
    monto_total: Decimal = Field(..., gt=0)
    tipo_cambio: Decimal | None = Field(None, gt=0)
    modo_imputacion: str = Field(..., pattern="^(especifica|a_cuenta|mixta)$")
    fecha_pago_estimada: date | None = None
    observaciones: str | None = None


class OrdenPagoCreate(OrdenPagoBase):
    """Body del POST /ordenes-pago.

    `items` describe las imputaciones a crear junto con la OP.
    `confirmar_duplicado=True` suprime el HTTP 409 cuando el usuario
    decide grabar la OP aun existiendo un posible duplicado en el ERP
    (registra evento de auditoría). Ver design §11.

    `actualizar_tc_pedido` (F1): cuando True (Caso A) el TC de esta OP
    participa en el promedio ponderado del TC efectivo del pedido destino.
    False (Caso B, default): el pago se registra normalmente sin modificar
    el TC efectivo. Inmutable después de que la OP pasa a 'pagado'.
    """

    items: list[ImputacionItem] = Field(default_factory=list)
    confirmar_duplicado: bool = False
    actualizar_tc_pedido: bool = False


class OrdenPagoEjecutarPago(BaseModel):
    """Body del POST /ordenes-pago/{id}/pagar.

    `tipo_cambio_override` permite sobrescribir el TC de la OP al momento
    del pago (sub-batch 2.2). Si viene, reemplaza `op.tipo_cambio` antes de
    registrar el egreso en caja ARS cross-moneda (design §3.2 extendido).
    """

    caja_id: int
    fecha_pago_real: date
    tipo_cambio_override: Decimal | None = Field(None, gt=0)


class OrdenPagoCrearYPagar(OrdenPagoCreate, OrdenPagoEjecutarPago):
    """Body del POST /ordenes-pago/crear-y-pagar (F3).

    Hereda todos los campos de creación (OrdenPagoCreate) y los del pago
    (OrdenPagoEjecutarPago) para ejecutar ambas operaciones en una sola
    transacción atómica. Si el paso de pago falla, la creación también
    se revierte (rollback completo).

    Permisos requeridos (ambos):
      - `administracion.gestionar_ordenes_compra` (crear OP).
      - `administracion.ejecutar_pagos` (ejecutar pago).
    """


class OrdenPagoEditar(BaseModel):
    """Body del PUT /ordenes-pago/{id} (sub-batch 1.1).

    Todos los campos son opcionales: sólo se actualizan los que vengan
    explícitos. Si `items` se envía, revalida contra whitelist + modo y
    registra evento `items_editados` (append-only). La OP debe estar en
    estado `pendiente` o el endpoint retorna 409.
    """

    monto_total: Decimal | None = Field(None, gt=0)
    moneda: str | None = Field(None, pattern="^(ARS|USD)$", max_length=3)
    modo_imputacion: str | None = Field(None, pattern="^(especifica|a_cuenta|mixta)$")
    items: list[ImputacionItem] | None = None
    observaciones: str | None = None
    tipo_cambio: Decimal | None = Field(None, gt=0)
    fecha_pago_estimada: date | None = None


class OrdenPagoCancelarPendiente(BaseModel):
    """Body del POST /ordenes-pago/{id}/cancelar-pendiente (sub-batch 1.2)."""

    motivo: str = Field(..., min_length=1, max_length=500)


class OrdenPagoResponse(OrdenPagoBase):
    """Representación plana de la orden de pago."""

    id: int
    numero: str
    estado: str
    # F1 — incluido en la respuesta para que el frontend pueda mostrar el
    # badge "Caso A / Caso B" en el detalle de la OP.
    actualizar_tc_pedido: bool = False
    caja_id: int | None = None
    caja_movimiento_id: int | None = None
    caja_documento_id: int | None = None
    fecha_pago_real: date | None = None
    creado_por_id: int
    pagado_por_id: int | None = None
    created_at: datetime
    updated_at: datetime
    paid_at: datetime | None = None

    # Nombres derivados (populados por el router vía joinedload + update).
    empresa_nombre: str | None = None
    proveedor_nombre: str | None = None

    # Flag de hard-delete calculado en batch por el router (opción C).
    # True si la OP está en estado 'anulado' (nunca pendiente/pagado), sin
    # imputaciones activas y el updated_at superó la ventana de retención.
    puede_eliminar: bool = False

    model_config = ConfigDict(from_attributes=True)


class CajaMovimientoResumen(BaseModel):
    """Resumen del movimiento de caja vinculado a una OP pagada.

    Se expone solo cuando la OP está en estado `pagado` y tiene un
    `caja_movimiento_id` asociado. Le da a tesorería un vistazo rápido
    sin hacer un segundo request a `/administracion-caja/`.
    """

    id: int
    caja_id: int
    caja_nombre: str | None = None
    fecha: date
    monto: Decimal
    tipo: str

    model_config = ConfigDict(from_attributes=True)


class OrdenPagoDetalle(OrdenPagoResponse):
    """OP con imputaciones, eventos y resumen de pago (GET /ordenes-pago/{id})."""

    imputaciones: list["ImputacionResponse"] = Field(default_factory=list)
    eventos: list["CompraEventoResponse"] = Field(default_factory=list)
    caja_movimiento_resumen: CajaMovimientoResumen | None = None

    model_config = ConfigDict(from_attributes=True)


class OrdenPagoPaginated(BaseModel):
    """Respuesta paginada de listado de OPs."""

    items: list[OrdenPagoResponse]
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=200)


class DuplicadoOPERPInfo(BaseModel):
    """Info de una OP ya cargada en el ERP que coincide con la que se intenta crear."""

    ct_transaction: int = Field(..., description="PK BIGINT de tb_commercial_transactions")
    ct_date: datetime
    ct_docnumber: str | None = Field(None, max_length=50)
    ct_total: Decimal


class PosibleDuplicadoResponse(BaseModel):
    """Envelope del HTTP 409 POSIBLE_DUPLICADO_OP_ERP (design §11).

    El frontend muestra un ModalTesla con la lista y 2 acciones:
    "Cancelar" o "Confirmar igual" (que reenvía POST con
    `confirmar_duplicado=true`).
    """

    codigo: str = Field(default="POSIBLE_DUPLICADO_OP_ERP")
    mensaje: str
    duplicados: list[DuplicadoOPERPInfo]
    flag_confirmacion: str = Field(default="confirmar_duplicado")


# Forward refs
from app.schemas.compra_evento import CompraEventoResponse  # noqa: E402
from app.schemas.imputacion import ImputacionResponse  # noqa: E402

OrdenPagoDetalle.model_rebuild()
