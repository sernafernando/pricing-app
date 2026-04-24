"""
Schemas Pydantic v2 para Imputacion (append-only, D9).

Modela relaciones monetarias polimórficas origen→destino. La whitelist
de combos válidos v1 vive en el servicio (`imputaciones_service.
COMBOS_VALIDOS_V1`), no en el schema. Cross-moneda prohibido (D3).

Desimputación y reimputación NO modifican filas existentes: insertan
nuevas con `es_reversal=True` y `reimputada_desde_id` apuntando a la
original (D9).
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ImputacionBase(BaseModel):
    """Campos comunes de una imputación polimórfica."""

    origen_tipo: str = Field(..., max_length=32)
    origen_id: int
    destino_tipo: str = Field(..., max_length=32)
    destino_id: int | None = None
    monto_imputado: Decimal = Field(..., gt=0)
    moneda_imputada: str = Field(..., pattern="^(ARS|USD)$", max_length=3)
    tipo_cambio: Decimal | None = Field(None, gt=0)
    proveedor_id: int


class ImputacionResponse(ImputacionBase):
    """Imputación serializada (incluye metadata de reversal y nombres derivados)."""

    id: int
    es_reversal: bool
    reimputada_desde_id: int | None = None
    creado_por_id: int
    created_at: datetime

    # Nombres derivados (enriquecidos por el router vía batch queries) — el
    # frontend los consume directamente sin hacer fetches adicionales.
    empresa_nombre: str | None = None
    proveedor_nombre: str | None = None

    # Descripciones legibles del origen y destino para el listado:
    #   origen_descripcion: "OP P-01-2026-00042" / "NC NC-01-2026-00007" /
    #                        "NC ERP 768710"
    #   destino_descripcion: "Pedido P-01-2026-00001" / "Factura 00390198" /
    #                         "Saldo a cuenta"
    origen_descripcion: str | None = None
    destino_descripcion: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ImputacionDesimputar(BaseModel):
    """Body del POST /imputaciones/{id}/desimputar."""

    motivo: str = Field(..., min_length=3, max_length=500)


class ImputacionReimputar(BaseModel):
    """Body del POST /imputaciones/{id}/reimputar.

    `destino_id` es opcional: obligatorio para destinos != 'saldo'
    (pedido_compra, factura_erp). El servicio valida la combinación.
    """

    destino_tipo: str = Field(..., max_length=32)
    destino_id: int | None = None
    motivo: str = Field(..., min_length=3, max_length=500)


class ImputacionPaginated(BaseModel):
    """Respuesta paginada de listado de imputaciones."""

    items: list[ImputacionResponse]
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=200)
