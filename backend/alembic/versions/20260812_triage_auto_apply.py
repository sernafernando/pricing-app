"""Backfill pending AI-triage proposals into confirmed ia_auto values
(feat/tickets-triage-aplicar-directo)

The confirm-first design shipped by tickets-ai-triage PR 4b never scaled:
production accumulated 164 `pendiente` proposals across 35 tickets, every
one of them sitting invisible in a side table while the board kept showing
"Sin clasificar". This is a DATA migration (explicitly requested over a
one-off script: versioned, has a real `downgrade()`, needs no manual step)
that applies every still-`pendiente` proposal for the four origen-tracked
plain fields — `severidad`/`urgencia`/`resumen`/`titulo` — the same way
`triage_service.run_triage` now does going forward with
`TICKETS_TRIAGE_AUTO_APPLY=True`: the ticket column gets written, its
`<campo>_origen` becomes `'ia_auto'`, and the proposal becomes
`estado='confirmada'` with `confirmado_por_id` staying NULL — that NULL is
the signal nobody has reviewed it yet.

SCOPE — deliberately NOT `sector`/`tipo_ticket`/`metadata_ia`:
- `sector`/`tipo_ticket` have no `_origen` column at all, so there is no
  way to make a downgrade "precise" for them the way the decision requires
  (revert only what carries `_origen = 'ia_auto'`). Moving a ticket's
  sector is also a DOMAIN OPERATION (workflow + estado_id resolution, see
  `confirmacion_service._confirmar_sector`), not a column UPDATE — hand-
  rolling that in raw SQL for a historical, one-time backfill is a correctness
  risk this migration does not need to take. Any pending `sector`/
  `tipo_ticket` proposal is left `pendiente`, still reachable through the
  existing (still-functional) confirm UI.
- `metadata_ia` was always a JSONB MERGE (`campos_metadata = {**old, **new}`)
  — there is no record of which keys a given proposal would have added, so
  there is nothing precise to revert. Left `pendiente` for the same reason.

PER-FIELD WHERE guards, so this migration can NEVER overwrite a value a
human (or any other path) already set:
- severidad/urgencia/resumen: only when the ticket's own column IS NULL —
  the same "nothing has claimed this field yet" invariant
  `_ya_tiene_propuesta_activa` already relies on in the application.
- titulo: `tickets.titulo` is NOT NULL, so "IS NULL" can never gate it. Use
  `texto_original IS NOT NULL` instead — `_debe_proponer_titulo` already
  guarantees the model was ONLY ever asked to propose a titulo for a
  single-box-intake ticket, whose current titulo is exactly the machine-
  derived `_derivar_titulo(texto_original)` truncation, never something a
  person typed. A pending titulo proposal existing at all is proof this
  ticket satisfies that condition.

DOWNGRADE precision, exactly as decided: revert only ticket values whose
`<campo>_origen = 'ia_auto'` AND whose backing proposal is `confirmada`
with a NULL confirmer, and return those proposals to `pendiente`. This is a
DATA-SHAPE match, not a "rows this migration personally touched" ledger (no
such ledger exists without adding a new column, out of scope) — a real
downgrade run long after go-live would also revert any ticket the ORDINARY
`run_triage` auto-apply path wrote in the meantime. That is the same
trade-off `20260810_sector_tipo_metadata_check_ia.py`'s own downgrade makes
for `campo`, made explicit here for `confirmado_por_id`/`_origen`.

For `severidad`/`urgencia`/`resumen`, downgrade clears the column back to
NULL (the state it was in before this migration ever ran — nullable
columns, no data loss). For `titulo` (NOT NULL), downgrade recomputes
`_derivar_titulo`'s own truncation (strip both ends, first 80 chars, strip
again) from the immutable `texto_original` — the exact value the ticket
carried before this migration, not a guess. `_STRIP_CHARS` spells out the
same whitespace set Python's `str.strip()` uses (space/tab/newline/CR/
form-feed/vertical-tab) — Postgres's bare `TRIM(BOTH FROM ...)` only
strips plain spaces, which would silently diverge from `_derivar_titulo`
for a `texto_original` starting or ending in e.g. a newline.

Real pre-push review finding, twice: (1) downgrade's per-proposal
`estado='pendiente'` UPDATEs run BEFORE the matching ticket-column clear,
both gated on the SAME `t.{campo}_origen = 'ia_auto'` join — running them
in the other order (as first written) left the proposal-revert step with
no way to tell a legitimately-reverted ticket apart from one a human had
ALREADY corrected by the time downgrade ran, since by then the ticket
column would already be NULL either way. (2) the runtime write path
(`triage_service.run_triage`) needed its OWN mirror of this migration's
"never overwrite a claimed field" guard — see that module's own history
for why a `WHERE tickets.{campo} IS NULL`-shaped precondition is not
enough there, and `_origen` is checked instead.

Revision ID: 20260812_triage_auto_apply
Revises: 20260811_ver_web_tarjeta
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260812_triage_auto_apply"
down_revision = "20260811_ver_web_tarjeta"
branch_labels = None
depends_on = None

_TITULO_DERIVADO_MAX_LEN = 80
# Python's `str.strip()` (used by `_derivar_titulo`) strips ALL whitespace —
# space, tab, newline, CR, form feed, vertical tab — not just the plain
# space Postgres's bare `TRIM(BOTH FROM ...)` removes. Spelled out
# explicitly so a `texto_original` starting/ending in e.g. `\n` still
# recomputes the exact same titulo `_derivar_titulo` would.
_STRIP_CHARS = r"E'\t\n\r\x0b\x0c '"

# Per-campo precondition for the ticket column being safe to overwrite —
# see module docstring. `{campo}` is substituted from this literal tuple
# only, never from user input.
_CAMPOS_SIMPLES = ("severidad", "urgencia", "resumen")


def upgrade() -> None:
    bind = op.get_bind()

    for campo in _CAMPOS_SIMPLES:
        result = bind.execute(
            sa.text(
                f"""
                UPDATE tickets
                SET {campo} = (p.valor_propuesto ->> 'valor'),
                    {campo}_origen = 'ia_auto'
                FROM tickets_propuestas_ia p
                WHERE p.ticket_id = tickets.id
                  AND p.campo = :campo
                  AND p.estado = 'pendiente'
                  AND tickets.{campo} IS NULL
                RETURNING p.id
                """  # noqa: S608 (campo comes only from the literal tuple above)
            ),
            {"campo": campo},
        )
        _marcar_confirmadas(bind, result)

    # titulo: NOT NULL column, gated on `texto_original IS NOT NULL`
    # instead — see module docstring.
    result = bind.execute(
        sa.text(
            """
            UPDATE tickets
            SET titulo = (p.valor_propuesto ->> 'valor'),
                titulo_origen = 'ia_auto'
            FROM tickets_propuestas_ia p
            WHERE p.ticket_id = tickets.id
              AND p.campo = 'titulo'
              AND p.estado = 'pendiente'
              AND tickets.texto_original IS NOT NULL
            RETURNING p.id
            """
        )
    )
    _marcar_confirmadas(bind, result)


def _marcar_confirmadas(bind: sa.engine.Connection, update_result: sa.engine.CursorResult) -> None:
    """Mark `confirmada` exactly the proposals whose value the `UPDATE
    ... FROM tickets_propuestas_ia p ... RETURNING p.id` above just wrote
    onto a ticket column — no more, no less.

    This is coupled to the write ITSELF (via `RETURNING`), not to the
    ticket's resulting shape (a previous version re-queried
    `t.{campo}_origen = 'ia_auto'` after the fact — deleted, it was wrong).
    A shape-only re-check only proves *some* ia_auto write exists for that
    ticket/campo at some point; it does NOT prove this proposal's value is
    the one that produced it, or that this migration's own UPDATE is what
    wrote it. That gap is reachable, not theoretical:
    `TICKETS_TRIAGE_AUTO_APPLY=False` plus a forced retrigger
    (`POST /tickets/{id}/triage?forzar=true`) can demote an already-applied
    `ia_auto`/`confirmada` proposal to `reemplazada` and insert a NEW
    `pendiente` proposal with a DIFFERENT value for the same ticket/campo,
    while leaving the ticket's own `_origen` column untouched. A shape-only
    join would then mark that new, never-applied proposal `confirmada`,
    claiming a write that never happened — and a later Discard on it would
    wipe the ticket's real, correct value. See
    `test_marking_is_coupled_to_the_write_not_to_origen_shape` for the
    fixture that reproduces this exact sequence.
    """
    propuesta_ids = [row[0] for row in update_result]
    if not propuesta_ids:
        return
    bind.execute(
        sa.text("UPDATE tickets_propuestas_ia SET estado = 'confirmada', confirmado_at = NOW() WHERE id = ANY(:ids)"),
        {"ids": propuesta_ids},
    )


def downgrade() -> None:
    bind = op.get_bind()

    # ORDER MATTERS (real pre-push review finding): the proposal-revert
    # step runs FIRST, while `tickets.{campo}_origen` still says 'ia_auto'
    # — that is the ONE join condition that proves a human has NOT since
    # corrected this field through a different path (`actualizar_ticket`'s
    # PATCH, which never touches `tickets_propuestas_ia`). Running this
    # AFTER clearing the ticket column would have nothing left to check
    # against (already NULL for the legitimate cases) and, worse, offered
    # no guard at all against the human-corrected case — reverting a
    # proposal to `pendiente` over a value a person already fixed, which
    # the still-functional confirm UI would then let someone re-approve
    # and clobber.
    #
    # The ticket-column clear is coupled to the revert step via
    # `RETURNING p.ticket_id`, NOT a second `{campo}_origen = 'ia_auto'`
    # join (real pre-push review finding, second one: a bare re-join only
    # proves the ORIGEN shape, not that THIS revert is what should trigger
    # the clear). That gap became reachable once `confirmacion_service.
    # confirmar()` grew its ratify branch (feat/tickets-triage-aplicar-
    # directo): ratifying an ia_auto proposal sets `confirmado_por_id`
    # WITHOUT touching the ticket — `{campo}_origen` stays 'ia_auto'
    # forever, that is the whole point (a human looked and agrees, nothing
    # to rewrite). The revert step above already excludes a ratified row
    # correctly (`confirmado_por_id IS NULL`); a shape-only clear right
    # after it would still wipe that ratified value anyway, since it never
    # checks `confirmado_por_id` at all. RETURNING ties the clear strictly
    # to the tickets whose proposal the revert step actually reverted.
    for campo in _CAMPOS_SIMPLES:
        result = bind.execute(
            sa.text(
                f"""
                UPDATE tickets_propuestas_ia p
                SET estado = 'pendiente', confirmado_at = NULL
                FROM tickets t
                WHERE p.ticket_id = t.id
                  AND p.campo = :campo
                  AND p.estado = 'confirmada'
                  AND p.confirmado_por_id IS NULL
                  AND t.{campo}_origen = 'ia_auto'
                RETURNING p.ticket_id
                """  # noqa: S608 (campo comes only from the literal tuple above)
            ),
            {"campo": campo},
        )
        _limpiar_columna_revertida(bind, campo, result)

    result = bind.execute(
        sa.text(
            """
            UPDATE tickets_propuestas_ia p
            SET estado = 'pendiente', confirmado_at = NULL
            FROM tickets t
            WHERE p.ticket_id = t.id
              AND p.campo = 'titulo'
              AND p.estado = 'confirmada'
              AND p.confirmado_por_id IS NULL
              AND t.titulo_origen = 'ia_auto'
            RETURNING p.ticket_id
            """
        )
    )
    ticket_ids = [row[0] for row in result]
    if ticket_ids:
        bind.execute(
            sa.text(
                f"""
                UPDATE tickets
                SET titulo = TRIM(TRAILING {_STRIP_CHARS} FROM
                        LEFT(TRIM(BOTH {_STRIP_CHARS} FROM tickets.texto_original), {_TITULO_DERIVADO_MAX_LEN})
                    ),
                    titulo_origen = NULL
                WHERE id = ANY(:ids)
                  AND titulo_origen = 'ia_auto'
                  AND texto_original IS NOT NULL
                """  # noqa: S608 (_STRIP_CHARS/_TITULO_DERIVADO_MAX_LEN are module-level literal constants, never user input)
            ),
            {"ids": ticket_ids},
        )


def _limpiar_columna_revertida(bind: sa.engine.Connection, campo: str, revert_result: sa.engine.CursorResult) -> None:
    """Clears `tickets.{campo}`/`{campo}_origen` ONLY for the ticket ids the
    proposal-revert `UPDATE ... RETURNING p.ticket_id` above actually
    reverted — see the long comment above `downgrade()`'s loop for why a
    shape-only `{campo}_origen = 'ia_auto'` re-join is not enough once a
    ratified (human-approved, `confirmado_por_id` set) row can share that
    same origen forever."""
    ticket_ids = [row[0] for row in revert_result]
    if not ticket_ids:
        return
    bind.execute(
        sa.text(f"UPDATE tickets SET {campo} = NULL, {campo}_origen = NULL WHERE id = ANY(:ids)"),  # noqa: S608
        {"ids": ticket_ids},
    )
