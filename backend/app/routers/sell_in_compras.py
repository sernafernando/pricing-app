"""Router: sell-in purchases (`/api/sell-in/compras`), feature sell-in-sell-out T2.

A sell-in purchase is a purchase discount spread over the items it covers; it
lowers the cost of THAT purchase's units only. The math lives in
`app.services.sell_in` (split + `compras`); this module is HTTP only.

- The preview and the load need `sell_in.gestionar` (migration
  `20261025_sell_in_permisos`).
- `POST /preview` writes nothing. `POST ""` recomputes the same split
  server-side, freezes each line's base cost and records the author from the
  token, never from the body.
- Business-rule errors are a 422 with one readable Spanish message.
- There is no delete and no edit.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario
from app.schemas.sell_in import (
    SellInCompraCreate,
    SellInCompraOut,
    SellInPreviewIn,
    SellInPreviewOut,
)
from app.services.permisos_service import verificar_permiso
from app.services.sell_in import compras as service

router = APIRouter(prefix="/sell-in/compras", tags=["Sell in"])


def _forbidden(codigo: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"No tienes permiso: {codigo}")


def requiere_gestionar(current_user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)) -> Usuario:
    if not verificar_permiso(db, current_user, "sell_in.gestionar"):
        raise _forbidden("sell_in.gestionar")
    return current_user


def _unprocessable(exc: service.SellInError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.post("/preview", response_model=SellInPreviewOut)
def preview_compra(
    data: SellInPreviewIn,
    _user: Usuario = Depends(requiere_gestionar),
    db: Session = Depends(get_db),
) -> dict:
    """How the total would be split, with each line's cost without and with sell in. Writes nothing."""
    try:
        return service.calcular_preview(db, data)
    except service.SellInError as exc:
        raise _unprocessable(exc) from exc


@router.post("", response_model=SellInCompraOut, status_code=status.HTTP_201_CREATED)
def crear_compra(
    data: SellInCompraCreate,
    user: Usuario = Depends(requiere_gestionar),
    db: Session = Depends(get_db),
) -> dict:
    try:
        compra = service.crear_compra(db, data, user.id)
    except service.SellInError as exc:
        db.rollback()
        raise _unprocessable(exc) from exc
    return service.serializar(db, [compra])[0]
