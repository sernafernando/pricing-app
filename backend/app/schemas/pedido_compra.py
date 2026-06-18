"""
Schemas Pydantic v2 para PedidoCompra.

Modela los contratos de entrada/salida del flujo de aprobación de
compras (design §9.1). Campos derivados del modelo SQLAlchemy
`app.models.pedido_compra.PedidoCompra`.

Convenciones v2: `model_config = ConfigDict(from_attributes=True)` en
los Response; sintaxis moderna `X | None` para opcionales; `Decimal`
para montos; `date` para fechas de negocio; `datetime` para auditoría.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ESTADOS_PEDIDO: tuple[str, ...] = (
    "borrador",
    "pendiente_aprobacion",
    "aprobado",
    "rechazado",
    "cancelado",
    "pagado_parcial",
    "pagado",
    "recibido",
    "con_faltantes",
)


class PedidoCompraBase(BaseModel):
    """Campos comunes del pedido de compra (input y output)."""

    empresa_id: int
    proveedor_id: int
    moneda: str = Field(..., pattern="^(ARS|USD)$", max_length=3)
    monto: Decimal = Field(..., gt=0)
    # Cotización ARS por 1 USD al momento del pedido. Solo aplica a moneda='USD'.
    # Si moneda='USD' y viene None, el servicio intenta autollenar con el TC del día
    # (deja None si no hay TC cargado, logueando WARNING). Si moneda='ARS' y viene
    # un valor, el servicio lo rechaza con HTTP 400.
    tipo_cambio: Decimal | None = Field(None, gt=0)
    fecha_pago_texto: str | None = Field(None, max_length=200)
    fecha_pago_estimada: date | None = None
    requiere_envio: bool = False
    numero_factura: str | None = Field(None, max_length=50)
    # Notas libres del pedido. Editable en borrador y como metadata en
    # aprobado/pagado_parcial/pagado (feature B — no impacta CC).
    observaciones: str | None = None


class PedidoCompraCreate(PedidoCompraBase):
    """Body de POST /pedidos. `numero` lo genera el backend vía numeracion_service."""

    pass


class PedidoCompraUpdate(BaseModel):
    """Body de PUT /pedidos/{id}. Todos los campos opcionales."""

    empresa_id: int | None = None
    proveedor_id: int | None = None
    moneda: str | None = Field(None, pattern="^(ARS|USD)$", max_length=3)
    monto: Decimal | None = Field(None, gt=0)
    tipo_cambio: Decimal | None = Field(None, gt=0)
    fecha_pago_texto: str | None = Field(None, max_length=200)
    fecha_pago_estimada: date | None = None
    requiere_envio: bool | None = None
    numero_factura: str | None = Field(None, max_length=50)
    observaciones: str | None = None
    estado: str | None = None


class PedidoCompraResponse(PedidoCompraBase):
    """Representación plana del pedido de compra (listados)."""

    id: int
    numero: str
    ct_transaction_id: int | None = None
    # Batch J — OC link columns (nullable when not linked)
    oc_comp_id: int | None = None
    oc_bra_id: int | None = None
    oc_poh_id: int | None = None
    estado: str
    creado_por_id: int
    aprobado_por_id: int | None = None
    created_at: datetime
    updated_at: datetime

    # F1 — TC Re-valuation fields.
    # `tipo_cambio_original`: snapshot inmutable del TC al aprobar el pedido.
    #   None para pedidos ARS (sin TC) o pedidos anteriores a F1 sin backfill.
    tipo_cambio_original: Decimal | None = None

    # Feature D — círculo cerrado de correcciones. Solo populados cuando el
    # pedido forma parte de un par original↔clon (caso contrario: None).
    corregido_desde_id: int | None = None
    corregido_a_id: int | None = None

    # Nombres derivados de las relaciones `empresa` / `proveedor`. Los populan
    # los routers vía `model_validate(p, update={...})` usando los datos de
    # `joinedload`. Si la relación no se cargó, quedan `None` y el frontend
    # muestra fallback "Proveedor #N".
    empresa_nombre: str | None = None
    proveedor_nombre: str | None = None

    # Saldo pendiente = monto - imputaciones efectivas (no-reversal - reversal).
    # Solo lo completa el endpoint `/pedidos/pendientes-pago` (design Batch C);
    # en los listados genéricos queda None para evitar N+1.
    saldo_pendiente: Decimal | None = None

    # TC ponderado por aporte de imputaciones cross-moneda al pedido (FR-005,
    # FR-008). Cuantizado a 4 decimales. None si el pedido no tiene imps
    # cross-moneda (todas same-moneda, sin TC, o sin imps). Calculado server-
    # side vía `pedidos_service.calcular_tc_ponderado_pedido(_batch)`.
    tipo_cambio_ponderado: Decimal | None = None

    # Flag de hard-delete calculado en batch por el router (opción C).
    # True si el pedido está en borrador/cancelado, NO fue aprobado nunca,
    # NO tiene imputaciones y — si está cancelado — el updated_at superó
    # la ventana de retención (configuracion `compras.dias_retencion_cancelados`).
    puede_eliminar: bool = False

    # F2 — ND/NC variance circuit (AD-8: derived, never stored).
    # `varianza_tc_neta`: ARS pendiente de compensación por diferencia TC entre
    #   Caso-B pagos y el TC efectivo del pedido. Positivo → falta ND (debito);
    #   negativo → falta NC (credito). Cero cuando está completamente compensado.
    # `varianza_tc_pendiente`: True cuando abs(varianza_tc_neta) > umbral ARS 1.00.
    varianza_tc_pendiente: bool = False
    varianza_tc_neta: Decimal = Decimal("0")

    # F5 — Manual TC override fields.
    # `tipo_cambio_manual`: the override value (AD-3). None = no override active.
    # `tipo_cambio_es_manual`: derived flag — True when tipo_cambio_manual is not None.
    tipo_cambio_manual: Decimal | None = None
    tipo_cambio_es_manual: bool = False

    @model_validator(mode="after")
    def _compute_tipo_cambio_es_manual(self) -> "PedidoCompraResponse":
        self.tipo_cambio_es_manual = self.tipo_cambio_manual is not None
        return self

    model_config = ConfigDict(from_attributes=True)


class PedidoCompraDetalle(PedidoCompraResponse):
    """Pedido con sus eventos y imputaciones (endpoint GET /pedidos/{id})."""

    eventos: list["CompraEventoResponse"] = Field(default_factory=list)
    imputaciones: list["ImputacionResponse"] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PedidoCompraPaginated(BaseModel):
    """Respuesta paginada de listado de pedidos."""

    items: list[PedidoCompraResponse]
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=200)


# ==========================================================================
# Batch I — Vinculación manual + ajuste controlado factura ERP
# ==========================================================================


class FacturaCandidataResponse(BaseModel):
    """Factura del ERP candidata a ser vinculada a un pedido (derivada de v_facturas_compra_vigentes)."""

    ct_transaction: int
    ct_docnumber: str
    ct_date: datetime | None = None
    ct_total: Decimal
    curr_id_transaction: int | None = None

    model_config = ConfigDict(from_attributes=True)


class DocumentoERPImputado(BaseModel):
    """Documento ERP imputado a un pedido (sub-batch 3.1).

    Representa una fila en la tabla "Documentos imputados" del detalle
    del pedido. La fuente es la tabla de imputaciones, enriquecida con
    datos del documento origen (factura ERP, NC local, etc.).
    """

    origen_tipo: str
    origen_id: int
    numero: str | None = None
    fecha: datetime | None = None
    monto_imputado: Decimal
    moneda_imputada: str
    estado: str | None = None
    descripcion: str | None = None


class VincularFacturaRequest(BaseModel):
    """Body de POST /pedidos/{id}/vincular-factura.

    Si `ajustar_monto=False`, el pedido queda vinculado pero `monto` NO cambia.
    Si `ajustar_monto=True`, se ajusta el monto a `nuevo_monto` y se registra un
    movimiento de ajuste en CC. Requiere permiso `administracion.ajustar_monto_pedido`
    y `motivo_ajuste` no vacío. Esta validación cruzada la fuerza el router/service.
    """

    ct_transaction: int = Field(..., gt=0)
    ajustar_monto: bool = False
    nuevo_monto: Decimal | None = Field(None, gt=0)
    motivo_ajuste: str | None = Field(None, max_length=500)

    @field_validator("motivo_ajuste")
    @classmethod
    def _limpiar_motivo(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip() or None


# ==========================================================================
# Feature D — Corregir pedido (clonación append-only bidireccional)
# ==========================================================================


class CorreccionPedidoRequest(BaseModel):
    """Body de POST /pedidos/{id}/corregir.

    Todos los campos editables son opcionales — se envían solo los que cambian.
    Moneda NO se incluye: es inmutable al corregir (design decision D.3). Para
    cambiar moneda hay que cancelar el pedido y crear uno nuevo.

    `motivo_correccion` es OBLIGATORIO (trazabilidad) y se persiste en el
    payload del evento `creado_por_correccion_de` (clon) y
    `cancelado_por_correccion` (original).

    Reglas del clon según qué cambió:
      * Solo cosméticos (numero_factura, fecha_pago_*, requiere_envio,
        observaciones) → clon hereda estado `aprobado`.
      * Cambia monto → clon nace en `pendiente_aprobacion` (requiere re-aprobar).
        Las imputaciones se "congelan" en el original y se re-aplican al clon
        cuando se aprueba (opción Z del design).
        Nota F5: tipo_cambio ya NO es un campo corregible — usar PUT /pedidos/{id}/tipo-cambio.
    """

    numero_factura: str | None = Field(None, max_length=50)
    # tipo_cambio is intentionally absent — F5 requires TC corrections to go through
    # PUT /pedidos/{id}/tipo-cambio (in-place, append-only CC audit trail).
    monto: Decimal | None = Field(None, gt=0)
    fecha_pago_texto: str | None = Field(None, max_length=200)
    fecha_pago_estimada: date | None = None
    requiere_envio: bool | None = None
    observaciones: str | None = None
    motivo_correccion: str = Field(..., min_length=5, max_length=500)

    @field_validator("motivo_correccion")
    @classmethod
    def _limpiar_motivo_correccion(cls, v: str) -> str:
        s = (v or "").strip()
        if len(s) < 5:
            raise ValueError("motivo_correccion debe tener al menos 5 caracteres significativos.")
        return s


class PedidoTipoCambioUpdate(BaseModel):
    """Body de PUT /pedidos/{id}/tipo-cambio (F5 — manual TC override).

    `tipo_cambio`: the new authoritative TC value, or null to CLEAR the override
    and revert to weighted Caso-A / tipo_cambio_original mode.
    `motivo`: required for audit trail (logged in the CC adjustment). Stripped
    of leading/trailing whitespace; must be non-empty after stripping.
    """

    tipo_cambio: Decimal | None = Field(None, gt=0)
    motivo: str = Field(..., min_length=1, max_length=500)

    @field_validator("motivo")
    @classmethod
    def _strip_motivo(cls, v: str) -> str:
        s = (v or "").strip()
        if len(s) < 1:
            raise ValueError("motivo no puede estar vacío.")
        return s

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "tipo_cambio": 1430.0,
                "motivo": "Ajuste manual por acuerdo comercial",
            }
        }
    )


# Forward refs — importar acá al final para evitar ciclos
from app.schemas.compra_evento import CompraEventoResponse  # noqa: E402
from app.schemas.imputacion import ImputacionResponse  # noqa: E402

PedidoCompraDetalle.model_rebuild()
