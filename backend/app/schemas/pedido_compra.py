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

from pydantic import BaseModel, ConfigDict, Field


ESTADOS_PEDIDO: tuple[str, ...] = (
    "borrador",
    "pendiente_aprobacion",
    "aprobado",
    "rechazado",
    "cancelado",
    "pagado_parcial",
    "pagado",
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
    estado: str | None = None


class PedidoCompraResponse(PedidoCompraBase):
    """Representación plana del pedido de compra (listados)."""

    id: int
    numero: str
    ct_transaction_id: int | None = None
    estado: str
    creado_por_id: int
    aprobado_por_id: int | None = None
    created_at: datetime
    updated_at: datetime

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


# Forward refs — importar acá al final para evitar ciclos
from app.schemas.compra_evento import CompraEventoResponse  # noqa: E402
from app.schemas.imputacion import ImputacionResponse  # noqa: E402

PedidoCompraDetalle.model_rebuild()
