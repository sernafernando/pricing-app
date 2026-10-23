"""Router: bonuses (`/api/sell-in/bonos`), sell-in-sell-out T3c-3 (scopes and % in T3e-3).

A bonus pays an amount per invoiced unit, or a percentage of the invoiced net,
of the products it reaches (a brand, a category, some models, or every line of
one Compras operation) over a supplier-invoice date range. The `sell_in.bono` worker applies it by itself to
every Compras operation it reaches (`app.services.sell_in.bonos`); this module
is HTTP only over `app.services.sell_in.bonos_crud`.

- Reads (`GET ""`, `GET /{id}`) need `sell_in.ver`; load, edit and void need
  `sell_in.gestionar` (the sell-in permissions: a bonus lowers product cost).
- The author comes from the token, never from the body.
- `GET ""` is paginated, newest first, filtered by estado and brand (exact).
  Every bonus carries its models, its operation's number and what it generated
  so far (active purchases, units, amount in its currency and per currency).
- Edit is a full replace (`PUT /{id}`) of an active bonus; a voided one is a 409.
- There is no delete: a bonus is voided (`POST /{id}/anular`, optional reason
  kept in the audit row; 409 if it already was), which voids what it generated.
- `GET /{id}/alcance` (`sell_in.ver`) answers what the bonus reaches for its
  panel: generated purchases, operations of its scope pending an invoice, and
  operations of its scope invoiced outside the range (`bonos_alcance`), each capped with
  its count.
- Business-rule errors are a 422 with one readable Spanish message; an unknown
  bonus is a 404.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.sell_in import SellInBonoMarca
from app.models.usuario import Usuario
from app.routers.sell_in_compras import requiere_gestionar, requiere_ver
from app.schemas.sell_in_bonos import (
    ALCANCE_LIMITE,
    ALCANCE_LIMITE_MAX,
    Estado,
    SellInBonoAlcanceOut,
    SellInBonoAnularIn,
    SellInBonoIn,
    SellInBonoListOut,
    SellInBonoOut,
)
from app.services.sell_in import bonos_alcance
from app.services.sell_in import bonos_crud as service

router = APIRouter(prefix="/sell-in/bonos", tags=["Sell in"])


def _no_existe(bono_id: int) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"El bono {bono_id} no existe")


def _unprocessable(exc: service.SellInBonoError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _conflict(exc: service.SellInBonoError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("", response_model=SellInBonoOut, status_code=status.HTTP_201_CREATED)
def crear_bono(data: SellInBonoIn, user: Usuario = Depends(requiere_gestionar), db: Session = Depends(get_db)) -> dict:
    try:
        bono = service.crear_bono(db, data, user.id)
    except service.SellInBonoError as exc:
        db.rollback()
        raise _unprocessable(exc) from exc
    return service.serializar(db, [bono])[0]


@router.get("", response_model=SellInBonoListOut)
def listar_bonos(
    estado: Optional[Estado] = Query(None),
    marca: Optional[str] = Query(None, max_length=100, description="Exact brand"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _user: Usuario = Depends(requiere_ver),
    db: Session = Depends(get_db),
) -> dict:
    bonos, total = service.listar_bonos(
        db, service.FiltrosBonos(estado=estado, marca=marca), page=page, page_size=page_size
    )
    return {"items": service.serializar(db, bonos), "total": total, "page": page, "page_size": page_size}


@router.get("/{bono_id}", response_model=SellInBonoOut)
def obtener_bono(bono_id: int, _user: Usuario = Depends(requiere_ver), db: Session = Depends(get_db)) -> dict:
    bono = db.get(SellInBonoMarca, bono_id)
    if bono is None:
        raise _no_existe(bono_id)
    return service.serializar(db, [bono])[0]


@router.get("/{bono_id}/alcance", response_model=SellInBonoAlcanceOut)
def alcance_bono(
    bono_id: int,
    limite: int = Query(ALCANCE_LIMITE, ge=1, le=ALCANCE_LIMITE_MAX),
    _user: Usuario = Depends(requiere_ver),
    db: Session = Depends(get_db),
) -> dict:
    """What the bonus reaches: generated purchases, operations pending an invoice, and out of range."""
    bono = db.get(SellInBonoMarca, bono_id)
    if bono is None:
        raise _no_existe(bono_id)
    return bonos_alcance.alcance(db, bono, limite)


@router.put("/{bono_id}", response_model=SellInBonoOut)
def editar_bono(
    bono_id: int,
    data: SellInBonoIn,
    user: Usuario = Depends(requiere_gestionar),
    db: Session = Depends(get_db),
) -> dict:
    """Full replace of an active bonus; the worker then reconciles what it generated."""
    try:
        bono = service.editar_bono(db, bono_id, data, user.id)
    except service.SellInBonoYaAnulado as exc:
        db.rollback()
        raise _conflict(exc) from exc
    except service.SellInBonoError as exc:
        db.rollback()
        raise _unprocessable(exc) from exc
    if bono is None:
        raise _no_existe(bono_id)
    return service.serializar(db, [bono])[0]


@router.post("/{bono_id}/anular", response_model=SellInBonoOut)
def anular_bono(
    bono_id: int,
    data: Optional[SellInBonoAnularIn] = Body(None),
    user: Usuario = Depends(requiere_gestionar),
    db: Session = Depends(get_db),
) -> dict:
    """Void the bonus (the reason goes to the audit row); the worker then voids what it generated."""
    try:
        bono = service.anular_bono(db, bono_id, user.id, data.motivo if data else None)
    except service.SellInBonoYaAnulado as exc:
        db.rollback()
        raise _conflict(exc) from exc
    if bono is None:
        raise _no_existe(bono_id)
    return service.serializar(db, [bono])[0]
