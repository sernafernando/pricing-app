"""Acciones IA (MCP delivery 2): the audit of AI writes, undo from the app, and the write kill switch.

Every route requires `mcp.escribir`. Undo runs through the same guard layer as the MCP tools (app.mcp.write): kill
switch, plan -> confirm token -> apply, live re-check, audit row with `undo_of_id`; the writes go through the real
endpoints as the logged-in user (origin `app`, client "App").
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import require_permiso
from app.core.database import get_db
from app.mcp import store
from app.mcp.write import guards, service
from app.mcp.write.context import ORIGEN_APP, WriteContext, WriteError
from app.models.usuario import Usuario

router = APIRouter(prefix="/admin/mcp", tags=["MCP Acciones IA"])

Resultado = Literal["ok", "rechazada", "bloqueada", "ambigua", "error", "denegada"]


class AccionIA(BaseModel):
    id: int
    plan_id: str
    created_at: Optional[str]
    usuario_id: int
    usuario_nombre: Optional[str]
    cliente: str
    tool: str
    accion: str
    objetivo: str
    objetivo_label: Optional[str]
    antes: dict[str, Any]
    despues: dict[str, Any]
    motivo: str
    resultado: str
    detalle: Optional[str]
    deshacible: bool
    deshecha: bool
    undo_of_id: Optional[int]


class AccionesIAResponse(BaseModel):
    total: int
    items: list[AccionIA]


class DeshacerPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accion_ids: Optional[list[int]] = Field(None, min_length=1, max_length=100)
    plan_id: Optional[str] = Field(None, max_length=40)
    motivo: str = Field(..., min_length=1, max_length=500)


class FilaDeshacer(BaseModel):
    accion_id: int
    objetivo: str
    objetivo_label: Optional[str]
    accion: str
    antes: dict[str, Any]
    despues: dict[str, Any]
    estado: Literal["lista", "bloqueada"]
    detalle: Optional[str]


class DeshacerPlanResponse(BaseModel):
    plan_id: Optional[str]
    confirm_token: Optional[str]
    expires_at: Optional[str]
    filas: list[FilaDeshacer]


class DeshacerAplicarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(..., min_length=1, max_length=40)
    confirm_token: str = Field(..., min_length=1, max_length=100)


class ResultadoDeshacer(BaseModel):
    accion_id: Optional[int]
    nueva_accion_id: Optional[int]
    resultado: str
    detalle: Optional[str]


class DeshacerAplicarResponse(BaseModel):
    plan_id: str
    resultados: list[ResultadoDeshacer]


class EscrituraEstado(BaseModel):
    habilitado: bool
    fuente: Literal["default", "db", "kill_switch"]


class EscrituraRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    habilitado: bool


def _context(user: Usuario) -> WriteContext:
    return WriteContext(
        usuario_id=user.id, username=user.username, connection_id=None, cliente="App", origen=ORIGEN_APP
    )


def _http(exc: WriteError) -> HTTPException:
    return HTTPException(status_code=exc.http_status, detail=exc.message)


@router.get("/acciones", response_model=AccionesIAResponse)
def listar_acciones(
    usuario_id: Optional[int] = Query(None),
    cliente: Optional[str] = Query(None, max_length=100),
    tool: Optional[str] = Query(None, max_length=64),
    resultado: Optional[Resultado] = Query(None),
    plan_id: Optional[str] = Query(None, max_length=40),
    desde: Optional[date] = Query(None),
    hasta: Optional[date] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_permiso(store.PERMISO_ESCRIBIR)),
) -> AccionesIAResponse:
    """Every AI write row (all users), newest first, with what changed, why, the outcome and whether it can still
    be undone."""
    data = service.list_actions(
        db,
        usuario_id=usuario_id,
        cliente=cliente,
        tool=tool,
        resultado=resultado,
        plan_id=plan_id,
        desde=desde,
        hasta=hasta,
        limit=limit,
        offset=offset,
    )
    return AccionesIAResponse(**data)


@router.post("/acciones/deshacer/plan", response_model=DeshacerPlanResponse)
async def planear_deshacer(
    body: DeshacerPlanRequest,
    current_user: Usuario = Depends(require_permiso(store.PERMISO_ESCRIBIR)),
) -> DeshacerPlanResponse:
    """Undo plan for some actions or a whole plan: rows ready to restore and rows blocked (changed since the action,
    already undone, not applied). 503 when AI writes are disabled."""
    if not body.accion_ids and not body.plan_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Indicá accion_ids o plan_id")
    try:
        plan = await service.plan_undo(_context(current_user), body.motivo, body.accion_ids, body.plan_id)
    except WriteError as exc:
        raise _http(exc) from exc
    return DeshacerPlanResponse(
        plan_id=plan.get("plan_id"),
        confirm_token=plan.get("confirm_token"),
        expires_at=plan.get("expires_at"),
        filas=[FilaDeshacer(**{**fila, "detalle": fila.get("detalle")}) for fila in plan["filas"]],
    )


@router.post("/acciones/deshacer/aplicar", response_model=DeshacerAplicarResponse)
async def aplicar_deshacer(
    body: DeshacerAplicarRequest,
    current_user: Usuario = Depends(require_permiso(store.PERMISO_ESCRIBIR)),
) -> DeshacerAplicarResponse:
    """Apply an undo plan with its token (single use): 409 for a used, expired or foreign token, 503 when writes are
    disabled."""
    try:
        result = await service.apply_plan(_context(current_user), service.UNDO_TOOL, body.plan_id, body.confirm_token)
    except WriteError as exc:
        raise _http(exc) from exc
    return DeshacerAplicarResponse(
        plan_id=result["plan_id"],
        resultados=[ResultadoDeshacer(**r) for r in result["resultados"]],
    )


@router.get("/escritura", response_model=EscrituraEstado)
def estado_escritura(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_permiso(store.PERMISO_ESCRIBIR)),
) -> EscrituraEstado:
    """Whether AI writes are on and what decides it (`kill_switch` = an env switch on the server wins)."""
    enabled, source = guards.write_status(db)
    return EscrituraEstado(habilitado=enabled, fuente=source)


@router.put("/escritura", response_model=EscrituraEstado)
def cambiar_escritura(
    body: EscrituraRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_permiso(store.PERMISO_ESCRIBIR)),
) -> EscrituraEstado:
    """Turn AI writes on or off (instant, stored in the DB). An env kill switch still wins: the answer says so."""
    guards.set_write_enabled(db, body.habilitado, current_user.username or str(current_user.id))
    db.commit()
    enabled, source = guards.write_status(db)
    return EscrituraEstado(habilitado=enabled, fuente=source)
