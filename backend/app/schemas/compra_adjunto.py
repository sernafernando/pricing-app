"""
Schemas Pydantic v2 para CompraAdjunto (Batch H — design §9.1/§9.2 extended).

Contratos de respuesta para los endpoints de adjuntos polimórficos. NO se
expone `path_archivo` al cliente (security — es un path de server-side).
El cliente descarga via `GET /adjuntos/{id}/descargar` que resuelve el
archivo internamente.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CompraAdjuntoResponse(BaseModel):
    """Representación de un adjunto de compra (pedido u OP) para el cliente."""

    id: int
    entidad_tipo: str
    entidad_id: int
    nombre_archivo: str
    mime_type: str | None = None
    tamano_bytes: int | None = None
    tipo: str | None = None
    descripcion: str | None = None
    subido_por_id: int | None = None
    subido_por_nombre: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
