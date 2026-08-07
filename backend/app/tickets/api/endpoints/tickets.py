import enum
import logging
import math
import os
import uuid
from datetime import UTC, datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.sse import sse_publish
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService
from app.tickets.api.deps import get_triage_provider
from app.tickets.models.adjunto_ticket import AdjuntoTicket
from app.tickets.models.propuesta_ia import PropuestaIA
from app.tickets.models.sector_usuario import SectorUsuario
from app.tickets.models.asignacion_ticket import AsignacionTicket, TipoAsignacion
from app.tickets.models.comentario_ticket import ComentarioTicket
from app.tickets.models.historial_ticket import HistorialTicket
from app.tickets.models.sector import Sector
from app.tickets.models.ticket import Ticket, PrioridadTicket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, Workflow
from app.tickets.services.triage_service import LlmProvider, run_triage
from app.tickets.services.workflow_service import MotivoRechazoTransicion, WorkflowService
from app.tickets.schemas.ticket_schemas import (
    AdjuntoResponse,
    AsignarTicketRequest,
    BoardColumnResponse,
    BoardResponse,
    ComentarioCreate,
    ComentarioResponse,
    EstadoSimple,
    HistorialResponse,
    SectorSimple,
    TicketBadgeCount,
    TicketCardResponse,
    TicketCreate,
    TicketListPaginatedResponse,
    TicketResponse,
    TicketUpdate,
    TransicionRequest,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Allowed MIME types for ticket attachments
ALLOWED_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


# Single-box intake defaults (tickets-ai-triage PR 3) — seeded by
# 20260805_seed_inbox_sector_and_workflow.py.
INBOX_SECTOR_CODIGO = "INBOX"
INBOX_TIPO_CODIGO = "SIN_CLASIFICAR"
TITULO_DERIVADO_MAX_LEN = 80


def _derivar_titulo(texto: str) -> str:
    """Deriva un título legible a partir de texto libre (primeros ~80 caracteres).

    Pure function — no DB, no side effects, trivially testable.
    """
    return texto.strip()[:TITULO_DERIVADO_MAX_LEN].rstrip()


def _check_permiso(db: Session, user: Usuario, permiso: str) -> None:
    """Raise 403 if user lacks the required permission."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(user, permiso):
        raise HTTPException(status_code=403, detail=f"Sin permiso: {permiso}")


def _tiene_permiso(db: Session, user: Usuario, permiso: str) -> bool:
    """Check if user has a permission without raising."""
    return PermisosService(db).tiene_permiso(user, permiso)


def _check_acceso_ticket(db: Session, user: Usuario, ticket: Ticket) -> None:
    """
    Verifica que el usuario puede acceder a un ticket.
    - Si tiene tickets.ver → acceso a todos
    - Si es el creador → acceso a su ticket
    - Sino → 403
    """
    if _tiene_permiso(db, user, "tickets.ver"):
        return
    if ticket.creador_id == user.id:
        return
    raise HTTPException(status_code=403, detail="No tenés acceso a este ticket")


# ── Board + explicit ordering (tickets-ai-triage PR 5a) ────────────────
#
# severidad/urgencia are VARCHAR (see Ticket model docstring — never a PG
# ENUM, downgrade() would be a lie). A plain `ORDER BY severidad DESC` sorts
# ALPHABETICALLY: trivial, menor, mayor, critica — backwards. `_rank_case()`
# maps each vocabulary value to an explicit ordinal instead.
SEVERIDAD_VOCAB = ["trivial", "menor", "mayor", "critica"]
URGENCIA_VOCAB = ["baja", "normal", "alta", "inmediata"]
URGENCIA_SIN_CLASIFICAR = "sin_clasificar"
URGENCIA_ETIQUETAS = {
    "baja": "Baja",
    "normal": "Normal",
    "alta": "Alta",
    "inmediata": "Inmediata",
    URGENCIA_SIN_CLASIFICAR: "Sin clasificar",
}
URGENCIA_COLORES = {
    "baja": "#94A3B8",
    "normal": "#3B82F6",
    "alta": "#F59E0B",
    "inmediata": "#EF4444",
    URGENCIA_SIN_CLASIFICAR: "#9CA3AF",
}
ITEMS_POR_COLUMNA_DEFAULT = 20
ITEMS_POR_COLUMNA_MAX = 100


def _rank_case(columna, vocabulario: List[str]):
    """Explicit rank CASE for a VARCHAR column storing an ordered vocabulary.

    Pure function, unit-testable without a DB or a session — `columna` and
    the returned expression are plain SQLAlchemy constructs, never executed
    here. NULL/unknown values rank below every known value (-1), so they
    always sort last regardless of ASC/DESC direction.
    """
    whens = [(columna == valor, indice) for indice, valor in enumerate(vocabulario)]
    return case(*whens, else_=-1)


class TicketOrderBy(str, enum.Enum):
    """Query enum — the injection boundary: an unknown value 422s before
    FastAPI even calls `listar_tickets`, never reaching SQL."""

    CREATED_AT = "created_at"
    TITULO = "titulo"
    SEVERIDAD = "severidad"
    URGENCIA = "urgencia"


class TicketOrderDir(str, enum.Enum):
    ASC = "asc"
    DESC = "desc"


class AgrupacionBoard(str, enum.Enum):
    ESTADO = "estado"
    URGENCIA = "urgencia"


class UrgenciaFiltro(str, enum.Enum):
    """Query enum for `listar_tickets`'s `urgencia` filter — same
    injection-boundary pattern as `TicketOrderBy`/`AgrupacionBoard`. Added
    in PR 5b: the board groups by urgencia, but GET /tickets had no matching
    filter for its "load more" to reuse (gap found, closed here)."""

    BAJA = "baja"
    NORMAL = "normal"
    ALTA = "alta"
    INMEDIATA = "inmediata"
    SIN_CLASIFICAR = "sin_clasificar"


def _aplicar_orden(query, order_by: TicketOrderBy, order_dir: TicketOrderDir):
    """Applies ORDER BY, using `_rank_case()` for severidad/urgencia."""
    columnas = {
        TicketOrderBy.CREATED_AT: Ticket.created_at,
        TicketOrderBy.TITULO: Ticket.titulo,
        TicketOrderBy.SEVERIDAD: _rank_case(Ticket.severidad, SEVERIDAD_VOCAB),
        TicketOrderBy.URGENCIA: _rank_case(Ticket.urgencia, URGENCIA_VOCAB),
    }
    columna = columnas[order_by]
    return query.order_by(columna.desc() if order_dir == TicketOrderDir.DESC else columna.asc())


def _visible_tickets_filter(db: Session, current_user: Usuario):
    """Access-scope filter for the board — same visibility rule as
    `listar_tickets` (admin sees all; `tickets.ver` sees their sectores +
    lo que crearon; nadie más ve solo lo que creó). Returns `None` for "no
    filter" (admin) or a SQLAlchemy boolean expression to `.filter()`.
    """
    if _tiene_permiso(db, current_user, "tickets.admin"):
        return None
    if _tiene_permiso(db, current_user, "tickets.ver"):
        mis_sectores = (
            db.query(SectorUsuario.sector_id)
            .filter(SectorUsuario.usuario_id == current_user.id, SectorUsuario.activo.is_(True))
            .scalar_subquery()
        )
        return or_(Ticket.sector_id.in_(mis_sectores), Ticket.creador_id == current_user.id)
    return Ticket.creador_id == current_user.id


def _columnas_por_estado(db: Session, visible_filter) -> List[BoardColumnResponse]:
    """One column per configured `EstadoTicket`, including states with zero
    visible tickets — a column never disappears. A SINGLE query: LEFT JOIN
    from `tickets_estados` (every configured state) to a per-estado COUNT
    subquery over `tickets` (inlined SQL, not a second round-trip).
    """
    conteos = db.query(Ticket.estado_id.label("estado_id"), func.count(Ticket.id).label("total"))
    if visible_filter is not None:
        conteos = conteos.filter(visible_filter)
    conteos = conteos.group_by(Ticket.estado_id).subquery()

    filas = (
        db.query(
            EstadoTicket.id,
            EstadoTicket.nombre,
            EstadoTicket.color,
            func.coalesce(conteos.c.total, 0).label("total"),
        )
        .outerjoin(conteos, conteos.c.estado_id == EstadoTicket.id)
        .order_by(EstadoTicket.orden)
        .all()
    )
    return [
        BoardColumnResponse(clave=str(fila.id), etiqueta=fila.nombre, color=fila.color, total=fila.total, items=[])
        for fila in filas
    ]


def _columnas_por_urgencia(db: Session, visible_filter) -> List[BoardColumnResponse]:
    """Fixed vocabulary (baja|normal|alta|inmediata) plus a synthetic
    "Sin clasificar" column for NULL urgencia — unclassified tickets must
    never vanish from the board. Columns are a static Python list; only the
    totals come from the DB, in a SINGLE GROUP BY query.
    """
    conteo_expr = func.coalesce(Ticket.urgencia, URGENCIA_SIN_CLASIFICAR).label("clave")
    conteo_query = db.query(conteo_expr, func.count(Ticket.id).label("total"))
    if visible_filter is not None:
        conteo_query = conteo_query.filter(visible_filter)
    totales = {fila.clave: fila.total for fila in conteo_query.group_by(conteo_expr).all()}

    return [
        BoardColumnResponse(
            clave=clave,
            etiqueta=URGENCIA_ETIQUETAS[clave],
            color=URGENCIA_COLORES[clave],
            total=totales.get(clave, 0),
            items=[],
        )
        for clave in [*URGENCIA_VOCAB, URGENCIA_SIN_CLASIFICAR]
    ]


def _items_del_board(
    db: Session, agrupacion: AgrupacionBoard, visible_filter, items_por_columna: int
) -> Dict[str, List[TicketCardResponse]]:
    """`ROW_NUMBER() OVER (PARTITION BY <agrupación> ORDER BY <rank>)` capped
    at `items_por_columna` — the board's SECOND and LAST query. Items within
    a column are sorted by severidad rank descending (most severe first),
    tie-broken by created_at ascending (FIFO) for determinism.

    `propuestas_pendientes` is a correlated scalar subquery on
    `tickets_propuestas_ia`, evaluated inline per-row by the DB engine as
    part of THIS one statement — no extra round-trip, no N+1 from the app's
    perspective. Decided against a third query or a JOIN specifically to
    keep this endpoint's own query count at two.
    """
    grupo_expr = (
        Ticket.estado_id
        if agrupacion == AgrupacionBoard.ESTADO
        else func.coalesce(Ticket.urgencia, URGENCIA_SIN_CLASIFICAR)
    )
    rank_expr = _rank_case(Ticket.severidad, SEVERIDAD_VOCAB)
    propuestas_pendientes = (
        db.query(func.count(PropuestaIA.id))
        .filter(PropuestaIA.ticket_id == Ticket.id, PropuestaIA.estado == "pendiente")
        .correlate(Ticket)
        .scalar_subquery()
    )

    base = (
        db.query(
            Ticket.id,
            Ticket.titulo,
            Ticket.resumen,
            Ticket.severidad,
            Ticket.urgencia,
            Ticket.severidad_origen,
            Ticket.urgencia_origen,
            Ticket.created_at,
            EstadoTicket.id.label("estado_id"),
            EstadoTicket.codigo.label("estado_codigo"),
            EstadoTicket.nombre.label("estado_nombre"),
            EstadoTicket.color.label("estado_color"),
            EstadoTicket.es_final.label("estado_es_final"),
            Sector.id.label("sector_id"),
            Sector.codigo.label("sector_codigo"),
            Sector.nombre.label("sector_nombre"),
            Sector.color.label("sector_color"),
            propuestas_pendientes.label("propuestas_pendientes"),
            grupo_expr.label("grupo"),
        )
        .join(EstadoTicket, EstadoTicket.id == Ticket.estado_id)
        .join(Sector, Sector.id == Ticket.sector_id)
    )
    if visible_filter is not None:
        base = base.filter(visible_filter)

    row_number_col = (
        func.row_number().over(partition_by=grupo_expr, order_by=[rank_expr.desc(), Ticket.created_at.asc()])
    ).label("rn")
    ranked = base.add_columns(row_number_col).subquery()

    filas = db.query(ranked).filter(ranked.c.rn <= items_por_columna).order_by(ranked.c.grupo, ranked.c.rn).all()

    items_por_clave: Dict[str, List[TicketCardResponse]] = {}
    for fila in filas:
        items_por_clave.setdefault(str(fila.grupo), []).append(
            TicketCardResponse(
                id=fila.id,
                titulo=fila.titulo,
                resumen=fila.resumen,
                severidad=fila.severidad,
                urgencia=fila.urgencia,
                severidad_origen=fila.severidad_origen,
                urgencia_origen=fila.urgencia_origen,
                estado=EstadoSimple(
                    id=fila.estado_id,
                    codigo=fila.estado_codigo,
                    nombre=fila.estado_nombre,
                    color=fila.estado_color,
                    es_final=fila.estado_es_final,
                ),
                sector=SectorSimple(
                    id=fila.sector_id, codigo=fila.sector_codigo, nombre=fila.sector_nombre, color=fila.sector_color
                ),
                created_at=fila.created_at,
                propuestas_pendientes=fila.propuestas_pendientes or 0,
            )
        )
    return items_por_clave


@router.get("/tickets/board", response_model=BoardResponse)
def obtener_board(
    agrupacion: AgrupacionBoard = Query(..., description="Agrupación de columnas: estado o urgencia"),
    items_por_columna: int = Query(ITEMS_POR_COLUMNA_DEFAULT, ge=1, le=ITEMS_POR_COLUMNA_MAX),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> BoardResponse:
    """
    Tablero de tickets agrupado por estado o urgencia (tickets-ai-triage PR 5a).

    Exactamente DOS queries sin importar la cantidad de columnas: una
    GROUP BY para los totales por columna, una ROW_NUMBER() OVER (PARTITION
    BY <agrupación> ORDER BY <rank>) acotada a items_por_columna para los
    items. El overflow de una columna NO tiene paginación propia — el
    cliente pide más vía GET /tickets con el filtro correspondiente.
    """
    visible_filter = _visible_tickets_filter(db, current_user)

    if agrupacion == AgrupacionBoard.ESTADO:
        columnas = _columnas_por_estado(db, visible_filter)
    else:
        columnas = _columnas_por_urgencia(db, visible_filter)

    items_por_clave = _items_del_board(db, agrupacion, visible_filter, items_por_columna)
    for columna in columnas:
        columna.items = items_por_clave.get(columna.clave, [])

    return BoardResponse(agrupacion=agrupacion.value, columnas=columnas)


# ── Badge count (MUST be before /{ticket_id} to avoid path capture) ──


@router.get("/tickets/mis-pendientes/count", response_model=TicketBadgeCount)
def badge_count(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TicketBadgeCount:
    """
    Retorna el breakdown de tickets por categoría para el badge del TopBar.

    Categorías:
    - sin_asignar: tickets abiertos en scope sin asignación activa
    - asignados_a_mi: tickets abiertos asignados activamente al usuario
    - asignados_a_otros: tickets abiertos asignados a otro (solo con tickets.ver)
    - con_actividad_nueva: tickets con actividad posterior a la última revisión
    - pendientes (derivado): sin_asignar + asignados_a_mi (badge primario)

    Alcance:
    - tickets.ver → tickets de sus sectores + los que creó
    - sin tickets.ver → solo tickets que creó el usuario

    Usado por TicketBadge en el TopBar.
    """
    from sqlalchemy import func, or_

    puede_ver = PermisosService(db).tiene_permiso(current_user, "tickets.ver")

    # ── Sub-query: última revisión del usuario por ticket ────────────
    ultima_revision = (
        db.query(
            HistorialTicket.ticket_id,
            func.max(HistorialTicket.fecha).label("ultima_fecha"),
        )
        .filter(
            HistorialTicket.accion == "revisado",
            HistorialTicket.usuario_id == current_user.id,
        )
        .group_by(HistorialTicket.ticket_id)
        .subquery()
    )

    # ── Sub-query: último comentario de OTRO usuario por ticket ────────
    # Used for sin_responder and sin_leer — own comments excluded
    coment_otros = (
        db.query(
            HistorialTicket.ticket_id,
            func.max(HistorialTicket.fecha).label("ultima_fecha"),
        )
        .filter(
            HistorialTicket.accion == "comentado",
            HistorialTicket.usuario_id != current_user.id,
        )
        .group_by(HistorialTicket.ticket_id)
        .subquery()
    )

    # ── Sub-query: último comentario MÍO por ticket ─────────────────
    coment_mio = (
        db.query(
            HistorialTicket.ticket_id,
            func.max(HistorialTicket.fecha).label("ultima_fecha"),
        )
        .filter(
            HistorialTicket.accion == "comentado",
            HistorialTicket.usuario_id == current_user.id,
        )
        .group_by(HistorialTicket.ticket_id)
        .subquery()
    )

    # ── Sub-query: última actividad real por ticket ──────────────────
    # Actividad = cualquier acción que NO sea "revisado"
    ultima_actividad = (
        db.query(
            HistorialTicket.ticket_id,
            func.max(HistorialTicket.fecha).label("ultima_fecha"),
        )
        .filter(HistorialTicket.accion != "revisado")
        .group_by(HistorialTicket.ticket_id)
        .subquery()
    )

    # ── Sub-query: asignación activa por ticket ──────────────────────
    # Ticket.asignacion_actual is a Python property — cannot be used in SQL.
    # Use this subquery instead to filter by active assignment.
    asignacion_activa = (
        db.query(
            AsignacionTicket.ticket_id,
            AsignacionTicket.asignado_a_id,
        )
        .filter(AsignacionTicket.fecha_finalizacion.is_(None))
        .subquery()
    )

    # ── Scope predicate (shared across all four counts) ──────────────
    if puede_ver:
        mis_sectores = (
            db.query(SectorUsuario.sector_id)
            .filter(
                SectorUsuario.usuario_id == current_user.id,
                SectorUsuario.activo.is_(True),
            )
            .scalar_subquery()
        )
        scope_filter = or_(
            Ticket.sector_id.in_(mis_sectores),
            Ticket.creador_id == current_user.id,
        )
    else:
        scope_filter = Ticket.creador_id == current_user.id

    open_filter = EstadoTicket.es_final.is_(False)

    # ── Base query factory (open + in-scope tickets, joined to estado) ─
    def _base() -> object:
        return (
            db.query(func.count(func.distinct(Ticket.id)))
            .join(EstadoTicket, Ticket.estado_id == EstadoTicket.id)
            .filter(open_filter, scope_filter)
        )

    # 1. sin_asignar: open + in scope + no active assignment row
    sin_asignar: int = (
        _base()
        .outerjoin(asignacion_activa, Ticket.id == asignacion_activa.c.ticket_id)
        .filter(asignacion_activa.c.ticket_id.is_(None))
        .scalar()
        or 0
    )

    # 2. asignados_a_mi: open + in scope + active assignment to me
    asignados_a_mi: int = (
        _base()
        .join(asignacion_activa, Ticket.id == asignacion_activa.c.ticket_id)
        .filter(asignacion_activa.c.asignado_a_id == current_user.id)
        .scalar()
        or 0
    )

    # 3. asignados_a_otros: only computed for tickets.ver users (gate saves a query)
    if puede_ver:
        asignados_a_otros: int = (
            _base()
            .join(asignacion_activa, Ticket.id == asignacion_activa.c.ticket_id)
            .filter(
                asignacion_activa.c.asignado_a_id != current_user.id,
            )
            .scalar()
            or 0
        )
    else:
        asignados_a_otros = 0

    # 4. con_actividad_nueva: existing unread predicate (preserved verbatim)
    con_actividad_nueva: int = (
        _base()
        .outerjoin(ultima_revision, Ticket.id == ultima_revision.c.ticket_id)
        .outerjoin(ultima_actividad, Ticket.id == ultima_actividad.c.ticket_id)
        .filter(
            ultima_actividad.c.ultima_fecha.isnot(None),
            or_(
                ultima_revision.c.ultima_fecha.is_(None),
                ultima_actividad.c.ultima_fecha > ultima_revision.c.ultima_fecha,
            ),
        )
        .scalar()
        or 0
    )

    # 5. sin_responder: latest comment is from someone other than me
    # coment_otros IS NOT NULL AND (coment_mio IS NULL OR coment_otros > coment_mio)
    sin_responder: int = (
        _base()
        .outerjoin(coment_otros, Ticket.id == coment_otros.c.ticket_id)
        .outerjoin(coment_mio, Ticket.id == coment_mio.c.ticket_id)
        .filter(
            coment_otros.c.ultima_fecha.isnot(None),
            or_(
                coment_mio.c.ultima_fecha.is_(None),
                coment_otros.c.ultima_fecha > coment_mio.c.ultima_fecha,
            ),
        )
        .scalar()
        or 0
    )

    # 6. sin_leer: other's comment newer than my last revisado (ticket open)
    # coment_otros IS NOT NULL AND (ultima_revision IS NULL OR coment_otros > ultima_revision)
    sin_leer: int = (
        _base()
        .outerjoin(ultima_revision, Ticket.id == ultima_revision.c.ticket_id)
        .outerjoin(coment_otros, Ticket.id == coment_otros.c.ticket_id)
        .filter(
            coment_otros.c.ultima_fecha.isnot(None),
            or_(
                ultima_revision.c.ultima_fecha.is_(None),
                coment_otros.c.ultima_fecha > ultima_revision.c.ultima_fecha,
            ),
        )
        .scalar()
        or 0
    )

    # pendientes = acción requerida = sin_asignar + asignados_a_mi (no extra query)
    pendientes: int = sin_asignar + asignados_a_mi

    return TicketBadgeCount(
        pendientes=pendientes,
        sin_asignar=sin_asignar,
        asignados_a_mi=asignados_a_mi,
        asignados_a_otros=asignados_a_otros,
        con_actividad_nueva=con_actividad_nueva,
        sin_responder=sin_responder,
        sin_leer=sin_leer,
    )


@router.post("/tickets/marcar-revisado/{ticket_id}")
async def marcar_revisado(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Marca un ticket como revisado por el usuario actual.

    Crea una entrada 'revisado' en el historial. La siguiente actividad
    (comentario, cambio de estado, asignación) invalidará esta marca
    y el badge volverá a contar el ticket.

    Acceso: gestores con tickets.ver O el creador del ticket.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    # Gestores o creador del ticket pueden marcar como revisado
    _check_acceso_ticket(db, current_user, ticket)

    historial_entry = HistorialTicket(
        ticket_id=ticket.id,
        usuario_id=current_user.id,
        accion="revisado",
        descripcion="Ticket marcado como revisado",
        cambios={},
    )
    db.add(historial_entry)
    db.commit()

    await sse_publish("tickets:badge", {"hint": "reload"})

    return {"ok": True}


# ── CRUD de tickets ──────────────────────────────────────────────


# ponytail: tickets.crear stays unenforced here on purpose — enforcing it
# would lock out exactly the non-technical reporters this change exists to
# serve (seeded at migration 20260316t1:26-32, checked by no endpoint today).
# The correct fix is to seed the permission to every role FIRST, then
# enforce — a separate change with its own blast radius, not this one.
@router.post("/tickets", response_model=TicketResponse, status_code=201)
async def crear_ticket(
    ticket_data: TicketCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    triage_provider: LlmProvider = Depends(get_triage_provider),
) -> TicketResponse:
    """
    Crea un nuevo ticket.

    Cualquier usuario logueado puede crear tickets. `sector_id`/`tipo_ticket_id`
    son opcionales: si se omiten, el ticket se crea en la Bandeja de entrada
    (sector INBOX, tipo SIN_CLASIFICAR) sembrada por la migración de PR 3.
    `titulo` se deriva de `texto` cuando no se envía explícitamente; `texto`
    se persiste una única vez en `texto_original` y nunca vuelve a escribirse.
    """

    # Validar/derivar sector
    if ticket_data.sector_id is not None:
        sector = db.query(Sector).filter(Sector.id == ticket_data.sector_id).first()
        if not sector:
            raise HTTPException(status_code=404, detail=f"Sector {ticket_data.sector_id} no encontrado")
    else:
        sector = db.query(Sector).filter(Sector.codigo == INBOX_SECTOR_CODIGO).first()
        if not sector:
            raise HTTPException(status_code=400, detail="No hay sector de Bandeja de entrada configurado")

    if not sector.activo:
        raise HTTPException(status_code=400, detail=f"Sector {sector.nombre} está inactivo")

    # Validar/derivar tipo de ticket
    if ticket_data.tipo_ticket_id is not None:
        tipo_ticket = (
            db.query(TipoTicket)
            .filter(TipoTicket.id == ticket_data.tipo_ticket_id, TipoTicket.sector_id == sector.id)
            .first()
        )
        if not tipo_ticket:
            raise HTTPException(
                status_code=404,
                detail=f"Tipo de ticket {ticket_data.tipo_ticket_id} no encontrado para sector {sector.codigo}",
            )
    elif ticket_data.sector_id is None:
        # True single-box path: neither sector_id nor tipo_ticket_id was
        # sent, so fall back to the seeded Inbox tipo.
        tipo_ticket = (
            db.query(TipoTicket)
            .filter(TipoTicket.codigo == INBOX_TIPO_CODIGO, TipoTicket.sector_id == sector.id)
            .first()
        )
        if not tipo_ticket:
            raise HTTPException(status_code=400, detail="No hay tipo de ticket 'Sin clasificar' configurado")
    else:
        # An explicit sector_id was sent for a non-Inbox sector, but
        # tipo_ticket_id was not — the SIN_CLASIFICAR fallback only exists
        # inside the Inbox sector, so silently searching for it here would
        # produce a misleading "not configured" error. Say what's missing.
        raise HTTPException(
            status_code=422,
            detail=f"tipo_ticket_id es requerido al especificar sector_id (sector {sector.codigo})",
        )

    # Obtener workflow (del tipo o default del sector)
    workflow = tipo_ticket.workflow if tipo_ticket.workflow_id else None
    if not workflow:
        workflow = (
            db.query(Workflow)
            .filter(Workflow.sector_id == sector.id, Workflow.es_default == True, Workflow.activo == True)
            .first()
        )

    if not workflow:
        raise HTTPException(status_code=400, detail=f"No hay workflow configurado para sector {sector.codigo}")

    # Obtener estado inicial del workflow
    estado_inicial = (
        db.query(EstadoTicket).filter(EstadoTicket.workflow_id == workflow.id, EstadoTicket.es_inicial == True).first()
    )

    if not estado_inicial:
        raise HTTPException(status_code=400, detail=f"Workflow {workflow.nombre} no tiene estado inicial definido")

    # Crear ticket — titulo explícito gana; si no se envió, se deriva de texto
    # (el validador de TicketCreate garantiza que al menos uno esté presente).
    titulo = ticket_data.titulo or _derivar_titulo(ticket_data.texto)

    # texto_original stores the verbatim receipt, but nothing renders that
    # column in the UI yet — without this fallback, a long single-box texto
    # (titulo truncated to ~80 chars, descripcion empty) would be
    # effectively invisible to the user after creation. descripcion stays
    # editable afterwards (unlike texto_original); an explicit descripcion
    # always wins.
    # ponytail: descripcion and texto_original both start from the same
    # value here but diverge on the first PATCH (descripcion is editable,
    # texto_original never is) — once a UI surfaces texto_original
    # directly, this fallback becomes redundant and should be reconsidered.
    descripcion = ticket_data.descripcion or ticket_data.texto

    nuevo_ticket = Ticket(
        titulo=titulo,
        descripcion=descripcion,
        prioridad=ticket_data.prioridad,
        sector_id=sector.id,
        tipo_ticket_id=tipo_ticket.id,
        estado_id=estado_inicial.id,
        creador_id=current_user.id,
        campos_metadata=ticket_data.metadata,
        texto_original=ticket_data.texto,
    )

    db.add(nuevo_ticket)
    db.flush()

    # Historial entry for creation
    historial_entry = HistorialTicket(
        ticket_id=nuevo_ticket.id,
        usuario_id=current_user.id,
        accion="created",
        descripcion=f"Ticket creado en sector {sector.nombre}",
        estado_nuevo_id=estado_inicial.id,
        cambios={},
    )
    db.add(historial_entry)

    db.commit()
    db.refresh(nuevo_ticket)

    # AI triage (tickets-ai-triage PR 4a): scheduled AFTER commit, never
    # awaited — the request's `db` session is closed by the time
    # BackgroundTasks runs, so `run_triage` opens its own (design §6).
    # Only when there's free text to classify — the legacy titulo-only path
    # (review finding) leaves texto_original NULL, so scheduling it there
    # would just open a DB session to log a no-op warning on every normal
    # advanced-form submission.
    if ticket_data.texto:
        background_tasks.add_task(run_triage, nuevo_ticket.id, triage_provider)

    await sse_publish("tickets:changed", {"hint": "reload"})
    await sse_publish("tickets:badge", {"hint": "reload"})

    return nuevo_ticket


@router.get("/tickets", response_model=TicketListPaginatedResponse)
def listar_tickets(
    sector_id: Optional[int] = Query(None, description="Filtrar por sector"),
    estado_id: Optional[int] = Query(None, description="Filtrar por estado"),
    asignado_a_id: Optional[int] = Query(None, description="Filtrar por usuario asignado"),
    creador_id: Optional[int] = Query(None, description="Filtrar por creador"),
    prioridad: Optional[PrioridadTicket] = Query(None, description="Filtrar por prioridad"),
    urgencia: Optional[UrgenciaFiltro] = Query(
        None, description="Filtrar por urgencia (usado por el 'load more' del tablero)"
    ),
    esta_cerrado: Optional[bool] = Query(None, description="Filtrar por cerrado/abierto"),
    busqueda: Optional[str] = Query(None, description="Buscar en título"),
    order_by: TicketOrderBy = Query(TicketOrderBy.CREATED_AT, description="Campo de orden"),
    order_dir: TicketOrderDir = Query(TicketOrderDir.DESC, description="Dirección de orden"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TicketListPaginatedResponse:
    """
    Lista tickets con filtros opcionales y paginación completa.

    - Sin tickets.ver → solo ve tickets que creó
    - Con tickets.ver → ve tickets de sus sectores asignados + los que creó
    - Con tickets.admin → ve todos los tickets
    """
    puede_ver_sector = _tiene_permiso(db, current_user, "tickets.ver")
    es_admin = _tiene_permiso(db, current_user, "tickets.admin")

    query = db.query(Ticket)

    if es_admin:
        # Admin ve todo
        pass
    elif puede_ver_sector:
        # Ve tickets de sus sectores + los que creó
        from sqlalchemy import or_

        mis_sectores = (
            db.query(SectorUsuario.sector_id)
            .filter(SectorUsuario.usuario_id == current_user.id, SectorUsuario.activo.is_(True))
            .scalar_subquery()
        )
        query = query.filter(
            or_(
                Ticket.sector_id.in_(mis_sectores),
                Ticket.creador_id == current_user.id,
            )
        )
    else:
        # Solo ve sus propios tickets
        query = query.filter(Ticket.creador_id == current_user.id)

    # Aplicar filtros
    if sector_id:
        query = query.filter(Ticket.sector_id == sector_id)

    if estado_id:
        query = query.filter(Ticket.estado_id == estado_id)

    if prioridad:
        query = query.filter(Ticket.prioridad == prioridad)

    if urgencia:
        if urgencia == UrgenciaFiltro.SIN_CLASIFICAR:
            query = query.filter(Ticket.urgencia.is_(None))
        else:
            query = query.filter(Ticket.urgencia == urgencia.value)

    if creador_id:
        query = query.filter(Ticket.creador_id == creador_id)

    if asignado_a_id:
        query = query.join(AsignacionTicket).filter(
            AsignacionTicket.asignado_a_id == asignado_a_id,
            AsignacionTicket.fecha_finalizacion.is_(None),
        )

    if esta_cerrado is not None:
        if not estado_id:
            query = query.join(EstadoTicket).filter(EstadoTicket.es_final == esta_cerrado)

    if busqueda:
        query = query.filter(Ticket.titulo.ilike(f"%{busqueda}%"))

    # Total count
    from sqlalchemy import func

    total = query.with_entities(func.count(Ticket.id)).scalar() or 0

    # order_by/order_dir are Query enums (tickets-ai-triage PR 5a) — an
    # unknown value 422s before FastAPI even calls this function, never
    # reaching SQL. Default preserves prior behavior (created_at DESC).
    query = _aplicar_orden(query, order_by, order_dir)

    # Paginación
    offset = (page - 1) * page_size
    tickets = query.offset(offset).limit(page_size).all()

    pages = math.ceil(total / page_size) if page_size > 0 else 0

    return TicketListPaginatedResponse(
        items=tickets,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/tickets/{ticket_id}", response_model=TicketResponse)
def obtener_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TicketResponse:
    """
    Obtiene un ticket por ID con todas sus relaciones cargadas.

    - Usuarios con tickets.ver → acceso a cualquier ticket
    - Creador del ticket → acceso a su ticket
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()

    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    _check_acceso_ticket(db, current_user, ticket)

    return ticket


@router.patch("/tickets/{ticket_id}", response_model=TicketResponse)
async def actualizar_ticket(
    ticket_id: int,
    ticket_data: TicketUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TicketResponse:
    """
    Actualiza campos de un ticket.

    - Creador puede editar su propio ticket
    - Usuarios con tickets.gestionar pueden editar cualquier ticket
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()

    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    es_creador = ticket.creador_id == current_user.id
    puede_gestionar = _tiene_permiso(db, current_user, "tickets.gestionar")
    if not es_creador and not puede_gestionar:
        raise HTTPException(status_code=403, detail="No tenés acceso a este ticket")

    # Registrar cambios en historial
    cambios_realizados = {}

    if ticket_data.titulo is not None and ticket_data.titulo != ticket.titulo:
        cambios_realizados["titulo"] = {"valor_anterior": ticket.titulo, "valor_nuevo": ticket_data.titulo}
        ticket.titulo = ticket_data.titulo

    if ticket_data.descripcion is not None and ticket_data.descripcion != ticket.descripcion:
        cambios_realizados["descripcion"] = {
            "valor_anterior": ticket.descripcion,
            "valor_nuevo": ticket_data.descripcion,
        }
        ticket.descripcion = ticket_data.descripcion

    if ticket_data.prioridad is not None and ticket_data.prioridad != ticket.prioridad:
        cambios_realizados["prioridad"] = {
            "valor_anterior": ticket.prioridad.value,
            "valor_nuevo": ticket_data.prioridad.value,
        }
        ticket.prioridad = ticket_data.prioridad

    if ticket_data.metadata is not None:
        for key, value in ticket_data.metadata.items():
            if key not in ticket.campos_metadata or ticket.campos_metadata[key] != value:
                cambios_realizados[f"metadata.{key}"] = {
                    "valor_anterior": ticket.campos_metadata.get(key),
                    "valor_nuevo": value,
                }
        ticket.campos_metadata.update(ticket_data.metadata)

    # `urgencia` uses `model_fields_set`, not `is not None` like the fields
    # above: dropping a card on the board's "Sin clasificar" urgency column
    # sends `urgencia: null` EXPLICITLY, and that must actually clear the
    # field rather than being indistinguishable from "not sent".
    if "urgencia" in ticket_data.model_fields_set and ticket_data.urgencia != ticket.urgencia:
        cambios_realizados["urgencia"] = {
            "valor_anterior": ticket.urgencia,
            "valor_nuevo": ticket_data.urgencia,
        }
        ticket.urgencia = ticket_data.urgencia
        if ticket_data.urgencia is None:
            # Clearing urgencia must clear its provenance too — a stale
            # `urgencia_origen` pointing at a value that no longer exists
            # would violate "Provenance Is Always Visible" by making it
            # visible AND false.
            ticket.urgencia_origen = None
        elif ticket_data.urgencia_origen is not None:
            ticket.urgencia_origen = ticket_data.urgencia_origen

    if cambios_realizados:
        historial_entry = HistorialTicket(
            ticket_id=ticket.id,
            usuario_id=current_user.id,
            accion="metadata_updated",
            descripcion="Actualización de campos del ticket",
            cambios=cambios_realizados,
        )
        db.add(historial_entry)

    db.commit()
    db.refresh(ticket)

    await sse_publish("tickets:changed", {"hint": "reload"})

    return ticket


@router.post("/tickets/{ticket_id}/transicion", response_model=TicketResponse)
async def cambiar_estado_ticket(
    ticket_id: int,
    transicion_data: TransicionRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TicketResponse:
    """
    Cambia el estado de un ticket siguiendo las transiciones del workflow.

    Requiere: tickets.gestionar
    """
    _check_permiso(db, current_user, "tickets.gestionar")

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()

    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    nuevo_estado = db.query(EstadoTicket).filter(EstadoTicket.id == transicion_data.nuevo_estado_id).first()

    if not nuevo_estado:
        raise HTTPException(status_code=404, detail=f"Estado {transicion_data.nuevo_estado_id} no encontrado")

    if ticket.estado.workflow_id != nuevo_estado.workflow_id:
        raise HTTPException(status_code=400, detail="El nuevo estado no pertenece al workflow del ticket")

    workflow_service = WorkflowService(db)
    resultado = workflow_service.can_transition(ticket, nuevo_estado.id, current_user)

    if not resultado.permitida:
        # TICKETS_WORKFLOW_ENFORCE=False is a rollback lever for the missing-edge
        # case ONLY — a data gap in the configured transition graph. It must
        # NEVER bypass authorization (requiere_permiso/solo_asignado/solo_creador)
        # or the same-state idempotency guard: those reject regardless of the flag.
        es_bypasseable = resultado.motivo == MotivoRechazoTransicion.SIN_ARISTA
        if not settings.TICKETS_WORKFLOW_ENFORCE and es_bypasseable:
            logger.warning(
                f"Transición no permitida para ticket #{ticket.id} "
                f"({ticket.estado.nombre} -> {nuevo_estado.nombre}) permitida igual: "
                f"TICKETS_WORKFLOW_ENFORCE=False (motivo: {resultado.mensaje})"
            )
        else:
            raise HTTPException(status_code=409, detail=resultado.mensaje)

    estado_anterior = ticket.estado
    ticket.estado_id = nuevo_estado.id

    if nuevo_estado.es_final:
        ticket.closed_at = datetime.now(UTC)

    if transicion_data.metadata:
        ticket.campos_metadata.update(transicion_data.metadata)

    historial_entry = HistorialTicket(
        ticket_id=ticket.id,
        usuario_id=current_user.id,
        accion="estado_changed",
        descripcion=f"Estado cambiado de {estado_anterior.nombre} a {nuevo_estado.nombre}",
        estado_anterior_id=estado_anterior.id,
        estado_nuevo_id=nuevo_estado.id,
        cambios={"comentario": transicion_data.comentario} if transicion_data.comentario else {},
    )
    db.add(historial_entry)

    # The comment is only attached after validation passes, so a rejected
    # transition never leaves a comment attached to a rolled-back session.
    if transicion_data.comentario:
        comentario = ComentarioTicket(
            ticket_id=ticket.id,
            usuario_id=current_user.id,
            contenido=transicion_data.comentario,
            es_interno=False,
        )
        db.add(comentario)

    db.commit()
    db.refresh(ticket)

    await sse_publish("tickets:changed", {"hint": "reload"})
    await sse_publish("tickets:badge", {"hint": "reload"})

    return ticket


@router.post("/tickets/{ticket_id}/asignar", response_model=TicketResponse)
async def asignar_ticket(
    ticket_id: int,
    asignacion_data: AsignarTicketRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TicketResponse:
    """
    Asigna un ticket a un usuario.

    Requiere: tickets.gestionar
    """
    _check_permiso(db, current_user, "tickets.gestionar")

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()

    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    usuario_asignar = db.query(Usuario).filter(Usuario.id == asignacion_data.usuario_id).first()
    if not usuario_asignar:
        raise HTTPException(status_code=404, detail=f"Usuario {asignacion_data.usuario_id} no encontrado")

    asignacion_actual = ticket.asignacion_actual
    if asignacion_actual:
        asignacion_actual.fecha_finalizacion = datetime.now(UTC)

    nueva_asignacion = AsignacionTicket(
        ticket_id=ticket.id,
        asignado_a_id=asignacion_data.usuario_id,
        asignado_por_id=current_user.id,
        tipo=TipoAsignacion.MANUAL,
        motivo=asignacion_data.motivo,
    )
    db.add(nueva_asignacion)

    historial_entry = HistorialTicket(
        ticket_id=ticket.id,
        usuario_id=current_user.id,
        accion="asignado",
        descripcion=f"Ticket asignado a {usuario_asignar.nombre}",
        cambios={
            "asignado_a": {
                "valor_anterior": asignacion_actual.asignado_a.nombre if asignacion_actual else None,
                "valor_nuevo": usuario_asignar.nombre,
            },
            "motivo": asignacion_data.motivo,
        },
    )
    db.add(historial_entry)

    db.commit()
    db.refresh(ticket)

    await sse_publish("tickets:changed", {"hint": "reload"})
    await sse_publish("tickets:badge", {"hint": "reload"})

    return ticket


# ── Comentarios ──────────────────────────────────────────────────


@router.post("/tickets/{ticket_id}/comentarios", response_model=ComentarioResponse, status_code=201)
async def agregar_comentario(
    ticket_id: int,
    comentario_data: ComentarioCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ComentarioResponse:
    """
    Agrega un comentario a un ticket.

    - Creador puede comentar en su propio ticket (solo comentarios públicos)
    - Usuarios con tickets.ver pueden comentar en cualquier ticket
    - Comentarios internos requieren tickets.gestionar
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()

    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    _check_acceso_ticket(db, current_user, ticket)

    # Solo gestores pueden crear comentarios internos
    if comentario_data.es_interno and not _tiene_permiso(db, current_user, "tickets.gestionar"):
        raise HTTPException(status_code=403, detail="Solo gestores pueden crear comentarios internos")

    nuevo_comentario = ComentarioTicket(
        ticket_id=ticket.id,
        usuario_id=current_user.id,
        contenido=comentario_data.contenido,
        es_interno=comentario_data.es_interno,
    )

    db.add(nuevo_comentario)

    historial_entry = HistorialTicket(
        ticket_id=ticket.id,
        usuario_id=current_user.id,
        accion="comentado",
        descripcion=f"Comentario {'interno' if comentario_data.es_interno else 'público'} agregado",
        cambios={},
    )
    db.add(historial_entry)

    db.commit()
    db.refresh(nuevo_comentario)

    await sse_publish("tickets:changed", {"hint": "reload"})
    await sse_publish("tickets:badge", {"hint": "reload"})

    return nuevo_comentario


@router.get("/tickets/{ticket_id}/comentarios", response_model=List[ComentarioResponse])
def listar_comentarios(
    ticket_id: int,
    incluir_internos: bool = Query(True, description="Incluir comentarios internos"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[ComentarioResponse]:
    """
    Lista los comentarios de un ticket.

    - Creador ve solo comentarios públicos de su ticket
    - Usuarios con tickets.ver ven todos (internos según parámetro)
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()

    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    _check_acceso_ticket(db, current_user, ticket)

    query = db.query(ComentarioTicket).filter(ComentarioTicket.ticket_id == ticket_id)

    # Creadores sin tickets.gestionar nunca ven comentarios internos
    puede_ver_internos = _tiene_permiso(db, current_user, "tickets.gestionar")
    if not incluir_internos or not puede_ver_internos:
        query = query.filter(ComentarioTicket.es_interno == False)

    comentarios = query.order_by(ComentarioTicket.created_at.asc()).all()

    return comentarios


# ── Historial ────────────────────────────────────────────────────


@router.get("/tickets/{ticket_id}/historial", response_model=List[HistorialResponse])
def obtener_historial(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[HistorialResponse]:
    """
    Obtiene el historial completo de cambios de un ticket.

    - Creador puede ver historial de su ticket
    - Usuarios con tickets.ver pueden ver historial de cualquier ticket
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()

    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    _check_acceso_ticket(db, current_user, ticket)

    historial = (
        db.query(HistorialTicket)
        .filter(HistorialTicket.ticket_id == ticket_id)
        .order_by(HistorialTicket.fecha.desc())
        .all()
    )

    return historial


# ── Adjuntos (file upload/download/delete) ───────────────────────


@router.post("/tickets/{ticket_id}/adjuntos", response_model=AdjuntoResponse, status_code=201)
async def subir_adjunto(
    ticket_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> AdjuntoResponse:
    """
    Sube un archivo adjunto a un ticket.

    MIME types permitidos: imágenes, PDF, documentos Office.
    Tamaño máximo: TICKETS_MAX_FILE_SIZE_MB (default 5MB).

    Cualquier usuario logueado puede subir adjuntos a sus propios tickets.
    Usuarios con tickets.ver pueden subir a cualquier ticket.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    _check_acceso_ticket(db, current_user, ticket)

    # Validar MIME type
    if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de archivo no permitido: {file.content_type}",
        )

    # Leer archivo
    content = await file.read()
    max_bytes = settings.TICKETS_MAX_FILE_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Archivo demasiado grande. Máximo: {settings.TICKETS_MAX_FILE_SIZE_MB}MB",
        )

    # Guardar en disco: uploads/tickets/{ticket_id}/{uuid}_{filename}
    upload_dir = os.path.join(settings.TICKETS_UPLOADS_DIR, str(ticket_id))
    os.makedirs(upload_dir, exist_ok=True)

    safe_filename = file.filename or "archivo"
    stored_name = f"{uuid.uuid4().hex}_{safe_filename}"
    full_path = os.path.join(upload_dir, stored_name)

    with open(full_path, "wb") as f:
        f.write(content)

    # Guardar en DB (path relativo)
    rel_path = os.path.join(str(ticket_id), stored_name)
    adjunto = AdjuntoTicket(
        ticket_id=ticket_id,
        nombre_archivo=safe_filename,
        path_archivo=rel_path,
        mime_type=file.content_type,
        tamano_bytes=len(content),
        subido_por_id=current_user.id,
    )
    db.add(adjunto)
    db.commit()
    db.refresh(adjunto)

    await sse_publish("tickets:changed", {"hint": "reload"})

    return adjunto


@router.get("/tickets/{ticket_id}/adjuntos", response_model=List[AdjuntoResponse])
def listar_adjuntos(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[AdjuntoResponse]:
    """
    Lista los adjuntos de un ticket.

    - Creador puede ver adjuntos de su ticket
    - Usuarios con tickets.ver pueden ver adjuntos de cualquier ticket
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} no encontrado")

    _check_acceso_ticket(db, current_user, ticket)

    adjuntos = (
        db.query(AdjuntoTicket)
        .filter(AdjuntoTicket.ticket_id == ticket_id)
        .order_by(AdjuntoTicket.created_at.asc())
        .all()
    )

    return adjuntos


@router.get("/tickets/{ticket_id}/adjuntos/{adjunto_id}/descargar")
def descargar_adjunto(
    ticket_id: int,
    adjunto_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> FileResponse:
    """
    Descarga un adjunto de ticket. Auth-gated (no StaticFiles).

    Requiere: tickets.ver
    """
    _check_permiso(db, current_user, "tickets.ver")

    adjunto = (
        db.query(AdjuntoTicket).filter(AdjuntoTicket.id == adjunto_id, AdjuntoTicket.ticket_id == ticket_id).first()
    )
    if not adjunto:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")

    full_path = os.path.join(settings.TICKETS_UPLOADS_DIR, adjunto.path_archivo)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado en disco")

    return FileResponse(
        path=full_path,
        filename=adjunto.nombre_archivo,
        media_type=adjunto.mime_type or "application/octet-stream",
    )


@router.delete("/tickets/{ticket_id}/adjuntos/{adjunto_id}", status_code=204)
async def eliminar_adjunto(
    ticket_id: int,
    adjunto_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """
    Elimina un adjunto de ticket (archivo + registro).

    Requiere: tickets.gestionar
    """
    _check_permiso(db, current_user, "tickets.gestionar")

    adjunto = (
        db.query(AdjuntoTicket).filter(AdjuntoTicket.id == adjunto_id, AdjuntoTicket.ticket_id == ticket_id).first()
    )
    if not adjunto:
        raise HTTPException(status_code=404, detail="Adjunto no encontrado")

    # Eliminar archivo de disco
    full_path = os.path.join(settings.TICKETS_UPLOADS_DIR, adjunto.path_archivo)
    if os.path.exists(full_path):
        os.remove(full_path)

    db.delete(adjunto)
    db.commit()

    await sse_publish("tickets:changed", {"hint": "reload"})
