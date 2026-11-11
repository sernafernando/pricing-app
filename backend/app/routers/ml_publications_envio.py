"""Publicaciones ML: the write of a product's shipping-cost choice (S7b).

- `PUT /ml-publications/products/{item_id}/envio` (`productos.editar_precio_clasica`, the permission of Productos'
  main price edit): stores which shipping cost the product uses (`max`, `mla` + one of ITS publications,
  `promedio`, `ponderado`) with the user and the time, and audits the change. Every pricing caller applies it
  through `envio_real_service`.

The options to choose from are read by `GET /ml-publications/view/products/{item_id}/envio` in
`ml_publications_view.py`, a router that only reads; this write lives here so it stays that way.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.orm import Session

from app.api.deps import require_permiso
from app.core.exceptions import ErrorCode, api_error
from app.models.usuario import Usuario
from app.routers.ml_publications_view import get_view_db
from app.schemas.ml_publications_view import EleccionEnvioGuardada, EleccionEnvioIn
from app.services import envio_producto_eleccion

router = APIRouter(prefix="/ml-publications", tags=["ml-publications"])

PERMISO_ELEGIR_ENVIO = "productos.editar_precio_clasica"


@router.put("/products/{item_id}/envio", response_model=EleccionEnvioGuardada)
def put_product_envio(
    body: EleccionEnvioIn,
    item_id: int = Path(..., ge=1),
    user: Usuario = Depends(require_permiso(PERMISO_ELEGIR_ENVIO)),
    db: Session = Depends(get_view_db),
) -> dict[str, Any]:
    """Store which shipping cost the product uses (`max`, `mla` + one of ITS publications, `promedio`,
    `ponderado`), with the user and the time; it replaces the previous choice. `max` is stored as a row, so who chose
    it stays recorded. From the next read on, every pricing caller resolves the product with it
    (`envio_real_service`). 422 (`field: mla`) for a publication of another product."""
    try:
        saved = envio_producto_eleccion.guardar_eleccion(db, item_id, body.modo, body.mla, usuario_id=user.id)
    except envio_producto_eleccion.EleccionInvalida as exc:
        db.rollback()
        error = api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, ErrorCode.VALIDATION_ERROR, exc.message)
        error.detail["field"] = exc.field
        raise error from exc
    if saved is None:
        db.rollback()
        raise api_error(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, f"El producto {item_id} no existe")
    db.commit()
    return saved
