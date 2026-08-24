"""Ticket -> Vikunja sync service (sdd/tickets-sync-vikunja, PR 2).

Wires the PR 1 client (`app.services.vikunja_client`) and ledger table
(`TicketVikunjaSync`) to two event-driven hooks (`push_ticket`,
`push_attachment`, both scheduled via `BackgroundTasks.add_task` from
`app.tickets.api.endpoints.tickets`) plus a 300s reconcile loop
(`run_vikunja_reconcile_cycle`, registered in `app.main` inside the
`bg_lock_fd` single-worker block).

Kill-switch discipline (mirrors `triage_service.run_triage`'s flag check):
`settings.TICKETS_VIKUNJA_SYNC_ENABLED` is checked as the FIRST statement in
every public entrypoint, BEFORE any `get_background_db()` call. A prior
version of an unrelated flag-gated feature shipped the flag check after the
DB session was already opened; the test suite here (`TestFlagOff*`) exists
specifically to prevent that regression from recurring here.

Duplicate-avoidance ordering (design, "Decision: ordering that makes
duplicates impossible"):

    hook -> flag OFF => return                     (before ANY DB session)
         -> session #1 (short): ensure ledger row exists (INSERT ON CONFLICT
                                 DO NOTHING), then CAS claim
                                 estado IN ('pendiente','error') -> 'enviando'
                                 (no row updated => someone else owns it)
                                 read the ticket into plain scalars
         -> session CLOSED
         -> network: create_task (idempotent=False in the client)
         -> session #2 (short): estado='sincronizado', vikunja_task_id, synced_at

Failure routing on the create call:
    VikunjaPermanentError  -> estado='error', intentos+=1, ultimo_error (truncated)
    VikunjaTransientError  -> estado='ambiguo', then the IMMEDIATE ambiguity
                              check below (this is the duplicate-prevention
                              heart of the change)
    process dies mid-call  -> row stays 'enviando' forever until the 300s
                              loop reclaims it (see `_reclaim_stale_enviando`)

Immediate ambiguity resolution (only place the description marker's match
matters — its lifetime is seconds, never used again once `vikunja_task_id`
is stored):
    wait ~2s, list_tasks(project_id), match tasks created in the last ~120s
    whose description contains `Ticket original #{id} ` (trailing space:
    `#1 ` must not match `#12 `).
        exactly one match -> adopt its id, 'sincronizado'
        zero matches      -> provably safe to create -> create
        >1 matches         -> UNSAFE -> stays 'ambiguo', flagged for
                              notification, NEVER creates

The 300s reconcile loop is a crash backstop ONLY and the rule INVERTS there:
'enviando' older than 10 minutes is reclaimed to 'ambiguo'; an 'ambiguo' row
the loop cannot match to EXACTLY one task stays 'ambiguo' and is flagged for
notification -- it must NEVER create, because outside the immediate window a
"not found" no longer proves non-existence (it could just as well mean
someone edited the description).

Attachments: if the parent ticket's row is not yet 'sincronizado' there is no
Vikunja task to attach to, so the upload is deferred (`adjuntos_pendientes`
set True) and drained by the loop once the ticket lands.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_background_db
from app.services.vikunja_client import (
    VikunjaClient,
    VikunjaPermanentError,
    VikunjaTransientError,
)
from app.tickets.models.adjunto_ticket import AdjuntoTicket
from app.tickets.models.ticket import Ticket
from app.tickets.models.ticket_vikunja_sync import TicketVikunjaSync

logger = logging.getLogger(__name__)

_STALE_ENVIANDO_MINUTES = 10
_AMBIGUOUS_CHECK_DELAY_SECONDS = 2.0
_AMBIGUOUS_MATCH_WINDOW_SECONDS = 120
_ULTIMO_ERROR_MAX_CHARS = 500


def _client() -> VikunjaClient:
    return VikunjaClient(base_url=settings.VIKUNJA_BASE_URL or "", token=settings.VIKUNJA_TOKEN or "")


def _marker(ticket_id: int) -> str:
    """The description marker used ONLY by the immediate/loop ambiguity
    checks below. Trailing space is load-bearing: without it `#1` would
    match `#12`'s task too."""
    return f"Ticket original #{ticket_id} "


def _build_description(ticket_id: int, descripcion: Optional[str]) -> str:
    marker = _marker(ticket_id)
    body = descripcion or ""
    return f"{marker}\n\n{body}"


def _parse_vikunja_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _insert_sync_row_if_absent(db: Session, ticket_id: int) -> None:
    """Portable INSERT ... ON CONFLICT DO NOTHING (production runs Postgres,
    CI runs SQLite; both dialects need their own `insert()` construct)."""
    dialect = db.bind.dialect.name if db.bind is not None else ""
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert

    stmt = dialect_insert(TicketVikunjaSync).values(ticket_id=ticket_id)
    stmt = stmt.on_conflict_do_nothing(index_elements=["ticket_id"])
    db.execute(stmt)


def _claim_ticket(ticket_id: int) -> Optional[Dict[str, Any]]:
    """Ensures a ledger row exists, then CAS-claims it
    (`pendiente`|`error` -> `enviando`). Returns the ticket's plain scalars
    on success; `None` if this call did NOT win the claim (already owned,
    already synced, or ambiguous elsewhere) — the caller must return
    immediately in that case."""
    with get_background_db() as db:
        _insert_sync_row_if_absent(db, ticket_id)

        result = db.execute(
            update(TicketVikunjaSync)
            .where(
                TicketVikunjaSync.ticket_id == ticket_id,
                TicketVikunjaSync.estado.in_(["pendiente", "error"]),
            )
            .values(estado="enviando", claimed_at=func.now())
        )
        if result.rowcount != 1:
            return None

        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if ticket is None:
            return None
        return {"id": ticket.id, "titulo": ticket.titulo, "descripcion": ticket.descripcion}


def _mark_synced(ticket_id: int, vikunja_task_id: int) -> None:
    with get_background_db() as db:
        db.execute(
            update(TicketVikunjaSync)
            .where(TicketVikunjaSync.ticket_id == ticket_id)
            .values(estado="sincronizado", vikunja_task_id=vikunja_task_id, synced_at=func.now())
        )


def _mark_error(ticket_id: int, error_message: str) -> None:
    with get_background_db() as db:
        db.execute(
            update(TicketVikunjaSync)
            .where(TicketVikunjaSync.ticket_id == ticket_id)
            .values(
                estado="error",
                intentos=TicketVikunjaSync.intentos + 1,
                ultimo_error=error_message[:_ULTIMO_ERROR_MAX_CHARS],
            )
        )


def _mark_ambiguous(ticket_id: int) -> None:
    with get_background_db() as db:
        db.execute(update(TicketVikunjaSync).where(TicketVikunjaSync.ticket_id == ticket_id).values(estado="ambiguo"))


def _flag_for_notification(ticket_id: int) -> None:
    """Stays/goes `ambiguo`, and marks `notificado_at` (only if not already
    set, so repeated cycles do not spam notifications for the same row)."""
    with get_background_db() as db:
        db.execute(
            update(TicketVikunjaSync)
            .where(TicketVikunjaSync.ticket_id == ticket_id, TicketVikunjaSync.notificado_at.is_(None))
            .values(estado="ambiguo", notificado_at=func.now())
        )
    logger.warning(
        "vikunja sync: ticket %d needs manual review — ambiguous create could not be auto-resolved", ticket_id
    )


def _match_marker(
    tasks: List[Dict[str, Any]], ticket_id: int, *, window_seconds: Optional[int]
) -> List[Dict[str, Any]]:
    """Tasks whose description contains this ticket's marker. When
    `window_seconds` is set, also requires `created` to fall within that
    many seconds of now (the immediate-check safety window). When it is
    `None` (the reconcile loop's use), no time filter is applied — the loop
    runs long after the marker's short safety window has expired, so time
    can no longer help decide anything; only the marker match matters."""
    marker = _marker(ticket_id)
    now = datetime.now(UTC)
    matches: List[Dict[str, Any]] = []
    for task in tasks:
        description = task.get("description") or ""
        if marker not in description:
            continue
        if window_seconds is not None:
            created_at = _parse_vikunja_timestamp(task.get("created"))
            if created_at is None or abs((now - created_at).total_seconds()) > window_seconds:
                continue
        matches.append(task)
    return matches


async def _resolve_ambiguous_create(ticket_id: int, claimed: Dict[str, Any], client: VikunjaClient) -> None:
    _mark_ambiguous(ticket_id)
    await asyncio.sleep(_AMBIGUOUS_CHECK_DELAY_SECONDS)

    try:
        tasks = await client.list_tasks(project_id=settings.VIKUNJA_PROJECT_ID)
    except (VikunjaPermanentError, VikunjaTransientError):
        # Could not verify right now — stays 'ambiguo', the 300s loop will
        # try again later (with the inverted, never-create rule).
        return

    matches = _match_marker(tasks, ticket_id, window_seconds=_AMBIGUOUS_MATCH_WINDOW_SECONDS)

    if len(matches) == 1:
        _mark_synced(ticket_id, matches[0]["id"])
        return

    if len(matches) > 1:
        # Cannot tell which one is ours — creating now could duplicate;
        # NOT creating could also leave a real duplicate unnoticed. Neither
        # is safe automatically, so this always routes to a human.
        _flag_for_notification(ticket_id)
        return

    # Zero matches in the window: provably safe, nothing else could have
    # created a task with this marker in the last ~120s.
    try:
        task = await client.create_task(
            project_id=settings.VIKUNJA_PROJECT_ID,
            title=claimed["titulo"],
            description=_build_description(ticket_id, claimed["descripcion"]),
        )
    except VikunjaPermanentError as exc:
        _mark_error(ticket_id, str(exc))
        return
    except VikunjaTransientError:
        # Ambiguous again — stays 'ambiguo', flagged; the loop takes over
        # (and will never blindly create either).
        _flag_for_notification(ticket_id)
        return

    _mark_synced(ticket_id, task["id"])


async def push_ticket(ticket_id: int) -> None:
    """Hook 1: schedule this unconditionally right after a ticket's create
    commit. Flag-gated as the very first statement — see module docstring."""
    if not settings.TICKETS_VIKUNJA_SYNC_ENABLED:
        return

    claimed = _claim_ticket(ticket_id)
    if claimed is None:
        return

    client = _client()
    try:
        task = await client.create_task(
            project_id=settings.VIKUNJA_PROJECT_ID,
            title=claimed["titulo"],
            description=_build_description(ticket_id, claimed["descripcion"]),
        )
    except VikunjaPermanentError as exc:
        _mark_error(ticket_id, str(exc))
        return
    except VikunjaTransientError:
        await _resolve_ambiguous_create(ticket_id, claimed, client)
        return

    _mark_synced(ticket_id, task["id"])


# -- attachments --------------------------------------------------------


def _load_sync_row(ticket_id: int) -> Optional[Dict[str, Any]]:
    with get_background_db() as db:
        row = db.query(TicketVikunjaSync).filter(TicketVikunjaSync.ticket_id == ticket_id).first()
        if row is None:
            return None
        return {"estado": row.estado, "vikunja_task_id": row.vikunja_task_id}


def _mark_adjuntos_pendientes(ticket_id: int) -> None:
    with get_background_db() as db:
        db.execute(
            update(TicketVikunjaSync).where(TicketVikunjaSync.ticket_id == ticket_id).values(adjuntos_pendientes=True)
        )


def _clear_adjuntos_pendientes(ticket_id: int) -> None:
    with get_background_db() as db:
        db.execute(
            update(TicketVikunjaSync).where(TicketVikunjaSync.ticket_id == ticket_id).values(adjuntos_pendientes=False)
        )


def _load_adjunto(ticket_id: int, adjunto_id: int) -> Optional[Dict[str, Any]]:
    with get_background_db() as db:
        row = (
            db.query(AdjuntoTicket).filter(AdjuntoTicket.id == adjunto_id, AdjuntoTicket.ticket_id == ticket_id).first()
        )
        if row is None:
            return None
        return {
            "id": row.id,
            "nombre_archivo": row.nombre_archivo,
            "path_archivo": row.path_archivo,
            "mime_type": row.mime_type,
        }


def _load_ticket_adjuntos(ticket_id: int) -> List[Dict[str, Any]]:
    with get_background_db() as db:
        rows = db.query(AdjuntoTicket).filter(AdjuntoTicket.ticket_id == ticket_id).all()
        return [
            {
                "id": row.id,
                "nombre_archivo": row.nombre_archivo,
                "path_archivo": row.path_archivo,
                "mime_type": row.mime_type,
            }
            for row in rows
        ]


async def _upload_one_attachment(vikunja_task_id: int, adjunto: Dict[str, Any], client: VikunjaClient) -> None:
    """A missing file or an upload failure is an ATTACHMENT-level error —
    it must never fail (or retry-loop) the ticket's own sync state."""
    full_path = os.path.join(settings.TICKETS_UPLOADS_DIR, adjunto["path_archivo"])
    if not os.path.exists(full_path):
        logger.error(
            "vikunja sync: attachment %d (%s) missing on disk at %s, skipping upload",
            adjunto["id"],
            adjunto["nombre_archivo"],
            full_path,
        )
        return

    try:
        with open(full_path, "rb") as fh:
            content = fh.read()
        await client.upload_attachment(
            task_id=vikunja_task_id,
            filename=adjunto["nombre_archivo"],
            content=content,
            content_type=adjunto["mime_type"],
        )
    except (VikunjaPermanentError, VikunjaTransientError, OSError) as exc:
        logger.error(
            "vikunja sync: failed to upload attachment %d for task %d: %s", adjunto["id"], vikunja_task_id, exc
        )


async def push_attachment(ticket_id: int, adjunto_id: int) -> None:
    """Hook 2: schedule this after an attachment upload's own commit. If the
    parent ticket has no Vikunja task yet, defers via
    `adjuntos_pendientes` and returns WITHOUT attempting any network call —
    there is nothing to attach to."""
    if not settings.TICKETS_VIKUNJA_SYNC_ENABLED:
        return

    sync_row = _load_sync_row(ticket_id)
    if sync_row is None or sync_row["estado"] != "sincronizado" or sync_row["vikunja_task_id"] is None:
        _mark_adjuntos_pendientes(ticket_id)
        return

    adjunto = _load_adjunto(ticket_id, adjunto_id)
    if adjunto is None:
        return

    await _upload_one_attachment(sync_row["vikunja_task_id"], adjunto, _client())


# -- 300s reconcile loop (crash backstop) --------------------------------


def _reclaim_stale_enviando() -> int:
    threshold = datetime.now(UTC) - timedelta(minutes=_STALE_ENVIANDO_MINUTES)
    with get_background_db() as db:
        result = db.execute(
            update(TicketVikunjaSync)
            .where(TicketVikunjaSync.estado == "enviando", TicketVikunjaSync.claimed_at < threshold)
            .values(estado="ambiguo")
        )
        return result.rowcount


def _fetch_ambiguous_ticket_ids() -> List[int]:
    with get_background_db() as db:
        rows = db.query(TicketVikunjaSync.ticket_id).filter(TicketVikunjaSync.estado == "ambiguo").all()
        return [row[0] for row in rows]


def _fetch_pending_attachment_tickets() -> List[Tuple[int, int]]:
    with get_background_db() as db:
        rows = (
            db.query(TicketVikunjaSync.ticket_id, TicketVikunjaSync.vikunja_task_id)
            .filter(
                TicketVikunjaSync.estado == "sincronizado",
                TicketVikunjaSync.adjuntos_pendientes.is_(True),
                TicketVikunjaSync.vikunja_task_id.isnot(None),
            )
            .all()
        )
        return [(row[0], row[1]) for row in rows]


async def _drain_ticket_attachments(ticket_id: int, vikunja_task_id: int, client: VikunjaClient) -> None:
    for adjunto in _load_ticket_adjuntos(ticket_id):
        await _upload_one_attachment(vikunja_task_id, adjunto, client)
    _clear_adjuntos_pendientes(ticket_id)


async def run_vikunja_reconcile_cycle() -> Dict[str, int]:
    """300s backstop loop (registered in `app.main`'s `bg_lock_fd` block,
    single-worker). Two jobs, NEITHER of which ever creates a task:
      1. Reclaim 'enviando' rows stuck past a crash (-> 'ambiguo').
      2. Resolve 'ambiguo' rows: adopt on exactly one marker match, else
         stay 'ambiguo' and flag for notification. The rule inverts vs the
         immediate check — a zero-match result here does NOT create,
         because it can no longer prove non-existence (module docstring).
    Also drains attachments deferred while their parent ticket was not yet
    synced.
    """
    stats = {"reclaimed": 0, "adopted": 0, "still_ambiguous": 0, "drained": 0}
    if not settings.TICKETS_VIKUNJA_SYNC_ENABLED:
        return stats

    stats["reclaimed"] = _reclaim_stale_enviando()

    ambiguous_ticket_ids = _fetch_ambiguous_ticket_ids()
    if ambiguous_ticket_ids:
        client = _client()
        try:
            tasks = await client.list_tasks(project_id=settings.VIKUNJA_PROJECT_ID)
        except (VikunjaPermanentError, VikunjaTransientError):
            tasks = None

        if tasks is not None:
            for ticket_id in ambiguous_ticket_ids:
                matches = _match_marker(tasks, ticket_id, window_seconds=None)
                if len(matches) == 1:
                    _mark_synced(ticket_id, matches[0]["id"])
                    stats["adopted"] += 1
                else:
                    _flag_for_notification(ticket_id)
                    stats["still_ambiguous"] += 1

    pending_attachments = _fetch_pending_attachment_tickets()
    if pending_attachments:
        client = _client()
        for ticket_id, vikunja_task_id in pending_attachments:
            await _drain_ticket_attachments(ticket_id, vikunja_task_id, client)
            stats["drained"] += 1

    return stats
