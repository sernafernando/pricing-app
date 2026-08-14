from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import List, Literal, Optional, Dict, Any
from datetime import datetime
from app.tickets.models.ticket import PrioridadTicket

# Mirrors the CHECK constraint on `tickets.urgencia` (`ck_tickets_urgencia`
# — `models/ticket.py`). A closed vocabulary here, not a bare `str`, so a
# bad value 422s cleanly instead of reaching `db.commit()` and surfacing as
# an unhandled `IntegrityError` (500) — the same defense-in-depth this
# change already applies elsewhere (`CAMPOS_CONFIRMABLES` in
# confirmacion_service).
UrgenciaValor = Literal["baja", "normal", "alta", "inmediata"]


class UsuarioSimple(BaseModel):
    """Usuario simplificado para responses"""

    id: int
    nombre: str
    email: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class EstadoSimple(BaseModel):
    """Estado simplificado para responses"""

    id: int
    codigo: str
    nombre: str
    color: Optional[str] = None
    es_final: bool

    model_config = ConfigDict(from_attributes=True)


class SectorSimple(BaseModel):
    """Sector simplificado para responses"""

    id: int
    codigo: str
    nombre: str
    color: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TipoTicketSimple(BaseModel):
    """Tipo de ticket simplificado para responses"""

    id: int
    codigo: str
    nombre: str

    model_config = ConfigDict(from_attributes=True)


class TipoTicketResponse(BaseModel):
    """Tipo de ticket con schema_campos para formulario dinámico"""

    id: int
    codigo: str
    nombre: str
    descripcion: Optional[str] = None
    icono: Optional[str] = None
    color: Optional[str] = None
    sector_id: int
    workflow_id: Optional[int] = None
    schema_campos: Dict[str, Any] = {}

    model_config = ConfigDict(from_attributes=True)


class TipoTicketCreate(BaseModel):
    """Schema para crear un tipo de ticket"""

    codigo: str = Field(..., min_length=1, max_length=50, description="Código único dentro del sector")
    nombre: str = Field(..., min_length=1, max_length=100, description="Nombre visible")
    descripcion: Optional[str] = None
    icono: Optional[str] = None
    color: Optional[str] = None
    workflow_id: Optional[int] = None
    schema_campos: Dict[str, Any] = Field(default_factory=dict, description="Schema de campos dinámicos")


class TipoTicketUpdate(BaseModel):
    """Schema para actualizar un tipo de ticket"""

    nombre: Optional[str] = Field(default=None, max_length=100)
    descripcion: Optional[str] = None
    icono: Optional[str] = None
    color: Optional[str] = None
    workflow_id: Optional[int] = None
    schema_campos: Optional[Dict[str, Any]] = None


class AsignacionSimple(BaseModel):
    """Asignación simplificada para responses"""

    id: int
    asignado_a: UsuarioSimple
    fecha_asignacion: datetime
    esta_activa: bool

    model_config = ConfigDict(from_attributes=True)


class TicketBase(BaseModel):
    """Schema base para Ticket"""

    titulo: str = Field(..., min_length=5, max_length=255, description="Título del ticket")
    descripcion: Optional[str] = Field(default=None, description="Descripción detallada")
    prioridad: PrioridadTicket = Field(default=PrioridadTicket.MEDIA, description="Prioridad del ticket")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Campos dinámicos según tipo de ticket",
        alias="campos_metadata",
        validation_alias="campos_metadata",
        serialization_alias="metadata",
    )

    model_config = ConfigDict(populate_by_name=True)


class TicketCreate(TicketBase):
    """Schema para crear un Ticket.

    Single-box intake (tickets-ai-triage PR 3): `sector_id`/`tipo_ticket_id`
    are optional and default to the seeded Inbox pair (Sector INBOX /
    TipoTicket SIN_CLASIFICAR) when omitted — explicit values still win.
    `titulo` is optional too; when not sent, the endpoint derives it from
    `texto` (first ~80 chars). `texto` is persisted verbatim once, in
    `Ticket.texto_original`, and is never part of `TicketUpdate`.
    """

    sector_id: Optional[int] = Field(default=None, description="ID del sector (default: Bandeja de entrada)")
    tipo_ticket_id: Optional[int] = Field(default=None, description="ID del tipo de ticket (default: Sin clasificar)")
    titulo: Optional[str] = Field(
        default=None, min_length=5, max_length=255, description="Título; si se omite, se deriva de texto"
    )
    texto: Optional[str] = Field(
        default=None,
        description="Texto libre del reporte. Se guarda tal cual en texto_original y, si no se envía "
        "un título explícito, se usa para derivarlo.",
    )

    @field_validator("texto")
    @classmethod
    def _texto_no_muy_corto(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v.strip()) < 5:
            raise ValueError("El texto debe tener al menos 5 caracteres")
        return v

    @model_validator(mode="after")
    def _requiere_texto_o_titulo(self) -> "TicketCreate":
        if not self.texto and not self.titulo:
            raise ValueError("Debe indicar texto o título para crear el ticket")
        return self


class TicketUpdate(BaseModel):
    """Schema para actualizar un Ticket"""

    titulo: Optional[str] = Field(default=None, min_length=5, max_length=255)
    descripcion: Optional[str] = None
    prioridad: Optional[PrioridadTicket] = None
    metadata: Optional[Dict[str, Any]] = None

    # tickets-ai-triage PR 5c: manual urgency reclassification, primarily via
    # the board's drag-and-drop (dropping a card on a different URGENCY
    # column). `None` sent EXPLICITLY clears urgencia (the "Sin clasificar"
    # column); the field simply absent leaves it untouched — see
    # `actualizar_ticket`'s `model_fields_set` check, not `is not None`.
    urgencia: Optional[UrgenciaValor] = Field(default=None, description="Urgencia asignada manualmente")
    # This endpoint is the HUMAN write path — any user with ticket access
    # can call it. `"humano"` is the only legal value: accepting
    # `ia_confirmada`/`ia_auto` here would let a human claim AI provenance
    # for a manually-set value. The endpoint derives urgencia_origen itself
    # regardless of what's sent (defense in depth on top of this Literal).
    urgencia_origen: Optional[Literal["humano"]] = Field(
        default=None, description="Siempre 'humano' — este es el camino de escritura humana"
    )


class TicketResponse(TicketBase):
    """Schema de respuesta completo para Ticket"""

    id: int
    sector: SectorSimple
    tipo_ticket: TipoTicketSimple
    estado: EstadoSimple
    creador: UsuarioSimple
    asignado_a: Optional[UsuarioSimple] = None
    asignacion_actual: Optional[AsignacionSimple] = None
    esta_cerrado: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    # tickets-ai-triage PR 4c: AI-inferred fields + provenance (spec's
    # "Provenance Is Always Visible"). All nullable — NULL means unclassified
    # or not yet AI-curated. `*_origen` in ('humano','ia_confirmada','ia_auto').
    severidad: Optional[str] = None
    urgencia: Optional[str] = None
    severidad_origen: Optional[str] = None
    urgencia_origen: Optional[str] = None
    resumen: Optional[str] = None
    titulo_origen: Optional[str] = None
    resumen_origen: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TicketListResponse(BaseModel):
    """Schema de respuesta simplificado para listados"""

    id: int
    titulo: str
    prioridad: PrioridadTicket
    sector: SectorSimple
    tipo_ticket: TipoTicketSimple
    estado: EstadoSimple
    creador: UsuarioSimple
    asignado_a: Optional[UsuarioSimple] = None
    esta_cerrado: bool
    created_at: datetime

    # tickets-ai-triage PR 5b: gap found while wiring the board's "load
    # more" (GET /tickets) — TicketCard needs these to render the same as a
    # board card, and they were only ever serialized on TicketResponse
    # (PR 4c). Free from the ORM: same columns, no query change.
    severidad: Optional[str] = None
    urgencia: Optional[str] = None
    severidad_origen: Optional[str] = None
    urgencia_origen: Optional[str] = None
    resumen: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ComentarioCreate(BaseModel):
    """Schema para crear un comentario"""

    contenido: str = Field(..., min_length=1, max_length=5000)
    es_interno: bool = Field(default=False, description="Si es interno (solo equipo)")


class ComentarioResponse(BaseModel):
    """Schema de respuesta para comentario"""

    id: int
    ticket_id: int
    usuario: UsuarioSimple
    contenido: str
    es_interno: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class HistorialResponse(BaseModel):
    """Schema de respuesta para historial"""

    id: int
    usuario: Optional[UsuarioSimple] = None
    accion: str
    descripcion: Optional[str] = None
    estado_anterior: Optional[EstadoSimple] = None
    estado_nuevo: Optional[EstadoSimple] = None
    cambios: Dict[str, Any]
    fecha: datetime

    model_config = ConfigDict(from_attributes=True)


class TransicionRequest(BaseModel):
    """Schema para solicitar una transición de estado"""

    nuevo_estado_id: int = Field(..., description="ID del nuevo estado")
    comentario: Optional[str] = Field(default=None, description="Comentario sobre la transición")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Metadata adicional a actualizar")


class AsignarTicketRequest(BaseModel):
    """Schema para asignar un ticket"""

    usuario_id: int = Field(..., description="ID del usuario a asignar")
    motivo: Optional[str] = Field(default=None, max_length=500, description="Motivo de la asignación")


class SectorUsuarioCreate(BaseModel):
    """Schema para agregar un usuario a un sector"""

    usuario_id: int = Field(..., description="ID del usuario a agregar al sector")


class SectorUsuarioResponse(BaseModel):
    """Schema de respuesta para usuario de sector"""

    id: int
    sector_id: int
    usuario: UsuarioSimple
    activo: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdjuntoResponse(BaseModel):
    """Schema de respuesta para adjunto de ticket"""

    id: int
    ticket_id: int
    nombre_archivo: str
    mime_type: Optional[str] = None
    tamano_bytes: int
    subido_por: UsuarioSimple
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TicketBadgeCount(BaseModel):
    """Schema de respuesta para badge count + breakdown por categoría."""

    pendientes: int = Field(..., description="Acción requerida = sin_asignar + asignados_a_mi (badge primario)")
    sin_asignar: int = Field(0, description="Tickets abiertos visibles sin asignación activa")
    asignados_a_mi: int = Field(0, description="Tickets abiertos visibles asignados al usuario actual")
    asignados_a_otros: int = Field(0, description="Asignados a otra persona; 0 sin permiso tickets.ver")
    con_actividad_nueva: int = Field(
        0, description="Cross-cutting: actividad nueva desde la última revisión; solapa las demás"
    )
    sin_responder: int = Field(
        0, description="Cross-cutting: último comentario es de otro usuario (pelota en mi cancha)"
    )
    sin_leer: int = Field(
        0, description="Cross-cutting: comentario de otro usuario más reciente que mi última revisión"
    )


class TicketListPaginatedResponse(BaseModel):
    """Schema de respuesta paginada para listado de tickets"""

    items: list[TicketListResponse]
    total: int
    page: int
    page_size: int
    pages: int


class PropuestaResponse(BaseModel):
    """Schema de respuesta para una propuesta de IA (tickets-ai-triage PR 4b)"""

    id: int
    ticket_id: int
    campo: str
    valor_propuesto: Dict[str, Any]
    confianza: Optional[float] = None
    modelo: Optional[str] = None
    estado: str
    # tickets-triage-feedback PR1: set only when estado='corregida' — the
    # human-picked value, distinguishing "corrected" from "ratified"
    # structurally (see PropuestaIA.valor_corregido's own docstring).
    valor_corregido: Optional[str] = None
    confirmado_por_id: Optional[int] = None
    confirmado_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConfirmarRequest(BaseModel):
    """Body opcional de `POST /propuestas/{id}/confirmar` (tickets-triage-
    feedback PR1). `valor_corregido` sólo se acepta para severidad/urgencia
    (`vocabularios.CAMPOS_CORREGIBLES`); repetir el valor propuesto por la
    IA equivale a omitirlo — el confirm se resuelve como ratificación, no
    como corrección (decidido server-side, ver `confirmacion_service.
    _resolver_correccion`)."""

    valor_corregido: Optional[str] = Field(default=None, max_length=20)

    model_config = ConfigDict(extra="forbid")


class ConfirmarBatchRequest(BaseModel):
    """Schema para confirmar múltiples propuestas de IA en un solo request"""

    propuesta_ids: List[int] = Field(..., min_length=1, description="IDs de propuestas pendientes a confirmar")


class TicketCardResponse(BaseModel):
    """Schema de respuesta para una card del tablero (tickets-ai-triage PR 5a).

    Deliberadamente MÁS ANGOSTO que `TicketListResponse` — una card no
    necesita todo lo que necesita una fila de tabla. `propuestas_pendientes`
    no estaba en el pedido original de campos, pero se agregó porque sale
    gratis: una subquery correlacionada dentro de la MISMA query de items,
    sin round-trip ni JOIN adicional (ver `_items_del_board`).
    """

    id: int
    titulo: str
    resumen: Optional[str] = None
    severidad: Optional[str] = None
    urgencia: Optional[str] = None
    severidad_origen: Optional[str] = None
    urgencia_origen: Optional[str] = None
    estado: EstadoSimple
    sector: SectorSimple
    created_at: datetime
    propuestas_pendientes: int = 0

    model_config = ConfigDict(from_attributes=True)


class BoardColumnResponse(BaseModel):
    """Una columna del tablero — ver `BoardResponse`."""

    clave: str
    etiqueta: str
    color: Optional[str] = None
    # Only populated for the synthetic 'inbox' column (fix/tickets-board-scope-y-legacy):
    # the Inbox holding pen has no single `estado_id` to filter "load more"
    # by (it aggregates every estado in the Inbox workflow), so the client
    # needs the Inbox SECTOR's id instead. Every other column keeps using
    # `clave` (a real `estado_id`) for that, same as before.
    sector_id: Optional[int] = None
    total: int
    items: List[TicketCardResponse] = Field(default_factory=list)


class BoardResponse(BaseModel):
    """Respuesta de `GET /tickets/board` (tickets-ai-triage PR 5a).

    Deliberadamente SIN metadata de paginación más allá de `total` por
    columna: el overflow de una columna no tiene su propia paginación, el
    cliente pide más vía `GET /tickets` con un filtro equivalente.
    """

    agrupacion: str
    columnas: List[BoardColumnResponse]
