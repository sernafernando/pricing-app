"""Router: tacticals (`/api/tacticals`, tacticals T1); HTTP only over `app.services.tacticals`. The contract T2 and T5
build against is `handoffs/tactical-tarea.md` "Contrato final".

- Permissions follow the tactical's `tipo`: a sell-in one needs `sell_in.ver` to read and `sell_in.gestionar` to load
  or void; a sell-out one `sell_out.ver` / `sell_out.gestionar`. The list returns only the kinds the caller may read
  (403 when none); a tactical of a kind the caller may not read is a 403.
- The author comes from the token, never from the body.
- `GET ""` is paginated, newest start first, filtered by kind, brand, estado (vigentes | vencidos | anulados), a
  period its dates overlap (an inverted one is a 422) and free text over name or reference.
- `PATCH /{id}` changes only what is safe on live money: name, note, end date (never before today nor before the
  start) and the lines' caps (never below what a child already used); a voided tactical is a 409.
- A create stores at most `HIJOS_MAX` (500) campaigns or bonuses (a per-product line counts each product): past it,
  a 422 before anything is stored.
- Collection (tactical cobranza S2): `PUT /{id}/cobranza` saves the one record (only `fecha_cobro` required, 422
  without it), `DELETE /{id}/cobranza` undoes it (204 when there is nothing to undo); both need `<tipo>.gestionar`.
  The list filters by `cobranza` (cobrados | pendientes) and returns `kpis` (Pendientes / Cobrados: count and money
  used per currency) over the other filters.
- A broken rule is a 422 with one Spanish message ("Línea N: ..." when a line broke it); a campaign being
  recomputed is a 409 (retry; nothing stored); voiding twice is a 409; an unknown tactical is a 404.
"""

from __future__ import annotations

from datetime import date
from typing import Optional, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.tactical import Tactical
from app.models.usuario import Usuario
from app.schemas.tacticals import (
    MARCA_MAX,
    NOMBRE_MAX,
    CobranzaFiltro,
    EstadoFiltro,
    Moneda,
    TacticalAnularIn,
    TacticalCobranzaIn,
    TacticalEditarIn,
    TacticalIn,
    TacticalListOut,
    TacticalOut,
    TipoTactical,
)
from app.services import tacticals as service
from app.services.permisos_service import verificar_permiso

router = APIRouter(prefix="/tacticals", tags=["Tacticals"])

TIPOS: tuple[TipoTactical, ...] = ("sell_in", "sell_out")
PAGE_SIZE_MAX = 200


def _exigir(db: Session, user: Usuario, tipo: str, accion: str) -> None:
    codigo = f"{tipo}.{accion}"
    if not verificar_permiso(db, user, codigo):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Falta el permiso {codigo}")


def _error(exc: service.TacticalError) -> HTTPException:
    if isinstance(exc, (service.TacticalOcupado, service.TacticalYaAnulado)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _buscar(db: Session, user: Usuario, tactical_id: int, accion: str) -> Tactical:
    tactical = db.query(Tactical).options(selectinload(Tactical.tiendas)).filter(Tactical.id == tactical_id).first()
    if tactical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"El tactical {tactical_id} no existe")
    _exigir(db, user, tactical.tipo, accion)
    return tactical


@router.post("", response_model=TacticalOut, status_code=status.HTTP_201_CREATED)
def crear_tactical(data: TacticalIn, user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    _exigir(db, user, data.tipo, "gestionar")
    try:
        tactical = service.crear(db, data, user.id)
    except service.TacticalError as exc:
        raise _error(exc) from exc
    return service.serializar(db, [tactical])[0]


@router.get("", response_model=TacticalListOut)
def listar_tacticals(
    tipo: Optional[TipoTactical] = None,
    marca: Optional[str] = Query(None, max_length=MARCA_MAX),
    moneda: Optional[Moneda] = None,
    estado: Optional[EstadoFiltro] = None,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    q: Optional[str] = Query(None, max_length=NOMBRE_MAX),
    cobranza: Optional[CobranzaFiltro] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=PAGE_SIZE_MAX),
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    pedidos = [tipo] if tipo else list(TIPOS)
    tipos = [t for t in pedidos if verificar_permiso(db, user, f"{t}.ver")]
    if not tipos:
        _exigir(db, user, pedidos[0], "ver")  # raises the 403 naming the missing permission
    if desde is not None and hasta is not None and hasta < desde:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="La fecha hasta no puede ser anterior a desde"
        )
    filtros = service.Filtros(
        tipos=tipos, marca=marca, moneda=moneda, estado=estado, desde=desde, hasta=hasta, q=q, cobranza=cobranza
    )
    total, filas = service.listar(db, filtros, page, page_size)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": service.serializar(db, filas),
        "kpis": service.kpis(db, filtros),
    }


@router.get("/{tactical_id}", response_model=TacticalOut)
def detalle_tactical(
    tactical_id: int, user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    return service.serializar(db, [_buscar(db, user, tactical_id, "ver")])[0]


@router.patch("/{tactical_id}", response_model=TacticalOut)
def editar_tactical(
    tactical_id: int,
    data: TacticalEditarIn,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Change the name, note, end date or the lines' caps (only those: the rest is Anular + Renovar); every active
    child takes it through its engine's edit step. Same permission as the create."""
    _buscar(db, user, tactical_id, "gestionar")
    try:
        tactical = service.editar(db, tactical_id, data, user.id)
    except service.TacticalError as exc:
        raise _error(exc) from exc
    if tactical is None:  # gone between the check and the lock
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"El tactical {tactical_id} no existe")
    return service.serializar(db, [tactical])[0]


@router.post("/{tactical_id}/anular", response_model=TacticalOut)
def anular_tactical(
    tactical_id: int,
    data: Optional[TacticalAnularIn] = Body(None),
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Void the tactical and every active child (the reason goes to the audit rows)."""
    _buscar(db, user, tactical_id, "gestionar")
    try:
        tactical = service.anular(db, tactical_id, user.id, data.motivo if data else None)
    except service.TacticalError as exc:
        raise _error(exc) from exc
    if tactical is None:  # gone between the check and the lock
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"El tactical {tactical_id} no existe")
    return service.serializar(db, [tactical])[0]


@router.put("/{tactical_id}/cobranza", response_model=TacticalOut)
def cobrar_tactical(
    tactical_id: int,
    data: TacticalCobranzaIn,
    user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Save (create or replace) the tactical's collection record: it reads "Cobrado" (tactical cobranza S2). Only
    `fecha_cobro` is required (422 without it). Same permission as editing the tactical: `<tipo>.gestionar`."""
    _buscar(db, user, tactical_id, "gestionar")
    tactical = service.cobrar(db, tactical_id, data, user.id)
    if tactical is None:  # gone between the check and the lock
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"El tactical {tactical_id} no existe")
    return service.serializar(db, [tactical])[0]


@router.delete(
    "/{tactical_id}/cobranza",
    response_model=TacticalOut,
    responses={status.HTTP_204_NO_CONTENT: {"description": "The tactical had no collection record: nothing to undo"}},
)
def deshacer_cobro_tactical(
    tactical_id: int, user: Usuario = Depends(get_current_user), db: Session = Depends(get_db)
) -> Union[dict, Response]:
    """Undo the collection: the record is deleted and the tactical reads "Pendiente" again (200 with the tactical).
    Idempotent: a tactical without a record is a 204 with no body. Permission `<tipo>.gestionar`."""
    tactical = _buscar(db, user, tactical_id, "gestionar")
    if not service.deshacer_cobro(db, tactical_id):
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return service.serializar(db, [tactical])[0]
