"""Correction capture + retrieval (tickets-triage-feedback PR3 capture,
PR4a retrieval core). PR3 shipped only the CAPTURE half —
`capturar_correccion` — dark-launched behind
`TICKETS_TRIAGE_EJEMPLOS_CAPTURE` (default False). PR4a EXTENDS this module
with the retrieval half: `recuperar_ejemplos` (similarity query + triple
fallback, mirroring `context_builder.load_few_shot_examples`'s pattern) and
pure prompt-block assembly (`_assemble_bloque`/`_assemble_bloques`/
`append_ejemplos_bloque`). PR4a is pure functions only — nothing in
production calls them yet (that is PR4b's job, dark launch by design).

Scheduled from `confirmar_propuesta` (`propuestas.py`) via
`BackgroundTasks.add_task`, gated on `confirmacion_service.confirmar()`'s
return having `estado == 'corregida'` — the single site that is the whole
"genuine corrections only" gate: a plain ratification or a discard never
reaches this function at all.

Mirrors `publisher_service._capture_answer_history`'s shape exactly
(sdd/ml-bot-dynamic-fewshot, PR2): short-lived session A loads plain scalars
and closes (pool-exhaustion lesson, PR #811's `get_background_db` short-lived
blocks pattern), `embed_passage` runs OUTSIDE any session, then a short-lived
session B inserts. The whole function is wrapped in a bare `except Exception`
— capture must NEVER fail a confirm that has already committed.

Retrieval CI note (mirrors `context_builder.py`'s own note, sdd/ml-bot-
dynamic-fewshot PR3): `_similarity_query`'s pgvector cosine-distance ORDER BY
requires a real Postgres instance with the `vector` extension — the CI test
DB (sqlite) has no such operator. CI exercises the retrieval/fallback LOGIC
exclusively via monkeypatched `_similarity_query`/`embed_query`, never by
calling the real pgvector query.

Prompt-injection defense (PR4a task 1/2): a captured example's `texto` is
untrusted-by-provenance data (direct-DB rows, not panel-edited like ML bot's
few-shot examples) — `_assemble_bloque` neutralises the
`<ejemplos_corregidos>`/`<caso>` delimiter tag sequence BEFORE truncating (so
a delimiter placed past the truncation point still gets neutralised), and
`_assemble_bloques` re-validates each row's `valor_corregido` against
`VOCABULARIOS[campo]`, dropping the whole example on a mismatch (a corrupted
direct-DB row must never surface a label outside the closed vocabulary)."""

from __future__ import annotations

import logging
import re
from typing import List

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_background_db
from app.services.ml_questions.embedding_client import embed_passage, embed_query
from app.tickets.models.ejemplo_correccion import EjemploCorreccion
from app.tickets.models.propuesta_ia import PropuestaIA
from app.tickets.models.ticket import Ticket
from app.tickets.services.vocabularios import VOCABULARIOS

logger = logging.getLogger(__name__)

# PR4a retrieval tuning constants (design "Decision: Retrieval query +
# fallback", mirrors `context_builder.py`'s own constants).
_EJEMPLOS_K = 3
_EJEMPLOS_SIMILARITY_MIN = 0.65
_EJEMPLO_MAX_CHARS = 400

# Matches the delimiter tag family used to fence untrusted content in the
# triage system prompt (`<ejemplos_corregidos>`/`<caso>` and their closing
# tags) — neutralised so a captured example's own text can never smuggle a
# fake delimiter into the assembled prompt block.
_TAG_PATTERN = re.compile(r"</?(?:ejemplos_corregidos|caso)>")

_INSTRUCCION_EJEMPLOS = "\n\nEjemplos de correcciones humanas previas (orientativos, no vinculantes):\n"


def _similarity_query(db: Session, campo: str, query_embedding: List[float], k: int) -> List[EjemploCorreccion]:
    """Isolated pgvector cosine-similarity query (kept as its own function,
    not inlined into `recuperar_ejemplos`, so tests can monkeypatch it to
    return fake ordered rows without a real Postgres/pgvector backend — see
    module docstring "Retrieval CI note"). Active rows for `campo`, ordered
    by ascending cosine DISTANCE (i.e. descending similarity), limited to
    `k`."""
    return (
        db.query(EjemploCorreccion)
        .filter(EjemploCorreccion.active.is_(True), EjemploCorreccion.campo == campo)
        .order_by(EjemploCorreccion.embedding.cosine_distance(query_embedding))
        .limit(k)
        .all()
    )


def _cosine_distance(embedding, query_embedding: List[float]) -> float:
    """Plain-Python cosine distance for the in-process similarity threshold
    filter (mirrors `context_builder._cosine_distance` exactly — the DB-level
    ORDER BY already used `cosine_distance`; this recomputes the same metric
    on the already-fetched rows)."""
    a = list(embedding)
    b = query_embedding
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 1.0
    similarity = dot / (norm_a * norm_b)
    return 1 - similarity


def _assemble_bloque(row: EjemploCorreccion) -> str:
    """Render one captured example into a prompt block fragment.
    Neutralise-then-truncate (task 1): the delimiter tag pattern is stripped
    BEFORE truncation, so a delimiter sitting past the truncation cutoff is
    still neutralised (truncating first could leave an unmatched half-tag
    that's harmless, but also could preserve a full tag before the cutoff —
    order matters for the general case, not just this one)."""
    texto = _TAG_PATTERN.sub("[etiqueta]", row.texto)
    if len(texto) > _EJEMPLO_MAX_CHARS:
        texto = texto[:_EJEMPLO_MAX_CHARS]
    return f"- Texto: {texto}\n  Valor corregido ({row.campo}): {row.valor_corregido}\n"


def _assemble_bloques(rows: List[EjemploCorreccion]) -> List[str]:
    """Assemble prompt blocks for every row, applying per-example label
    re-validation against `VOCABULARIOS` (task 2): a row whose
    `valor_corregido` falls outside its field's closed vocabulary is dropped
    entirely — never substituted, never surfaced with the corrupted value."""
    bloques: List[str] = []
    for row in rows:
        vocabulario = VOCABULARIOS.get(row.campo)
        if vocabulario is None or row.valor_corregido not in vocabulario:
            logger.warning(
                "ejemplos_service: dropped example with out-of-vocabulary valor_corregido=%r for campo=%r",
                row.valor_corregido,
                row.campo,
            )
            continue
        bloques.append(_assemble_bloque(row))
    return bloques


def append_ejemplos_bloque(system_prompt: str, bloques: List[str]) -> str:
    """Append-only prompt assembly (task 6/7): an empty `bloques` list
    returns `system_prompt` UNCHANGED (byte-identical, no trailing
    whitespace difference) — the retrieval feature must be a true no-op on
    the prompt when there is nothing to add."""
    if not bloques:
        return system_prompt
    return system_prompt + _INSTRUCCION_EJEMPLOS + "".join(bloques)


async def recuperar_ejemplos(db: Session, campo: str, texto: str) -> List[EjemploCorreccion]:
    """Retrieve up to `_EJEMPLOS_K` similar captured corrections for `campo`,
    filtered to `_EJEMPLOS_SIMILARITY_MIN`. Returns `[]` on EVERY degradation
    path — never raises (mirrors `context_builder.load_few_shot_examples`'s
    fallback contract):
      1. `embed_query` returns `None` (embedder disabled/unavailable/failed)
         — `_similarity_query` is never even called in this case.
      2. `_similarity_query` raises for ANY reason (e.g. sqlite CI, a
         transient DB error) — caught and logged, never propagated.
      3. Zero rows returned, or all rows fall below the similarity floor.
    """
    query_embedding = await embed_query(texto)
    if query_embedding is None:
        return []

    try:
        rows = _similarity_query(db, campo, query_embedding, _EJEMPLOS_K)
    except Exception:  # noqa: BLE001 — retrieval must never break triage; fall back to nothing.
        logger.warning("recuperar_ejemplos: similarity query failed for campo=%r", campo, exc_info=True)
        return []

    return [row for row in rows if _cosine_distance(row.embedding, query_embedding) <= (1 - _EJEMPLOS_SIMILARITY_MIN)]


async def capturar_correccion(propuesta_id: int) -> None:
    """Best-effort: loads the confirmed correction, embeds its ticket's
    original text, and inserts one `tickets_triage_ejemplos` row. Never
    raises — flag off returns before any DB work, and any failure (missing
    row, embed failure, DB error) is swallowed here, logged, and skips the
    capture entirely (design: never insert a dead row with a
    null/placeholder embedding)."""
    if not settings.TICKETS_TRIAGE_EJEMPLOS_CAPTURE:
        # Checked BEFORE any session work: a flag-off capture must be a true
        # no-op, never a pool checkout (PR #811 pool-exhaustion lesson).
        return

    try:
        with get_background_db() as db:
            propuesta = db.query(PropuestaIA).filter(PropuestaIA.id == propuesta_id).first()
            if propuesta is None:
                return
            ticket = db.query(Ticket).filter(Ticket.id == propuesta.ticket_id).first()
            if ticket is None:
                return

            texto = ticket.texto_original
            ticket_id = ticket.id
            campo = propuesta.campo
            valor_ia = propuesta.valor_propuesto.get("valor") if propuesta.valor_propuesto else None
            valor_corregido = propuesta.valor_corregido

        if not texto or valor_ia is None or valor_corregido is None:
            # Nothing meaningful to embed/capture — skip rather than insert
            # a row with a null AI value or corrected value.
            return

        embedding = await embed_passage(texto)
        if embedding is None:
            # No session while calling embed_passage; a None result means
            # capture is skipped entirely — never a dead row with a
            # null/placeholder embedding.
            return

        with get_background_db() as db:
            db.add(
                EjemploCorreccion(
                    ticket_id=ticket_id,
                    propuesta_id=propuesta_id,
                    campo=campo,
                    texto=texto,
                    valor_ia=valor_ia,
                    valor_corregido=valor_corregido,
                    embedding=embedding,
                    active=True,
                )
            )
    except Exception:  # noqa: BLE001 — capture must never fail a real confirm.
        logger.warning(
            "tickets triage: correction capture failed for propuesta %s (best-effort, confirm unaffected)",
            propuesta_id,
            exc_info=True,
        )
