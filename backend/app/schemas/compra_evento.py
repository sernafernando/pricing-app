"""
Schemas Pydantic v2 para CompraEvento (tabla polimórfica append-only).

Modela el log de auditoría de pedidos de compra y órdenes de pago
(design §1.4, D2). El payload es un JSON arbitrario: se expone tal
cual al frontend como `dict` sin validación estricta (cada evento tiene
su propia shape documentada en §6).
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


ENTIDADES_VALIDAS: tuple[str, ...] = ("pedido_compra", "orden_pago", "nota_credito_local")


class CompraEventoResponse(BaseModel):
    """Evento de auditoría serializado (solo lectura, append-only)."""

    id: int
    entidad_tipo: str = Field(..., pattern="^(pedido_compra|orden_pago|nota_credito_local)$")
    entidad_id: int
    tipo: str
    usuario_id: int
    payload: dict[str, Any] | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
