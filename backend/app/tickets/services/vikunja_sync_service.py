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

Attachments: `push_attachment` NEVER uploads directly — it only sets
`adjuntos_pendientes=True` (review finding, PR 2: an earlier version
uploaded immediately when the ticket was already `sincronizado`, which can
race the loop's own drain of an EARLIER pending attachment on the same
ticket and double-attach it, since `upload_attachment` is
`idempotent=False`). The loop is the single writer for every attachment
upload, and it decides what still needs uploading by asking Vikunja itself
(`list_attachments`) rather than trusting local state — see the
"attachments" section header below for why a local flag/watermark was not
enough. It only clears the pending flag once every local attachment for the
ticket is confirmed present in Vikunja.

`error` rows are bounded-retried by the loop too (up to
`_MAX_ERROR_RETRY_INTENTOS`): the CAS claim already accepted `error` as a
re-claimable state, but nothing was reclaiming it — a config-level failure
(stale token, wrong project id) left a ticket unsynced forever with zero
retry and zero visibility.
"""

from __future__ import annotations

import asyncio
from collections import Counter
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, func, or_, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_background_db
from app.models.notificacion import SeveridadNotificacion
from app.services.notificacion_service import crear_notificaciones_para_permisos
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
_MAX_ERROR_RETRY_INTENTOS = 5


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
            # The claim already flipped the row to 'enviando'. Leaving it
            # there would strand it until the 10-minute sweep reclaims it to
            # 'ambiguo' and pesters a human about a ticket that simply does
            # not exist. A vanished ticket is a clean, terminal error.
            db.execute(
                update(TicketVikunjaSync)
                .where(TicketVikunjaSync.ticket_id == ticket_id)
                .values(
                    estado="error",
                    intentos=_MAX_ERROR_RETRY_INTENTOS,
                    ultimo_error="ticket no longer exists",
                )
            )
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


def _flag_for_notification(ticket_id: int) -> bool:
    """Stays/goes `ambiguo`, and marks `notificado_at` (only if not already
    set, so repeated cycles do not spam notifications for the same row —
    the warning below only fires the FIRST time a row is flagged, not on
    every 300s cycle it remains unresolved)."""
    with get_background_db() as db:
        result = db.execute(
            update(TicketVikunjaSync)
            .where(TicketVikunjaSync.ticket_id == ticket_id, TicketVikunjaSync.notificado_at.is_(None))
            .values(estado="ambiguo", notificado_at=func.now())
        )
        newly_flagged = result.rowcount == 1
    if newly_flagged:
        logger.warning(
            "vikunja sync: ticket %d needs manual review — ambiguous create could not be auto-resolved", ticket_id
        )
    return newly_flagged


def _notificar_fallos_terminales(ticket_ids: List[int]) -> None:
    """ONE notification per cycle, however many tickets failed.

    Notifying per ticket would drop twenty rows into everyone's bell the
    first time Vikunja is down for a whole cycle -- and a bell that cries
    twenty times is a bell people learn to ignore. `notificado_at` alone
    does not prevent that: it stops the SECOND cycle, not the first burst.

    The channel is deliberately in-app (`notificaciones` -> NotificationBell),
    NOT a task in Vikunja: telling Vikunja that Vikunja is unreachable is
    circular and fails exactly when it matters.
    """
    if not ticket_ids:
        return
    ids = ", ".join(f"#{t}" for t in sorted(ticket_ids))
    with get_background_db() as db:
        crear_notificaciones_para_permisos(
            db,
            permisos_requeridos=["tickets.gestionar"],
            tipo="tickets.vikunja_sync_error",
            mensaje=(
                f"{len(ticket_ids)} ticket(s) no se pudieron sincronizar con Vikunja y necesitan revisión manual: {ids}"
            ),
            severidad=SeveridadNotificacion.CRITICAL,
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


async def _attempt_create_and_sync(ticket_id: int, client: VikunjaClient) -> bool:
    """Claims the ledger row (`pendiente`|`error` -> `enviando`) and runs
    ONE create attempt, routing the outcome exactly like the module
    docstring's ordering. Shared by `push_ticket` (first attempt, right
    after ticket creation) and the reconcile loop's bounded `error` retry
    (review finding: `error` was a CAS-claimable state with no caller ever
    reclaiming it — a permanent-looking failure, e.g. a stale token, left
    the ticket unsynced forever with zero visibility)."""
    claimed = _claim_ticket(ticket_id)
    if claimed is None:
        # Did not win the CAS: nothing was attempted, so the caller must not
        # count this as work (same reasoning as `drained` below).
        return False

    try:
        task = await client.create_task(
            project_id=settings.VIKUNJA_PROJECT_ID,
            title=claimed["titulo"],
            description=_build_description(ticket_id, claimed["descripcion"]),
        )
    except VikunjaPermanentError as exc:
        _mark_error(ticket_id, str(exc))
        return True
    except VikunjaTransientError:
        await _resolve_ambiguous_create(ticket_id, claimed, client)
        return True

    _mark_synced(ticket_id, task["id"])
    return True


async def push_ticket(ticket_id: int) -> None:
    """Hook 1: schedule this unconditionally right after a ticket's create
    commit. Flag-gated as the very first statement — see module docstring."""
    if not settings.TICKETS_VIKUNJA_SYNC_ENABLED:
        return

    await _attempt_create_and_sync(ticket_id, _client())


# -- attachments --------------------------------------------------------


def _mark_adjuntos_pendientes(ticket_id: int) -> None:
    """Ensures the ledger row EXISTS before deferring — without this, a row
    that has not been created yet (e.g. the flag was off when the ticket
    was created and turned on later) makes the UPDATE below a silent
    zero-row no-op, and the attachment is lost forever (never drained,
    since the loop only looks at existing rows)."""
    with get_background_db() as db:
        _insert_sync_row_if_absent(db, ticket_id)
        db.execute(
            update(TicketVikunjaSync).where(TicketVikunjaSync.ticket_id == ticket_id).values(adjuntos_pendientes=True)
        )


def _clear_adjuntos_pendientes(ticket_id: int, up_to_adjunto_id: Optional[int] = None) -> None:
    """Clears the pending flag, but ONLY if no attachment newer than the
    batch we just drained has arrived meanwhile.

    Without that guard there is a lost update: between `_load_ticket_adjuntos`
    and this call, a user can upload a file, whose `push_attachment` sets the
    flag to True -- and then this would immediately overwrite it with False.
    That attachment would never be uploaded and nothing would look at the
    ticket again until some *other* attachment happened to arrive.
    """
    with get_background_db() as db:
        stmt = update(TicketVikunjaSync).where(TicketVikunjaSync.ticket_id == ticket_id)
        if up_to_adjunto_id is not None:
            mas_nuevo = (
                db.query(AdjuntoTicket.id)
                .filter(AdjuntoTicket.ticket_id == ticket_id, AdjuntoTicket.id > up_to_adjunto_id)
                .first()
            )
            if mas_nuevo is not None:
                # Something arrived while we were uploading: leave the flag
                # set so the next cycle picks the newcomer up.
                return
        db.execute(stmt.values(adjuntos_pendientes=False))


def _load_ticket_adjuntos(ticket_id: int) -> List[Dict[str, Any]]:
    with get_background_db() as db:
        rows = db.query(AdjuntoTicket).filter(AdjuntoTicket.ticket_id == ticket_id).all()
        return [
            {
                "id": row.id,
                "nombre_archivo": row.nombre_archivo,
                "path_archivo": row.path_archivo,
                "mime_type": row.mime_type,
                "tamano_bytes": row.tamano_bytes,
            }
            for row in rows
        ]


async def _upload_one_attachment(vikunja_task_id: int, adjunto: Dict[str, Any], client: VikunjaClient) -> bool:
    """A missing file or an upload failure is an ATTACHMENT-level error —
    it must never fail (or retry-loop) the ticket's own sync state. Returns
    True on a genuine upload success, False otherwise, so the caller can
    decide whether it is safe to stop tracking this ticket's backlog."""
    full_path = os.path.join(settings.TICKETS_UPLOADS_DIR, adjunto["path_archivo"])
    if not os.path.exists(full_path):
        logger.error(
            "vikunja sync: attachment %d (%s) missing on disk at %s, skipping upload",
            adjunto["id"],
            adjunto["nombre_archivo"],
            full_path,
        )
        # A permanently-missing file can never succeed on retry either —
        # treat it as "handled" so it does not block the ticket's backlog
        # forever.
        return True

    try:
        with open(full_path, "rb") as fh:
            content = fh.read()
        await client.upload_attachment(
            task_id=vikunja_task_id,
            filename=adjunto["nombre_archivo"],
            content=content,
            content_type=adjunto["mime_type"],
        )
        return True
    except (VikunjaPermanentError, VikunjaTransientError, OSError) as exc:
        logger.error(
            "vikunja sync: failed to upload attachment %d for task %d: %s", adjunto["id"], vikunja_task_id, exc
        )
        return False


async def push_attachment(ticket_id: int) -> None:
    """Hook 2: schedule this after an attachment upload's own commit.

    ALWAYS defers via `adjuntos_pendientes` — it never uploads directly,
    even when the parent ticket is already `sincronizado`. Review finding
    (PR 2): an earlier version uploaded immediately when the ticket was
    already synced, racing the 300s loop's own drain of any attachment
    left pending by an EARLIER upload on the same ticket — `upload_attachment`
    is `idempotent=False`, so a file caught by both paths gets attached
    twice. Routing every attachment through the SAME single path (the loop,
    which runs sequentially on the one `bg_lock_fd` worker) removes that
    race entirely, at the cost of a poll-interval delay before the first
    attachment on an already-synced ticket appears in Vikunja."""
    if not settings.TICKETS_VIKUNJA_SYNC_ENABLED:
        return

    _mark_adjuntos_pendientes(ticket_id)


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
    """Ambiguous rows the loop should still try to resolve on its own.

    A row that has already been notified is EXCLUDED: notification is the
    handoff to a human, not a log line. Without this, a row that never
    matches is re-processed forever — `notificado_at` stops the notification
    spam but not the work, so every 300s each zombie row would keep hitting
    Vikunja's task list for as long as the row exists.
    """
    with get_background_db() as db:
        rows = (
            db.query(TicketVikunjaSync.ticket_id)
            .filter(
                TicketVikunjaSync.estado == "ambiguo",
                TicketVikunjaSync.notificado_at.is_(None),
            )
            .all()
        )
        return [row[0] for row in rows]


def _warn_about_orphaned_attachments() -> int:
    """Attachments waiting on a ticket that will never sync (terminal
    `error`). The files are safe on disk, but nothing would ever mention
    them again — an invisible queue is how you find out months later."""
    with get_background_db() as db:
        rows = (
            db.query(TicketVikunjaSync.ticket_id)
            .filter(
                TicketVikunjaSync.adjuntos_pendientes.is_(True),
                TicketVikunjaSync.estado != "sincronizado",
                or_(
                    TicketVikunjaSync.intentos >= _MAX_ERROR_RETRY_INTENTOS,
                    # An `ambiguo` row that was already notified is excluded
                    # from the loop's own sweep, so it never reaches
                    # `sincronizado` and its `intentos` stays at 0 -- without
                    # this arm its attachments are exactly the invisible
                    # queue this function exists to prevent.
                    and_(
                        TicketVikunjaSync.estado == "ambiguo",
                        TicketVikunjaSync.notificado_at.isnot(None),
                    ),
                ),
            )
            .all()
        )
    ticket_ids = [row[0] for row in rows]
    if ticket_ids:
        logger.warning(
            "vikunja sync: %d ticket(s) have attachments pending on a ticket that will not sync: %s",
            len(ticket_ids),
            ticket_ids,
        )
    return len(ticket_ids)


def _fetch_retryable_error_ticket_ids() -> List[int]:
    """Rows the loop should drive forward: `error` under the retry budget,
    and — critically — `pendiente`.

    `error` is a bounded retry because a permanent-looking failure can still
    be transient at the CONFIGURATION level (an expired token, a momentarily
    wrong project id). Past `_MAX_ERROR_RETRY_INTENTOS` the row stays `error`
    and relies on `ultimo_error` for visibility.

    `pendiente` is here because otherwise it is an ORPHAN state that nothing
    ever sweeps, and two ordinary paths land in it:
      1. The flag was off when the ticket was created (so no row existed),
         then turned on, and an attachment upload inserts the row as
         `pendiente`. `push_ticket` only runs on the creation POST, so
         nothing would ever pick that ticket up again.
      2. The process dies between the row INSERT and the CAS claim, or a
         deploy restarts the app between the ticket's commit and its
         BackgroundTask running. The row sits in `pendiente` — and the 300s
         crash backstop, which exists for exactly this, would not look at it.
    `_claim_ticket`'s CAS already accepts `pendiente`, so simply handing
    these ids to `_attempt_create_and_sync` is the whole fix. The same
    `intentos` budget bounds them: a `pendiente` row accrues attempts only
    once it starts failing.
    """
    with get_background_db() as db:
        rows = (
            db.query(TicketVikunjaSync.ticket_id)
            .filter(
                TicketVikunjaSync.estado.in_(["error", "pendiente"]),
                TicketVikunjaSync.intentos < _MAX_ERROR_RETRY_INTENTOS,
            )
            .all()
        )
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


async def _drain_ticket_attachments(ticket_id: int, vikunja_task_id: int, client: VikunjaClient) -> bool:
    """Uploads the ticket's attachments that Vikunja does not already hold.

    Asking Vikunja what is already attached — instead of tracking it on our
    side — is what makes a retry safe. `upload_attachment` is
    `idempotent=False`: every call creates a NEW attachment record. So a
    partial failure (2 of 3 uploads succeed) previously retried the whole
    batch next cycle and attached those 2 a second time. The earlier
    docstring called that residual risk unfixable "without a per-attachment
    ledger column, i.e. a migration". It is fixable without one: the remote
    list already IS the ledger, it is authoritative, and it self-corrects
    anything a previous buggy pass got wrong.

    Matching is by (filename, size) as a MULTISET, so a ticket carrying two
    genuinely different files that happen to share a name still gets both.
    """
    adjuntos = _load_ticket_adjuntos(ticket_id)
    if not adjuntos:
        # `up_to_adjunto_id=0` is the same lost-update guard as the normal
        # path: with zero attachments loaded, ANY attachment now present
        # arrived after the read, so the flag must survive for it.
        _clear_adjuntos_pendientes(ticket_id, up_to_adjunto_id=0)
        return True

    try:
        remotos = await client.list_attachments(task_id=vikunja_task_id)
    except (VikunjaPermanentError, VikunjaTransientError):
        # Cannot tell what is already there, so uploading now could
        # duplicate. Leave the flag set and let the next cycle decide.
        return False

    ya_estan: Counter = Counter()
    for remoto in remotos:
        archivo = remoto.get("file") or {}
        ya_estan[(archivo.get("name"), archivo.get("size"))] += 1

    all_succeeded = True
    for adjunto in adjuntos:
        clave = (adjunto["nombre_archivo"], adjunto["tamano_bytes"])
        if ya_estan.get(clave, 0) > 0:
            ya_estan[clave] -= 1
            continue
        ok = await _upload_one_attachment(vikunja_task_id, adjunto, client)
        all_succeeded = all_succeeded and ok

    if all_succeeded:
        _clear_adjuntos_pendientes(ticket_id, up_to_adjunto_id=max(a["id"] for a in adjuntos))
    return all_succeeded


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
    stats = {
        "reclaimed": 0,
        "adopted": 0,
        "still_ambiguous": 0,
        "drained": 0,
        "error_retried": 0,
        "orphaned_attachments": 0,
        "notificados": 0,
    }
    if not settings.TICKETS_VIKUNJA_SYNC_ENABLED:
        return stats

    # Tickets that crossed into "a human has to look at this" during THIS
    # cycle. Collected, not notified one by one — see
    # `_notificar_fallos_terminales`.
    recien_marcados: List[int] = []

    stats["reclaimed"] = _reclaim_stale_enviando()

    retryable_ticket_ids = _fetch_retryable_error_ticket_ids()
    if retryable_ticket_ids:
        client = _client()
        for ticket_id in retryable_ticket_ids:
            if await _attempt_create_and_sync(ticket_id, client):
                stats["error_retried"] += 1

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
                    if _flag_for_notification(ticket_id):
                        recien_marcados.append(ticket_id)
                    stats["still_ambiguous"] += 1

    pending_attachments = _fetch_pending_attachment_tickets()
    if pending_attachments:
        client = _client()
        for ticket_id, vikunja_task_id in pending_attachments:
            # Count only real drains: the function returns False when
            # `list_attachments` failed or an upload did, and a stats line
            # reporting `drained: N` after uploading nothing lies exactly
            # when you most need it to tell the truth.
            if await _drain_ticket_attachments(ticket_id, vikunja_task_id, client):
                stats["drained"] += 1

    stats["orphaned_attachments"] = _warn_about_orphaned_attachments()

    _notificar_fallos_terminales(recien_marcados)
    stats["notificados"] = len(recien_marcados)

    return stats
