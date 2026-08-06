"""AI triage confirmation endpoints (tickets-ai-triage PR 4b): confirm/discard
a proposal, batch-confirm several, and the human retrigger with its
single-flight guard. Kept out of `tickets.py` (already large)."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService
from app.tickets.api.deps import get_triage_provider
from app.tickets.models.propuesta_ia import PropuestaIA
from app.tickets.models.ticket import Ticket
from app.tickets.schemas.ticket_schemas import ConfirmarBatchRequest, PropuestaResponse
from app.tickets.services import confirmacion_service
from app.tickets.services.confirmacion_service import (
    PropuestaBatchInvalidaError,
    PropuestaNoEncontradaError,
    PropuestaNoPendienteError,
)
from app.tickets.services.triage_service import LlmProvider, run_triage

router = APIRouter()

PERMISO_CONFIRMAR = "tickets.triage.confirmar"


def _check_permiso(db: Session, user: Usuario, permiso: str) -> None:
    """Raise 403 if user lacks the required permission (duplicated per the
    existing tickets.py/workflows.py/sectores.py convention)."""
    if not PermisosService(db).tiene_permiso(user, permiso):
        raise HTTPException(status_code=403, detail=f"Sin permiso: {permiso}")


@router.post("/propuestas/{propuesta_id}/confirmar", response_model=PropuestaResponse)
def confirmar_propuesta(
    propuesta_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> PropuestaResponse:
    """Confirma una propuesta de IA pendiente. Requiere: tickets.triage.confirmar"""
    _check_permiso(db, current_user, PERMISO_CONFIRMAR)
    try:
        return confirmacion_service.confirmar(db, propuesta_id, current_user)
    except PropuestaNoEncontradaError:
        raise HTTPException(status_code=404, detail=f"Propuesta {propuesta_id} no encontrada")
    except PropuestaNoPendienteError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/propuestas/{propuesta_id}/descartar", response_model=PropuestaResponse)
def descartar_propuesta(
    propuesta_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> PropuestaResponse:
    """Descarta una propuesta de IA pendiente (nunca vuelve a `pendiente`).
    Requiere: tickets.triage.confirmar"""
    _check_permiso(db, current_user, PERMISO_CONFIRMAR)
    try:
        return confirmacion_service.descartar(db, propuesta_id, current_user)
    except PropuestaNoEncontradaError:
        raise HTTPException(status_code=404, detail=f"Propuesta {propuesta_id} no encontrada")
    except PropuestaNoPendienteError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/propuestas/confirmar-batch", response_model=list[PropuestaResponse])
def confirmar_propuestas_batch(
    payload: ConfirmarBatchRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[PropuestaResponse]:
    """Confirma varias propuestas en una sola operación atómica: todas o
    ninguna. Requiere: tickets.triage.confirmar"""
    _check_permiso(db, current_user, PERMISO_CONFIRMAR)
    try:
        return confirmacion_service.confirmar_batch(db, payload.propuesta_ids, current_user)
    except PropuestaBatchInvalidaError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/tickets/{ticket_id}/triage")
async def retriggerar_triage(
    ticket_id: int,
    background_tasks: BackgroundTasks,
    forzar: bool = False,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    triage_provider: LlmProvider = Depends(get_triage_provider),
) -> dict:
    """Reintenta la triage de IA (single-flight guard): rechaza con 409 si ya
    existe una propuesta `confirmada`/`pendiente`, salvo `forzar=true` (marca
    las `pendiente` como `reemplazada` primero). Requiere: tickets.triage.confirmar"""
    _check_permiso(db, current_user, PERMISO_CONFIRMAR)

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    activas = (
        db.query(PropuestaIA)
        .filter(PropuestaIA.ticket_id == ticket_id, PropuestaIA.estado.in_(("pendiente", "confirmada")))
        .all()
    )

    if activas and not forzar:
        raise HTTPException(
            status_code=409,
            detail="Ya existe una clasificación pendiente o confirmada para este ticket; use forzar=true para reintentar",
        )

    if forzar:
        for propuesta in activas:
            if propuesta.estado == "pendiente":
                propuesta.estado = "reemplazada"
        db.commit()

    background_tasks.add_task(run_triage, ticket_id, triage_provider)
    return {"ok": True}
