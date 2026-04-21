"""
Schemas Pydantic v2 para la papelera auditable del módulo compras.

Contratos de respuesta:
  - `PapeleraItemResponse`: fila para listado (sin snapshot grande).
  - `PapeleraItemDetalle`: fila completa con snapshot JSON + eventos copiados.

Input: el hard-delete recibe su payload a través de un dict en el router
(`motivo`, `challenge_palabra_usada`) — no hay un schema Create porque
esta tabla NUNCA se crea directo: se crea como side-effect del borrado.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class PapeleraItemResponse(BaseModel):
    """Fila de la papelera para listados (sin payload pesado)."""

    id: int
    entidad_tipo: str
    entidad_id_original: int
    numero: str | None = None
    empresa_id: int | None = None
    proveedor_id: int | None = None
    eliminado_por_id: int
    motivo: str
    challenge_palabra: str | None = None
    estado_original: str | None = None
    created_at: datetime

    # Nombres derivados, populados por el router vía `model_copy(update=...)`.
    empresa_nombre: str | None = None
    proveedor_nombre: str | None = None
    eliminado_por_nombre: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PapeleraItemDetalle(PapeleraItemResponse):
    """Fila de papelera con snapshot JSONB completo para drill-down."""

    snapshot: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class PapeleraPaginated(BaseModel):
    """Respuesta paginada de listado de papelera."""

    items: list[PapeleraItemResponse]
    total: int
    page: int
    page_size: int


class PapeleraHardDeleteRequest(BaseModel):
    """Body del DELETE /pedidos/{id} y DELETE /ordenes-pago/{id}.

    El `challenge_palabra_usada` es informativo: el backend lo guarda en
    la fila de papelera para auditoría pero NO lo valida (el challenge
    word se genera y valida en el frontend — no existe palabra "correcta"
    server-side). Obligatoriedad del motivo se valida en el service.
    """

    motivo: str
    challenge_palabra_usada: str | None = None
