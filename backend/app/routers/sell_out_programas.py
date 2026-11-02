"""Router: sell-out programs (`/api/sell-out/programas`), campaign system S1 ("Programa" on screen).

A program groups the campaigns that are one deal renewed over time or split by what each applies to (production:
"EPSON PROGRAM1" x13, "EPSON PROG 3.0", "EPSON PROGR 7.5", ... over the same dates). It is metadata only: the money of a campaign never depends on it. The rules live in `app.services.sell_out.programas`;
this module is HTTP only.

- Reads need `sell_out.ver`; create, edit and assign need `sell_out.gestionar`, the campaigns' own permissions (no
  new one). The author comes from the token.
- `GET ""` lists programs by name with how many campaigns each has (`campanas`), how many are active (`activas`)
  and their date span (`desde`, `hasta`), filtered by `estado`.
- `POST ""` creates one (201); `PATCH /{id}` changes only the fields sent. A name taken by another program,
  ignoring case, is a 409; an empty name a 422; an unknown program a 404.
- `POST /asignar` (`{"campana_ids": [...], "programa_id": id | null}`) sets or clears the program of up to 500
  campaigns, active or voided, all or nothing, with one audit row per changed campaign. Unknown campaigns are a 422
  naming them, an unknown program a 404, an archived one a 422. It queues no rebuild.
- `GET /sugerencias` proposes groups of campaigns without a program that share their exact dates (`fecha_desde`,
  `fecha_hasta`), each with a proposed name (`base`: the words all its names start with, or its date range);
  nothing is applied.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.usuario import Usuario
from app.routers.sell_out_campanas import requiere_gestionar, requiere_ver
from app.schemas.sell_out import (
    EstadoPrograma,
    SellOutAsignarIn,
    SellOutAsignarOut,
    SellOutProgramaIn,
    SellOutProgramaListOut,
    SellOutProgramaOut,
    SellOutProgramaPatchIn,
    SellOutSugerenciaListOut,
)
from app.services.sell_out import programas as service

router = APIRouter(prefix="/sell-out/programas", tags=["Sell out"])


def _error(db: Session, exc: service.ProgramaError) -> HTTPException:
    db.rollback()
    if isinstance(exc, service.ProgramaNoExiste):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, service.ProgramaDuplicado):
        code = status.HTTP_409_CONFLICT
    else:
        code = 422
    return HTTPException(status_code=code, detail=str(exc))


def _pagina(filas: list[dict], page: int, page_size: int) -> dict:
    inicio = (page - 1) * page_size
    return {"items": filas[inicio : inicio + page_size], "total": len(filas), "page": page, "page_size": page_size}


@router.get("", response_model=SellOutProgramaListOut)
def listar_programas(
    estado: Optional[EstadoPrograma] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _user: Usuario = Depends(requiere_ver),
    db: Session = Depends(get_db),
) -> dict:
    """Programs by name, with their campaigns' counts and date span, one page at a time."""
    return _pagina(service.listar(db, estado), page, page_size)


@router.get("/sugerencias", response_model=SellOutSugerenciaListOut)
def sugerir_programas(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _user: Usuario = Depends(requiere_ver),
    db: Session = Depends(get_db),
) -> dict:
    """Campaigns without a program that share their exact dates, biggest group first: a proposal to assign by
    hand. Grouped in Python, so the page is cut over the sorted groups."""
    return _pagina(service.sugerencias(db), page, page_size)


@router.post("", response_model=SellOutProgramaOut, status_code=status.HTTP_201_CREATED)
def crear_programa(
    data: SellOutProgramaIn, user: Usuario = Depends(requiere_gestionar), db: Session = Depends(get_db)
) -> dict:
    try:
        programa = service.crear(db, data, user.id)
    except service.ProgramaError as exc:
        raise _error(db, exc) from exc
    return service.detalle(db, programa.id)


@router.patch("/{programa_id}", response_model=SellOutProgramaOut)
def editar_programa(
    programa_id: int,
    data: SellOutProgramaPatchIn,
    _user: Usuario = Depends(requiere_gestionar),
    db: Session = Depends(get_db),
) -> dict:
    """Change the name, description or state (archive / reactivate); only the fields sent."""
    try:
        service.editar(db, programa_id, data)
    except service.ProgramaError as exc:
        raise _error(db, exc) from exc
    return service.detalle(db, programa_id)


@router.post("/asignar", response_model=SellOutAsignarOut)
def asignar_programa(
    data: SellOutAsignarIn, user: Usuario = Depends(requiere_gestionar), db: Session = Depends(get_db)
) -> dict:
    """Set (or clear, with `programa_id: null`) the program of the campaigns, all or nothing."""
    try:
        asignadas, sin_cambio = service.asignar(db, data.campana_ids, data.programa_id, user.id)
    except service.ProgramaError as exc:
        raise _error(db, exc) from exc
    return {"asignadas": asignadas, "sin_cambio": sin_cambio}
