"""
Schemas Pydantic v2 para NotaCreditoLocal (compras v2).

Modela los contratos de entrada/salida del flujo de NCs locales (spec T.7).
Patrón análogo a `pedido_compra` schemas. Todos los responses incluyen
`saldo_pendiente` calculable derivado de imputaciones.

Convenciones v2: `model_config = ConfigDict(from_attributes=True)`,
sintaxis `X | None`, `Decimal` para montos, `date` para fechas de negocio.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


ESTADOS_NC_LOCAL: tuple[str, ...] = (
    "borrador",
    "pendiente_aprobacion",
    "aprobado",
    "rechazado",
    "cancelado",
    "aplicada_parcial",
    "aplicada",
)


class NotaCreditoLocalBase(BaseModel):
    """Campos comunes de NC local (input + output)."""

    empresa_id: int
    proveedor_id: int
    moneda: str = Field(..., pattern="^(ARS|USD)$", max_length=3)
    monto: Decimal = Field(..., gt=0)
    # Cotización ARS/USD al momento de cargar la NC. Solo aplica a 'USD'.
    # Si es None y moneda='USD', el servicio intenta autollenar con TC del día.
    tipo_cambio: Decimal | None = Field(None, gt=0)
    fecha_emision: date
    numero_nc_proveedor: str | None = Field(None, max_length=50)
    motivo: str = Field(..., min_length=1)
    observaciones: str | None = None


class NotaCreditoLocalCreate(NotaCreditoLocalBase):
    """Body de POST /ncs-locales. `numero` lo genera el backend."""

    pass


class NotaCreditoLocalUpdate(BaseModel):
    """Body de PUT /ncs-locales/{id}. Todos opcionales. NO incluye 'estado'
    (las transiciones van por endpoints dedicados)."""

    moneda: str | None = Field(None, pattern="^(ARS|USD)$", max_length=3)
    monto: Decimal | None = Field(None, gt=0)
    tipo_cambio: Decimal | None = Field(None, gt=0)
    fecha_emision: date | None = None
    numero_nc_proveedor: str | None = Field(None, max_length=50)
    motivo: str | None = Field(None, min_length=1)
    observaciones: str | None = None


class NotaCreditoLocalResponse(NotaCreditoLocalBase):
    """Representación plana de la NC local (listados)."""

    id: int
    numero: str
    ct_transaction_id: int | None = None
    estado: str
    creado_por_id: int
    aprobado_por_id: int | None = None
    created_at: datetime
    updated_at: datetime

    # Derivados (los popula el router con joinedload).
    empresa_nombre: str | None = None
    proveedor_nombre: str | None = None

    # Saldo pendiente = monto - SUM(imputaciones no-reversal de esta NC)
    # + SUM(imputaciones reversal). Lo completa el router cuando el endpoint
    # lo necesita (detalle, listado de aplicables). En listados livianos
    # queda None para evitar N+1.
    saldo_pendiente: Decimal | None = None

    model_config = ConfigDict(from_attributes=True)


class NotaCreditoLocalDetalle(NotaCreditoLocalResponse):
    """NC con eventos + imputaciones (endpoint GET /ncs-locales/{id})."""

    eventos: list["CompraEventoResponse"] = Field(default_factory=list)
    imputaciones: list["ImputacionResponse"] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class NotaCreditoLocalPaginated(BaseModel):
    """Respuesta paginada de listado de NCs locales."""

    items: list[NotaCreditoLocalResponse]
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=200)


class VincularFacturaNCRequest(BaseModel):
    """Body de POST /ncs-locales/{id}/vincular-factura.

    Si `ajustar_monto=True`:
      - Requiere permiso `administracion.ajustar_monto_pedido` (validado en router).
      - Requiere `nuevo_monto` > 0 y `motivo_ajuste` no vacío.
    """

    ct_transaction: int = Field(..., gt=0)
    ajustar_monto: bool = False
    nuevo_monto: Decimal | None = Field(None, gt=0)
    motivo_ajuste: str | None = Field(None, max_length=500)


class NCErpCandidataResponse(BaseModel):
    """NC del ERP candidata a vincular a una NC local."""

    ct_transaction: int
    ct_docnumber: str
    ct_date: datetime | None = None
    ct_total: Decimal
    curr_id_transaction: int | None = None

    model_config = ConfigDict(from_attributes=True)


class TransicionNCRequest(BaseModel):
    """Body genérico de transiciones que requieren motivo (rechazar, cancelar)."""

    accion: str | None = None  # solo para /rechazar
    motivo: str | None = None


# Forward refs — importar al final para evitar ciclos
from app.schemas.compra_evento import CompraEventoResponse  # noqa: E402
from app.schemas.imputacion import ImputacionResponse  # noqa: E402

NotaCreditoLocalDetalle.model_rebuild()
