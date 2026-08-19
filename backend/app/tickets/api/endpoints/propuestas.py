"""AI triage confirmation endpoints (tickets-ai-triage PR 4b): confirm/discard
a proposal, batch-confirm several, and the human retrigger with its
single-flight guard. Kept out of `tickets.py` (already large)."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService
from app.tickets.api.deps import get_triage_provider
from app.tickets.models.ejemplo_correccion import EjemploCorreccion
from app.tickets.models.propuesta_ia import PropuestaIA
from app.tickets.models.ticket import Ticket
from app.tickets.schemas.ticket_schemas import (
    ConfirmarBatchRequest,
    ConfirmarRequest,
    EjemploResponse,
    EjemploToggleRequest,
    PropuestaResponse,
)
from app.tickets.services import confirmacion_service, ejemplos_service
from app.tickets.services.confirmacion_service import (
    CorreccionCampoNoPermitidoError,
    CorreccionValorInvalidoError,
    PropuestaBatchInvalidaError,
    PropuestaCampoNoPermitidoError,
    PropuestaNoDescartableError,
    PropuestaNoEncontradaError,
    PropuestaNoPendienteError,
    PropuestaSectorDejaTipoHuerfanoError,
    PropuestaSectorInvalidoError,
    PropuestaTipoSectorInvalidoError,
    TicketNoEncontradoError,
)
from app.tickets.services.triage_service import LlmProvider, run_triage

router = APIRouter()

PERMISO_CONFIRMAR = "tickets.triage.confirmar"
# tickets-triage-feedback PR5a: DELIBERATELY independent from
# PERMISO_CONFIRMAR — curating the few-shot correction corpus is a narrower
# judgment than confirming AI proposals, see `EjemploResponse`'s docstring.
PERMISO_EJEMPLOS = "tickets.triage.ejemplos"


def _check_permiso(db: Session, user: Usuario, permiso: str) -> None:
    """Raise 403 if user lacks the required permission (duplicated per the
    existing tickets.py/workflows.py/sectores.py convention)."""
    if not PermisosService(db).tiene_permiso(user, permiso):
        raise HTTPException(status_code=403, detail=f"Sin permiso: {permiso}")


def _check_acceso_ticket(db: Session, user: Usuario, ticket: Ticket) -> None:
    """Duplicated from `tickets.py::_check_acceso_ticket` per this file's
    established duplication convention (see `_check_permiso` above)."""
    if PermisosService(db).tiene_permiso(user, "tickets.ver"):
        return
    if ticket.creador_id == user.id:
        return
    raise HTTPException(status_code=403, detail="No tenés acceso a este ticket")


@router.get("/tickets/{ticket_id}/propuestas", response_model=list[PropuestaResponse])
def listar_propuestas_pendientes(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[PropuestaResponse]:
    """Lista las propuestas de IA de un ticket que un humano todavía puede
    revisar. Visible con solo acceso al ticket (creador o tickets.ver) — NO
    requiere tickets.triage.confirmar: la confianza debe verse antes de
    confirmar, independientemente de quién puede confirmar (spec:
    "Provenance Is Always Visible" / "Confidence is visible before
    confirming").

    Dos formas (feat/tickets-triage-aplicar-directo): `pendiente` (el flujo
    original — nada se aplicó todavía, sobrevive cuando
    TICKETS_TRIAGE_AUTO_APPLY=False o un campo quedó gateado por confianza)
    y `confirmada` con `confirmado_por_id IS NULL` (`ia_auto` — YA se
    aplicó, y nadie lo revisó todavía). Un `confirmada` con confirmador NO
    nulo (humano ya confirmó, o `ia_confirmada`) nunca aparece acá — ya no
    hay nada pendiente de revisión."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")
    _check_acceso_ticket(db, current_user, ticket)

    return (
        db.query(PropuestaIA)
        .filter(
            PropuestaIA.ticket_id == ticket_id,
            or_(
                PropuestaIA.estado == "pendiente",
                and_(PropuestaIA.estado == "confirmada", PropuestaIA.confirmado_por_id.is_(None)),
            ),
        )
        .order_by(PropuestaIA.campo)
        .all()
    )


@router.post("/propuestas/{propuesta_id}/confirmar", response_model=PropuestaResponse)
def confirmar_propuesta(
    propuesta_id: int,
    background_tasks: BackgroundTasks,
    payload: ConfirmarRequest | None = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> PropuestaResponse:
    """Confirma una propuesta de IA `pendiente`, ratifica una ya aplicada
    automáticamente (`confirmada` con `confirmado_por_id` nulo) sin
    reescribir el ticket, o la CORRIGE si el body incluye
    `valor_corregido` (sólo severidad/urgencia). Requiere:
    tickets.triage.confirmar

    Best-effort correction capture (tickets-triage-feedback PR3): scheduled
    ONLY when the confirm resolved to a genuine correction
    (`estado == 'corregida'`) — a plain ratification or a low-confidence
    `pendiente` confirm never schedules capture. Dark-launched behind
    `TICKETS_TRIAGE_EJEMPLOS_CAPTURE`; the flag check itself lives inside
    `ejemplos_service.capturar_correccion` so this endpoint stays a single
    unconditional `add_task` call regardless of the flag's value."""
    _check_permiso(db, current_user, PERMISO_CONFIRMAR)
    valor_corregido = payload.valor_corregido if payload else None
    try:
        resultado = confirmacion_service.confirmar(db, propuesta_id, current_user, valor_corregido)
        if resultado.estado == "corregida":
            background_tasks.add_task(ejemplos_service.capturar_correccion, resultado.id)
        return resultado
    except PropuestaNoEncontradaError:
        raise HTTPException(status_code=404, detail=f"Propuesta {propuesta_id} no encontrada")
    except TicketNoEncontradoError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (CorreccionCampoNoPermitidoError, CorreccionValorInvalidoError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PropuestaCampoNoPermitidoError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (
        PropuestaSectorInvalidoError,
        PropuestaTipoSectorInvalidoError,
        PropuestaSectorDejaTipoHuerfanoError,
    ) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PropuestaNoPendienteError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/propuestas/{propuesta_id}/descartar", response_model=PropuestaResponse)
def descartar_propuesta(
    propuesta_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> PropuestaResponse:
    """Descarta una propuesta de IA (nunca vuelve a `pendiente`): si está
    `pendiente`, no toca el ticket (comportamiento original PR 4b); si ya
    fue aplicada automáticamente (`confirmada` con `confirmado_por_id`
    nulo) y su campo admite revertirse, limpia el valor del ticket y su
    origen. Requiere: tickets.triage.confirmar"""
    _check_permiso(db, current_user, PERMISO_CONFIRMAR)
    try:
        return confirmacion_service.descartar(db, propuesta_id, current_user)
    except PropuestaNoEncontradaError:
        raise HTTPException(status_code=404, detail=f"Propuesta {propuesta_id} no encontrada")
    except TicketNoEncontradoError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PropuestaNoDescartableError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
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
    except TicketNoEncontradoError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PropuestaCampoNoPermitidoError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (
        PropuestaSectorInvalidoError,
        PropuestaTipoSectorInvalidoError,
        PropuestaSectorDejaTipoHuerfanoError,
    ) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
    como `reemplazada` las `pendiente` y las `confirmada` sin revisar
    —`ia_auto`, `confirmado_por_id` nulo— primero; una `confirmada` que un
    HUMANO ya ratificó nunca se toca). Requiere: tickets.triage.confirmar"""
    _check_permiso(db, current_user, PERMISO_CONFIRMAR)

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    activas = (
        db.query(PropuestaIA)
        .filter(
            PropuestaIA.ticket_id == ticket_id,
            # 'corregida' added by tickets-triage-feedback PR1 (design's
            # `estado` consumer audit, item 2 of 3): a corrected proposal
            # is a settled human decision — without it here, a plain
            # retrigger (no `forzar`) would silently proceed instead of
            # 409ing, and re-surface a field the human already corrected.
            # The `forzar` degrade loop below deliberately does NOT touch
            # `corregida` rows (only `pendiente`/unreviewed `confirmada`)
            # — a human correction is never silently replaced.
            PropuestaIA.estado.in_(("pendiente", "confirmada", "corregida")),
        )
        .all()
    )

    if activas and not forzar:
        raise HTTPException(
            status_code=409,
            detail="Ya existe una clasificación pendiente o confirmada para este ticket; use forzar=true para reintentar",
        )

    if forzar:
        # Real pre-push review finding: with auto-apply, most proposals now
        # arrive already `confirmada` — only degrading `pendiente` ones (the
        # ORIGINAL PR 4b shape) left every `confirmada`/`ia_auto` row active
        # forever, so `_ya_tiene_propuesta_activa` silently blocked EVERY
        # field on the next `run_triage` call: `forzar=true` returned
        # `{"ok": True}` and did nothing on any auto-classified ticket. A
        # HUMAN-confirmed row (`confirmado_por_id` set) is a decision a
        # person already ratified and must never be silently replaced by a
        # forced retrigger — only the unreviewed `ia_auto` shape degrades.
        for propuesta in activas:
            if propuesta.estado == "pendiente" or (
                propuesta.estado == "confirmada" and propuesta.confirmado_por_id is None
            ):
                propuesta.estado = "reemplazada"
        db.commit()

    background_tasks.add_task(run_triage, ticket_id, triage_provider)
    return {"ok": True}


@router.get("/tickets/triage/ejemplos", response_model=list[EjemploResponse])
def listar_ejemplos(
    campo: str | None = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[EjemploResponse]:
    """Lista los ejemplos capturados de correcciones humanas (tickets-
    triage-feedback PR5a), opcionalmente filtrados por `campo`, paginados.
    Requiere: tickets.triage.ejemplos (independiente de
    tickets.triage.confirmar — ver `PERMISO_EJEMPLOS`)."""
    _check_permiso(db, current_user, PERMISO_EJEMPLOS)

    query = db.query(EjemploCorreccion)
    if campo is not None:
        query = query.filter(EjemploCorreccion.campo == campo)

    return query.order_by(EjemploCorreccion.id).offset(skip).limit(limit).all()


@router.patch("/tickets/triage/ejemplos/{ejemplo_id}", response_model=EjemploResponse)
def toggle_ejemplo(
    ejemplo_id: int,
    payload: EjemploToggleRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> EjemploResponse:
    """Activa/desactiva un ejemplo capturado (tickets-triage-feedback
    PR5a). Toma efecto INMEDIATAMENTE en la próxima llamada a
    `ejemplos_service._similarity_query` — ese filtra sobre
    `EjemploCorreccion.active`, sin caché ni propagación demorada. Requiere:
    tickets.triage.ejemplos."""
    _check_permiso(db, current_user, PERMISO_EJEMPLOS)

    ejemplo = db.query(EjemploCorreccion).filter(EjemploCorreccion.id == ejemplo_id).first()
    if not ejemplo:
        raise HTTPException(status_code=404, detail=f"Ejemplo {ejemplo_id} no encontrado")

    ejemplo.active = payload.active
    db.commit()
    db.refresh(ejemplo)
    return ejemplo
