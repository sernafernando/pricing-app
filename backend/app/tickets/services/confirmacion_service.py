"""Confirmation lifecycle for AI-generated ticket proposals (tickets-ai-triage
PR 4b). The ONLY code path allowed to write `tickets.<campo>` from a
proposal (`run_triage`, PR 4a, only ever INSERTs `estado='pendiente'` rows).

Auto-apply seam (design's "Architecture Decisions" #1): a future
`TICKETS_TRIAGE_AUTO_APPLY=True` branch attaches here by calling
`confirmar()`/`confirmar_batch()` with `usuario` bound to the service user
(`agente-ia`, slice 6) instead of a human — a config flag choosing WHO
confirms, not a different write path. See `_aplicar_confirmacion()`.

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
from app.tickets.models.ticket import Ticket


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


def _aplicar_confirmacion(db: Session, ticket: Ticket, propuesta: PropuestaIA, usuario: Usuario, valor) -> None:
    """Write one proposal's value + provenance + history onto its ticket.
    Shared by `confirmar()`/`confirmar_batch()` — the AUTO-APPLY SEAM: this
    function only needs a real `Usuario` row, human or service user."""
    setattr(ticket, propuesta.campo, valor)
    setattr(ticket, f"{propuesta.campo}_origen", "ia_confirmada")

    db.add(
        HistorialTicket(
            ticket_id=ticket.id,
            usuario_id=usuario.id,
            accion="propuesta_confirmada",
            descripcion=f"Propuesta IA confirmada: {propuesta.campo} = {valor}",
            cambios={"campo": propuesta.campo, "valor_nuevo": valor, "origen": "ia_confirmada"},
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
    valor = propuesta.valor_propuesto["valor"]
    _aplicar_confirmacion(db, ticket, propuesta, usuario, valor)

    propuesta.estado = "confirmada"
    propuesta.confirmado_por_id = usuario.id
    propuesta.confirmado_at = datetime.now(UTC)

    db.commit()
    db.refresh(propuesta)
    return propuesta


def descartar(db: Session, propuesta_id: int, usuario: Usuario) -> PropuestaIA:
    """Discards a pending proposal. Never writes to `tickets` — only the
    proposal's own `estado` changes. See module docstring for the
    never-resurfaces invariant."""
    propuesta = db.query(PropuestaIA).filter(PropuestaIA.id == propuesta_id).first()
    if propuesta is None:
        raise PropuestaNoEncontradaError(propuesta_id)
    if propuesta.estado != "pendiente":
        raise PropuestaNoPendienteError(propuesta_id, propuesta.estado)

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

    try:
        for propuesta in propuestas:
            ticket = tickets_por_id.get(propuesta.ticket_id)
            if ticket is None:
                ticket = db.query(Ticket).filter(Ticket.id == propuesta.ticket_id).first()
                tickets_por_id[propuesta.ticket_id] = ticket
            _aplicar_confirmacion(db, ticket, propuesta, usuario, propuesta.valor_propuesto["valor"])
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
