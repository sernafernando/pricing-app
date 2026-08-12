"""Confirmation lifecycle for AI-generated ticket proposals (tickets-ai-triage
PR 4b, topology flipped by feat/tickets-triage-aplicar-directo). The ONLY
code path allowed to write `tickets.<campo>` from a proposal.

Auto-apply seam (design's "Architecture Decisions" #1, now the DEFAULT):
`TICKETS_TRIAGE_AUTO_APPLY=True` (`triage_service.run_triage`) calls
`_aplicar_confirmacion()` directly with `usuario=None` and
`origen="ia_auto"` — no human in the loop, `confirmado_por_id` stays NULL as
the signal that nobody ratified it. `confirmar()`/`confirmar_batch()` remain
the human path (`origen="ia_confirmada"`) for whatever a low-confidence
field or `TICKETS_TRIAGE_AUTO_APPLY=False` still leaves `pendiente`.

Hard invariant: a `descartada` proposal is NEVER reset to `pendiente` by any
code path here or in `run_triage` — no function assigns `estado='pendiente'`
to an existing row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import List

from sqlalchemy.orm import Session

from app.models.usuario import Usuario
from app.tickets.models.historial_ticket import HistorialTicket
from app.tickets.models.propuesta_ia import PropuestaIA
from app.tickets.models.sector import Sector
from app.tickets.models.ticket import Ticket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, Workflow


class PropuestaNoEncontradaError(Exception):
    """A single confirm/descartar target id does not exist."""

    def __init__(self, propuesta_id: int) -> None:
        self.propuesta_id = propuesta_id
        super().__init__(f"Propuesta {propuesta_id} no encontrada")


class PropuestaNoPendienteError(Exception):
    """A single confirm/descartar target exists but is not `pendiente`."""

    def __init__(self, propuesta_id: int, estado_actual: str) -> None:
        self.propuesta_id = propuesta_id
        self.estado_actual = estado_actual
        super().__init__(f"La propuesta {propuesta_id} no está pendiente (estado actual: {estado_actual})")


class PropuestaBatchInvalidaError(Exception):
    """One or more batch ids do not exist or are not `pendiente` — the whole
    batch is rejected before any write happens (spec: "Batch confirm is one
    atomic operation")."""

    def __init__(self, ids_invalidos: List[int]) -> None:
        self.ids_invalidos = ids_invalidos
        super().__init__(f"Propuestas no encontradas o no pendientes: {ids_invalidos}")


class PropuestaCampoNoPermitidoError(Exception):
    """`propuesta.campo` is outside `CAMPOS_CONFIRMABLES`. Without this
    guard, confirmation is an arbitrary-attribute-write primitive on
    `Ticket` (any column, e.g. `estado_id`) — enforced at the WRITE POINT
    in `_aplicar_confirmacion`, not only where proposals are created, so it
    also covers batch confirms and any future proposal-creation path."""

    def __init__(self, campo: str) -> None:
        self.campo = campo
        super().__init__(f"Campo no permitido para confirmación: '{campo}'")


class PropuestaNoDescartableError(Exception):
    """`campo` was already applied by auto-apply (`estado='confirmada'`,
    `confirmado_por_id IS NULL`) but has no clean "unset" state to revert
    to: `titulo` is a NOT NULL column on `Ticket` (no origen-less default to
    fall back to); `sector`/`tipo_ticket` (really `sector_id`/
    `tipo_ticket_id`, also NOT NULL) have no `_origen` column at all, and
    moving either is a DOMAIN OPERATION with no defined "undo" (see
    `_confirmar_sector`); `metadata_ia` was a JSONB MERGE, so there is no
    record of which keys it added. Discarding those must happen by
    CORRECTING the value directly (PATCH the ticket, or re-run triage/
    reassign sector), never by a blind revert that could destroy an
    unrelated write."""

    def __init__(self, campo: str) -> None:
        self.campo = campo
        super().__init__(
            f"No se puede descartar un valor de '{campo}' ya aplicado por la IA; corregilo directamente en el ticket"
        )


class TicketNoEncontradoError(Exception):
    """The ticket referenced by `propuesta.ticket_id` does not exist. FK
    constraints make this unlikely, not impossible — without this guard,
    `_aplicar_confirmacion` would call `setattr(None, ...)`, an unhandled
    500 instead of a clean 404."""

    def __init__(self, ticket_id: int) -> None:
        self.ticket_id = ticket_id
        super().__init__(f"Ticket {ticket_id} no encontrado")


class PropuestaSectorInvalidoError(Exception):
    """`campo='sector'`'s value is not an active, properly-configured
    sector (no matching `Sector.codigo`, or that sector has no default
    workflow / initial state) — the ticket cannot be moved there."""

    def __init__(self, sector_codigo: str) -> None:
        self.sector_codigo = sector_codigo
        super().__init__(f"Sector '{sector_codigo}' inválido o mal configurado")


class PropuestaTipoSectorInvalidoError(Exception):
    """`campo='tipo_ticket'`'s value does not belong to the ticket's
    CURRENT sector. Ordering guard (§4): confirming a tipo before its
    sector confirmation would set a type from a sector the ticket is not
    in yet — reject rather than write an inconsistent pair. Confirm the
    `sector` proposal first (or send both in the same `confirmar_batch`
    call, which auto-orders them — see `confirmar_batch`)."""

    def __init__(self, tipo_codigo: str, sector_id: int) -> None:
        self.tipo_codigo = tipo_codigo
        self.sector_id = sector_id
        super().__init__(f"Tipo de ticket '{tipo_codigo}' no pertenece al sector actual del ticket ({sector_id})")


class PropuestaSectorDejaTipoHuerfanoError(Exception):
    """Real pre-push review finding, the mirror image of
    `PropuestaTipoSectorInvalidoError`: confirming `sector` ALONE would
    leave `tipo_ticket_id` pointing at a tipo from the OLD sector — the
    same inconsistent pair, entered through the other field.
    `tipo_ticket_id` is NOT NULL, so it cannot simply be cleared. Confirm
    the `tipo_ticket` proposal in the SAME `confirmar_batch` call (it
    auto-orders `sector` first, then fixes `tipo_ticket_id` right after —
    see `confirmar_batch`)."""

    def __init__(self, sector_codigo: str, tipo_ticket_id: int) -> None:
        self.sector_codigo = sector_codigo
        self.tipo_ticket_id = tipo_ticket_id
        super().__init__(
            f"Confirmar sector '{sector_codigo}' dejaría tipo_ticket_id={tipo_ticket_id} huérfano de su sector; "
            "confirmá también la propuesta de tipo_ticket en el mismo lote"
        )


# Fields a confirmed AI proposal is allowed to write onto `Ticket`. Kept in
# sync with `ck_tickets_propuestas_ia_campo` — the Postgres CHECK constraint
# on `tickets_propuestas_ia.campo` (see `PropuestaIA.__table_args__` and
# alembic/versions/20260806_campo_check_ia.py,
# 20260810_sector_tipo_metadata_check_ia.py) — as a second,
# independent enforcement layer: the app rejects an out-of-vocabulary campo
# here, the DB refuses to store one there. A future slice adding another
# confirmable field MUST update BOTH this set AND that constraint's
# vocabulary (plus a new migration), or the two layers drift out of sync.
CAMPOS_CONFIRMABLES = frozenset({"severidad", "urgencia", "titulo", "resumen", "sector", "tipo_ticket", "metadata_ia"})

# Subset of CAMPOS_CONFIRMABLES that `descartar()` can revert to a clean
# "unset" state once already applied by auto-apply: nullable plain columns
# with a matching `<campo>_origen` to clear alongside them. `titulo` is NOT
# NULL (no unset state), `sector`/`tipo_ticket` have no origen column and
# moving them is a domain operation with no defined "undo", and
# `metadata_ia` was a JSONB MERGE — there is no record of which keys it
# added. See `PropuestaNoDescartableError`.
CAMPOS_REVERTIBLES = frozenset({"severidad", "urgencia", "resumen"})


def _estado_inicial_de_workflow(db: Session, workflow_id: int) -> EstadoTicket | None:
    return (
        db.query(EstadoTicket)
        .filter(EstadoTicket.workflow_id == workflow_id, EstadoTicket.es_inicial == True)  # noqa: E712
        .first()
    )


def _workflow_de_tipo_o_default(db: Session, tipo: TipoTicket, sector_id: int) -> Workflow | None:
    """Mirrors `crear_ticket`'s own fallback (`tickets.py`): a tipo's own
    workflow wins; the sector's default workflow only when the tipo has
    none. Real pre-push review finding: `_confirmar_sector` originally
    always used the sector's DEFAULT workflow, but a tipo can point at a
    non-default one — leaving `estado_id` unresolved for that case would
    strand the ticket on the wrong workflow graph."""
    if tipo.workflow_id:
        return tipo.workflow
    return (
        db.query(Workflow)
        .filter(Workflow.sector_id == sector_id, Workflow.es_default == True, Workflow.activo == True)  # noqa: E712
        .first()
    )


def _confirmar_sector(
    db: Session,
    ticket: Ticket,
    usuario: Usuario | None,
    sector_codigo: str,
    *,
    permite_tipo_huerfano: bool = False,
    origen: str = "ia_confirmada",
) -> None:
    """Moving `sector` is a DOMAIN OPERATION, not a column write: the
    ticket's `estado_id` belongs to the OLD sector's workflow graph, so
    leaving it untouched would file the ticket under a foreign column on
    every estado-grouped board and break `WorkflowService.can_transition`
    (it evaluates `ticket.estado_id` against its own workflow's edges).
    Moves both together, atomically, with one history row explaining why
    the state jumped.

    `permite_tipo_huerfano`: real pre-push review finding — confirming
    `sector` ALONE would leave `tipo_ticket_id` pointing at a tipo from the
    OLD sector (NOT NULL, so it can't just be cleared). Rejected unless the
    caller (`confirmar_batch`) is ALSO confirming a `tipo_ticket` proposal
    for this same ticket in the same call, which fixes it right after —
    see `PropuestaSectorDejaTipoHuerfanoError`."""
    sector = db.query(Sector).filter(Sector.codigo == sector_codigo, Sector.activo == True).first()  # noqa: E712
    workflow = (
        db.query(Workflow)
        .filter(Workflow.sector_id == sector.id, Workflow.es_default == True, Workflow.activo == True)
        .first()  # noqa: E712
        if sector
        else None
    )
    estado_inicial = _estado_inicial_de_workflow(db, workflow.id) if workflow else None
    if sector is None or estado_inicial is None:
        raise PropuestaSectorInvalidoError(sector_codigo)

    if not permite_tipo_huerfano:
        tipo_actual = db.query(TipoTicket).filter(TipoTicket.id == ticket.tipo_ticket_id).first()
        if tipo_actual is not None and tipo_actual.sector_id != sector.id:
            raise PropuestaSectorDejaTipoHuerfanoError(sector_codigo, ticket.tipo_ticket_id)

    sector_anterior_id, estado_anterior_id = ticket.sector_id, ticket.estado_id
    ticket.sector_id = sector.id
    ticket.estado_id = estado_inicial.id

    db.add(
        HistorialTicket(
            ticket_id=ticket.id,
            usuario_id=usuario.id if usuario else None,
            accion="propuesta_confirmada",
            descripcion=f"Propuesta IA confirmada: sector = {sector_codigo} (estado inicial '{estado_inicial.nombre}')",
            estado_anterior_id=estado_anterior_id,
            estado_nuevo_id=estado_inicial.id,
            cambios={
                "campo": "sector",
                "valor_nuevo": sector_codigo,
                "sector_anterior_id": sector_anterior_id,
                "sector_nuevo_id": sector.id,
                "estado_anterior_id": estado_anterior_id,
                "estado_nuevo_id": estado_inicial.id,
                "origen": origen,
            },
        )
    )


def _confirmar_tipo_ticket(
    db: Session, ticket: Ticket, usuario: Usuario | None, tipo_codigo: str, *, origen: str = "ia_confirmada"
) -> None:
    """`tipo_ticket` must belong to the ticket's CURRENT `sector_id` — see
    `PropuestaTipoSectorInvalidoError`. Also re-resolves `estado_id` when
    the confirmed tipo's own workflow differs from the ticket's current
    one (real pre-push review finding: `crear_ticket` resolves the
    workflow from the TIPO first, sector default only as fallback — a
    non-default-workflow tipo must not leave the ticket on whatever
    `_confirmar_sector` set)."""
    tipo = (
        db.query(TipoTicket).filter(TipoTicket.codigo == tipo_codigo, TipoTicket.sector_id == ticket.sector_id).first()
    )
    if tipo is None:
        raise PropuestaTipoSectorInvalidoError(tipo_codigo, ticket.sector_id)

    tipo_anterior_id = ticket.tipo_ticket_id
    ticket.tipo_ticket_id = tipo.id

    cambios = {
        "campo": "tipo_ticket",
        "valor_nuevo": tipo_codigo,
        "tipo_anterior_id": tipo_anterior_id,
        "tipo_nuevo_id": tipo.id,
        "origen": origen,
    }

    workflow_destino = _workflow_de_tipo_o_default(db, tipo, ticket.sector_id)
    estado_actual_workflow_id = ticket.estado.workflow_id if ticket.estado else None
    if workflow_destino is not None and workflow_destino.id != estado_actual_workflow_id:
        estado_inicial = _estado_inicial_de_workflow(db, workflow_destino.id)
        if estado_inicial is not None:
            cambios["estado_anterior_id"] = ticket.estado_id
            cambios["estado_nuevo_id"] = estado_inicial.id
            ticket.estado_id = estado_inicial.id

    db.add(
        HistorialTicket(
            ticket_id=ticket.id,
            usuario_id=usuario.id if usuario else None,
            accion="propuesta_confirmada",
            descripcion=f"Propuesta IA confirmada: tipo_ticket = {tipo_codigo}",
            estado_anterior_id=cambios.get("estado_anterior_id"),
            estado_nuevo_id=cambios.get("estado_nuevo_id"),
            cambios=cambios,
        )
    )


def _confirmar_metadata_ia(
    db: Session, ticket: Ticket, usuario: Usuario | None, valor: dict, *, origen: str = "ia_confirmada"
) -> None:
    """`area_probable`/`tamano`/`detalle` land in `campos_metadata` (design:
    a JSONB blob, not new columns) — a MERGE, never an overwrite, since
    `campos_metadata` may already carry values from the advanced form."""
    ticket.campos_metadata = {**(ticket.campos_metadata or {}), **valor}
    db.add(
        HistorialTicket(
            ticket_id=ticket.id,
            usuario_id=usuario.id if usuario else None,
            accion="propuesta_confirmada",
            descripcion="Propuesta IA confirmada: metadata_ia",
            cambios={"campo": "metadata_ia", "valor_nuevo": valor, "origen": origen},
        )
    )


def _aplicar_confirmacion(
    db: Session,
    ticket: Ticket,
    propuesta: PropuestaIA,
    usuario: Usuario | None,
    valor,
    *,
    permite_tipo_huerfano: bool = False,
    origen: str = "ia_confirmada",
) -> None:
    """Write one proposal's value + provenance + history onto its ticket.
    Shared by `confirmar()`/`confirmar_batch()` (human confirms, `usuario`
    always set, `origen="ia_confirmada"`) AND `triage_service.run_triage`'s
    auto-apply branch (`usuario=None`, `origen="ia_auto"`) — the ONE domain
    write path both go through, so sector/tipo_ticket movement and history
    stay identical regardless of who — or what — triggered the write.

    Rejects `propuesta.campo` outside `CAMPOS_CONFIRMABLES` BEFORE any
    write — see `PropuestaCampoNoPermitidoError`. `sector`/`tipo_ticket`/
    `metadata_ia` dispatch to dedicated domain logic; everything else keeps
    the plain column write. `permite_tipo_huerfano` only affects `sector`
    — see `_confirmar_sector`."""
    if propuesta.campo not in CAMPOS_CONFIRMABLES:
        raise PropuestaCampoNoPermitidoError(propuesta.campo)

    if propuesta.campo == "sector":
        _confirmar_sector(db, ticket, usuario, valor, permite_tipo_huerfano=permite_tipo_huerfano, origen=origen)
        return
    if propuesta.campo == "tipo_ticket":
        _confirmar_tipo_ticket(db, ticket, usuario, valor, origen=origen)
        return
    if propuesta.campo == "metadata_ia":
        _confirmar_metadata_ia(db, ticket, usuario, valor, origen=origen)
        return

    setattr(ticket, propuesta.campo, valor)
    setattr(ticket, f"{propuesta.campo}_origen", origen)

    db.add(
        HistorialTicket(
            ticket_id=ticket.id,
            usuario_id=usuario.id if usuario else None,
            accion="propuesta_confirmada",
            descripcion=f"Propuesta IA confirmada: {propuesta.campo} = {valor}",
            cambios={"campo": propuesta.campo, "valor_nuevo": valor, "origen": origen},
        )
    )


def confirmar(db: Session, propuesta_id: int, usuario: Usuario) -> PropuestaIA:
    """Confirms a pending proposal: writes its value + provenance onto the
    ticket, marks the proposal `confirmada`, and logs a `tickets_historial`
    row — all in one transaction."""
    propuesta = db.query(PropuestaIA).filter(PropuestaIA.id == propuesta_id).first()
    if propuesta is None:
        raise PropuestaNoEncontradaError(propuesta_id)
    if propuesta.estado != "pendiente":
        raise PropuestaNoPendienteError(propuesta_id, propuesta.estado)

    ticket = db.query(Ticket).filter(Ticket.id == propuesta.ticket_id).first()
    if ticket is None:
        raise TicketNoEncontradoError(propuesta.ticket_id)
    valor = propuesta.valor_propuesto["valor"]
    _aplicar_confirmacion(db, ticket, propuesta, usuario, valor)

    propuesta.estado = "confirmada"
    propuesta.confirmado_por_id = usuario.id
    propuesta.confirmado_at = datetime.now(UTC)

    db.commit()
    db.refresh(propuesta)
    return propuesta


def descartar(db: Session, propuesta_id: int, usuario: Usuario) -> PropuestaIA:
    """Discards a proposal. Never resurfaces (module docstring's hard
    invariant): a `descartada` row is never reset to `pendiente` by any
    code path.

    Two shapes, since auto-apply (`TICKETS_TRIAGE_AUTO_APPLY=True`) means
    most proposals now arrive already `confirmada`, not `pendiente`:

    - `pendiente`: unchanged from PR 4b — nothing was ever written to
      `tickets`, so discarding only flips the proposal's own `estado`.
    - `confirmada` with `confirmado_por_id IS NULL` (i.e. `ia_auto`, never
      reviewed by a human): the human is REJECTING an already-applied AI
      value — "correct it if wrong" from the UI's own copy. For
      `CAMPOS_REVERTIBLES` (nullable, origen-tracked plain columns) this
      clears the ticket value AND its `<campo>_origen`, mirroring
      `actualizar_ticket`'s own "clearing a value clears its origen too"
      rule — but ONLY when the ticket's CURRENT origen still says
      `ia_auto` (staleness guard: a human may have already overwritten the
      field through a different path since this proposal applied). Every
      other campo (`titulo` is NOT NULL; `sector`/`tipo_ticket` have no
      origen column and moving them has no defined "undo"; `metadata_ia`
      was a JSONB merge with no record of which keys it added) raises
      `PropuestaNoDescartableError` — correct those by editing the ticket
      directly instead.
    - Anything else (human-confirmed `ia_confirmada`, `descartada`,
      `reemplazada`): unchanged, `PropuestaNoPendienteError`.
    """
    propuesta = db.query(PropuestaIA).filter(PropuestaIA.id == propuesta_id).first()
    if propuesta is None:
        raise PropuestaNoEncontradaError(propuesta_id)

    es_ia_auto_sin_revisar = propuesta.estado == "confirmada" and propuesta.confirmado_por_id is None
    if propuesta.estado != "pendiente" and not es_ia_auto_sin_revisar:
        raise PropuestaNoPendienteError(propuesta_id, propuesta.estado)

    if es_ia_auto_sin_revisar:
        if propuesta.campo not in CAMPOS_REVERTIBLES:
            raise PropuestaNoDescartableError(propuesta.campo)
        ticket = db.query(Ticket).filter(Ticket.id == propuesta.ticket_id).first()
        if ticket is None:
            raise TicketNoEncontradoError(propuesta.ticket_id)
        # STALENESS GUARD (real pre-push review finding): this proposal
        # represents the value it applied at auto-apply time — but nothing
        # keeps it in sync if a human later overwrites the SAME field
        # through a different path (`actualizar_ticket`'s PATCH, e.g. a
        # board drag), which never touches `tickets_propuestas_ia` at all.
        # Only clear the ticket when its CURRENT origen still says
        # `ia_auto` — i.e. nothing has changed it since. If a human already
        # corrected it, this proposal is simply stale: mark it `descartada`
        # (below, unconditionally) without touching a ticket value that no
        # longer belongs to it — discarding a stale record must never
        # destroy a newer human correction.
        if getattr(ticket, f"{propuesta.campo}_origen", None) == "ia_auto":
            setattr(ticket, propuesta.campo, None)
            setattr(ticket, f"{propuesta.campo}_origen", None)
            db.add(
                HistorialTicket(
                    ticket_id=ticket.id,
                    usuario_id=usuario.id,
                    accion="propuesta_descartada",
                    descripcion=f"Valor de IA descartado: {propuesta.campo}",
                    cambios={"campo": propuesta.campo, "valor_anterior": propuesta.valor_propuesto.get("valor")},
                )
            )

    propuesta.estado = "descartada"
    propuesta.confirmado_por_id = usuario.id
    propuesta.confirmado_at = datetime.now(UTC)

    db.commit()
    db.refresh(propuesta)
    return propuesta


def confirmar_batch(db: Session, propuesta_ids: List[int], usuario: Usuario) -> List[PropuestaIA]:
    """Confirms N proposals — possibly across several tickets — as ONE
    atomic operation: all succeed or all fail, never a partial batch.

    Ticket writes differ per proposal (different campo/valor/ticket), so
    they can't be one literal `UPDATE...IN`; the proposals' own lifecycle
    fields ARE updated that way below. A single `db.commit()` plus an
    explicit `db.rollback()` on any failure makes the whole call one
    transaction — nothing persists unless everything succeeds.
    """
    if not propuesta_ids:
        return []

    propuestas = (
        db.query(PropuestaIA).filter(PropuestaIA.id.in_(propuesta_ids), PropuestaIA.estado == "pendiente").all()
    )
    encontrados = {p.id for p in propuestas}
    faltantes = sorted(set(propuesta_ids) - encontrados)
    if faltantes:
        raise PropuestaBatchInvalidaError(faltantes)

    ahora = datetime.now(UTC)
    tickets_por_id: dict[int, Ticket] = {}

    # Ordering (§4): a `tipo_ticket` confirmed before its `sector` could set
    # a type from a sector the ticket is not in yet. `confirmar()` (single)
    # REJECTS that via `PropuestaTipoSectorInvalidoError`; a batch instead
    # AUTO-ORDERS — any `sector` proposal always applies before any
    # `tipo_ticket` proposal, so the common case (one triage run proposing
    # both together) confirms cleanly in one call. `sorted` is stable, so
    # every other relative ordering is unaffected.
    propuestas = sorted(propuestas, key=lambda p: 0 if p.campo == "sector" else 1)

    # Real pre-push review finding, the mirror of the ordering above:
    # confirming `sector` alone would leave `tipo_ticket_id` orphaned in the
    # OLD sector. A ticket whose batch ALSO confirms its `tipo_ticket` in
    # this same call is safe — `_confirmar_tipo_ticket` fixes it right
    # after, same transaction — so only THOSE tickets' `sector` proposals
    # get `permite_tipo_huerfano=True`.
    tickets_con_tipo_en_batch = {p.ticket_id for p in propuestas if p.campo == "tipo_ticket"}

    try:
        for propuesta in propuestas:
            ticket = tickets_por_id.get(propuesta.ticket_id)
            if ticket is None:
                ticket = db.query(Ticket).filter(Ticket.id == propuesta.ticket_id).first()
                if ticket is None:
                    raise TicketNoEncontradoError(propuesta.ticket_id)
                tickets_por_id[propuesta.ticket_id] = ticket
            permite_huerfano = propuesta.campo == "sector" and propuesta.ticket_id in tickets_con_tipo_en_batch
            _aplicar_confirmacion(
                db,
                ticket,
                propuesta,
                usuario,
                propuesta.valor_propuesto["valor"],
                permite_tipo_huerfano=permite_huerfano,
            )
            db.flush()

        db.query(PropuestaIA).filter(PropuestaIA.id.in_(encontrados)).update(
            {"estado": "confirmada", "confirmado_por_id": usuario.id, "confirmado_at": ahora},
            synchronize_session=False,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    for propuesta in propuestas:
        db.refresh(propuesta)
    return propuestas
