"""Daily billing sweep (ml-ventas-desglose-costos, corte 3).

Downloads the ML billing period once a day and upserts every charge via
`upsert_billing_charge` (corte 2). Flag-gated (`ML_BILLING_ENABLED`,
default OFF): with the flag off this is a complete no-op, same
`PROMOS_WRITE_ENABLED` precedent as the rest of the app.

Hard constraint (investigation §3): ML's billing API enforces a rate limit
of 5 requests/minute PER ACCOUNT, shared with promos/PxQ/everything else --
NOT per endpoint. Consulting billing per-order would starve the account's
whole billing budget. The only safe pattern is downloading the full period
once a day, paginated, spaced >=15s apart (well under 4 requests/minute),
and reconciling by `order_id` afterwards (later cuts).

Lock reuse: this sweep is a SEPARATE cursor (`cursor_name='billing'`) on
the SAME lock/cursor machinery as `ml_orders_ingestion/sweep_service.py`
(`try_acquire_run_lock`/`load_cursor`/`ensure_cursor_row`/
`release_lock_as_*`), imported rather than re-implemented -- an
overlapping cron invocation of the ORDERS sweep and this billing sweep
never contend, because each holds its own row.

ASSUMPTION -- NOT YET CONFIRMED BY THE USER: temporal scope is ONLY the
currently OPEN billing period, re-swept ENTIRELY every day.

Which period is open is ASKED, not derived: `get_billing_periods` marks
each one `OPEN`/`CLOSED`, and that costs one request out of the ~20 this
sweep already makes. The 17th-to-16th boundary (investigation §3) survives
only as the fallback in `_derived_period_key`, for when that call times
out -- it is Mercado Libre's business rule, not ours, and deriving it would
sweep the wrong period in silence the day they move it. There is no
backfill of closed periods and no separate lag window: idempotent upsert
on `detail_id` makes a full daily re-sweep of the open period free, and
that subsumes the measured billing lag (median 1h, 99.5% within 24h, 100%
within 48h) without a dedicated overlap window.

Documents (PR 2b): after the details the sweep fetches the period's BILL
documents (`group=ML&document_type=BILL`) and upserts them into
`ml_billing_documents` with ML's own `count_details` and `amount`. Which
documents are complete is a query (`document_completeness`), reported on the
result and in the log, never stored; a document that is not complete is
retried by the next run's full re-sweep of the period.

Credit notes (PR 4b, BS-6): `run_billing_sweep(document_type="CREDIT_NOTE")` is
the same pass over `/details?document_type=CREDIT_NOTE` and the period's
CREDIT_NOTE documents. Purely additive: CN `detail_id`s are disjoint from the
BILL ones (0 overlap on 2026-09-01), `charge_bonified_id` stays in
`raw_detail`, and the cron entry point still runs BILL only (the worker
handler of PR 4c schedules both types).

The persistence steps of a pass (`persist_details_page`, `persist_documents`)
are separate functions so the worker lap of PR 4c can run them one request at a
time without this blocking loop.

`documents.count_details` (investigation §3 open discrepancy: 18,414 vs
18,743, a 329 difference with no known explanation) is persisted as an
OBSERVATION on `MlBillingPeriodStat` and is NEVER treated as an alarm or
raised as an exception -- doing so would produce a false alarm every
single day.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.dialects import postgresql, sqlite

from app.core.config import settings
from app.core.database import get_background_db
from app.models.ml_billing import MlBillingCharge, MlBillingPeriodStat
from app.services.ml_billing.document_completeness import document_completeness
from app.services.ml_billing_ingestion.ingestion_service import upsert_billing_charge, upsert_billing_document
from app.services.ml_billing_ingestion.mapper import MappingError, map_billing_detail, map_billing_document
from app.services.ml_orders_ingestion.sweep_service import (
    ensure_cursor_row,
    release_lock_as_error,
    release_lock_as_idle,
    try_acquire_run_lock,
)
from app.services.ml_webhook_client import ml_webhook_client
from app.utils.async_bridge import resolve_maybe_async

logger = logging.getLogger(__name__)

CURSOR_NAME = "billing"
BILLING_GROUP = "ML"
PAGE_LIMIT = 1000
# The default document type of a sweep. A sweep fetches exactly one type:
# `run_billing_sweep(document_type="CREDIT_NOTE")` is the general credit-note
# pass (BS-6). Which type runs when is the scheduler's business (PR 4c).
DOCUMENT_TYPE = "BILL"
DOCUMENT_TYPES = ("BILL", "CREDIT_NOTE")
# Hard bound on pages per pass, on top of the strictly advancing cursor.
# Only an empty page ends a pass (BS-1), so without a bound a misbehaving
# answer would hold the lock and spend one request of the account-wide budget
# every 15 s indefinitely. The bound derives from the FIRST page's `total`
# (rows remaining at the start): ceil(total / PAGE_LIMIT) pages, plus this
# margin for short pages (950-row pages measured in 2026-09) and rows that
# ML adds to the open period while the sweep runs.
PAGE_CAP_MARGIN = 10
# The proxy itself throttles to 1 call/15s and returns 429 without going to
# ML (investigation §3). Spacing our own requests at the same floor keeps
# us under the account's 5/minute ceiling with margin, instead of relying
# on the proxy to reject us.
REQUEST_SPACING_SECONDS = 15.0


@dataclass
class BillingSweepResult:
    ran: bool
    period_key: Optional[str] = None
    charges_seen: int = 0
    charges_upserted: int = 0
    charges_mapping_error: int = 0
    stopped_early: bool = False
    error: Optional[str] = None
    documents_upserted: int = 0
    # Documents whose stored rows do not match ML's count/amount (BS-3). Read
    # from a query after the upsert, never stored. The next run re-sweeps the
    # period and so retries them.
    incomplete_document_ids: list[str] = field(default_factory=list)


def _derived_period_key(now: datetime) -> str:
    """La clave del período abierto, DERIVADA de la fecha.

    Es el FALLBACK, no la fuente. Los períodos de ML van del 17 de un mes
    al 16 del siguiente y se nombran por el mes en que terminan (el que
    cubre 17/08-16/09 tiene clave `"2026-09-01"`). Ese corte se sostiene en
    los cuatro períodos que medimos, pero es una regla de negocio DE ML: si
    la cambian, derivarla acá nos haría barrer un período equivocado en
    silencio, y el chequeo de completitud compararía contra el total de
    otro período.

    `_resolve_open_period_key` pregunta primero; esto es lo que queda si esa
    llamada falla."""
    if now.day <= 16:
        year, month = now.year, now.month
    else:
        year, month = now.year, now.month + 1
        if month > 12:
            year += 1
            month = 1
    return f"{year:04d}-{month:02d}-01"


def _resolve_open_period_key(now: datetime, group: str) -> str:
    """Pregunta a ML cuál es el período abierto; deriva solo si no puede.

    `get_billing_periods` devuelve `period_status` por período (`"OPEN"` /
    `"CLOSED"`), así que la respuesta es autoritativa en vez de inferida.
    Cuesta UNA request de las ~20 que hace el barrido, una vez por día:
    barato al lado de barrer el período equivocado sin enterarse.

    Si la llamada falla -- timeout, 429, proxy caído -- cae al derivado y lo
    loguea, en vez de abortar la pasada entera por no poder confirmar algo
    que casi siempre coincide.
    """
    derived = _derived_period_key(now)
    try:
        payload = resolve_maybe_async(ml_webhook_client.get_billing_periods(group))
    except Exception as e:
        logger.warning(f"sync_ml_billing: no se pudo consultar los períodos, uso el derivado {derived}: {e}")
        return derived

    results = (payload or {}).get("results") or []
    for entry in results:
        if isinstance(entry, dict) and entry.get("period_status") == "OPEN":
            key = entry.get("key")
            if key:
                if key != derived:
                    logger.warning(
                        f"sync_ml_billing: ML dice que el período abierto es {key} y el derivado da "
                        f"{derived} -- gana ML. Si esto se repite, el corte 17-16 cambió."
                    )
                return str(key)

    logger.warning(f"sync_ml_billing: ML no marcó ningún período como OPEN, uso el derivado {derived}")
    return derived


def _cursor_value(cursor) -> Optional[int]:
    """The cursor as an int, or None when it is not a usable id.

    Compared numerically: ML sends `last_id` as an int, but a numeric string
    for the same id must not read as an advance."""
    try:
        return int(cursor)
    except (TypeError, ValueError):
        return None


def _page_cap(first_total: int) -> int:
    return -(-first_total // PAGE_LIMIT) + PAGE_CAP_MARGIN


def _highest_detail_id(raw_results: list) -> Optional[int]:
    """Cursor de respaldo cuando la página no trae `last_id`: el mayor
    `detail_id` numérico de las filas (el orden es ASC y `from_id` es
    exclusivo). None si ninguna fila trae un id utilizable."""
    ids: list[int] = []
    for raw in raw_results:
        raw_id = (raw.get("charge_info") or {}).get("detail_id") if isinstance(raw, dict) else None
        try:
            ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue
    return max(ids) if ids else None


def _insert_stmt(db, table):
    """Same dialect pick as `ml_billing_ingestion/ingestion_service.py`."""
    dialect_name = db.bind.dialect.name if db.bind is not None else "postgresql"
    if dialect_name == "sqlite":
        return sqlite.insert(table)
    return postgresql.insert(table)


def _upsert_period_stat(
    db,
    period_key: str,
    reported_total: Optional[int],
    stored_total: int,
    documents_count_details: Optional[int],
    swept_at: datetime,
) -> None:
    """Upserts on `period_key` -- requires the unique constraint added by
    this cut's migration (corte 1 left `ml_billing_period_stats` without
    one, deliberately, since it had no writer yet)."""
    values = {
        "period_key": period_key,
        "reported_total": reported_total,
        "stored_total": stored_total,
        "documents_count_details": documents_count_details,
        "swept_at": swept_at,
    }
    stmt = _insert_stmt(db, MlBillingPeriodStat.__table__).values(**values)
    update_cols = {k: stmt.excluded[k] for k in values if k != "period_key"}
    stmt = stmt.on_conflict_do_update(index_elements=["period_key"], set_=update_cols)
    db.execute(stmt)


@dataclass
class PersistedDocuments:
    count_details: int
    upserted: int
    incomplete_ids: list[str]


def persist_details_page(
    db, raw_results: list, period_key: str, document_type: str, billing_source: str = "general"
) -> tuple[int, int, int]:
    """Maps and upserts one `/details` page. Returns (seen, upserted, mapping_errors).

    Shared by the cron-style pass below and the worker lap (`billing_lap`). The
    caller commits."""
    upserted = errors = 0
    for raw in raw_results:
        mapped = map_billing_detail(raw, period_key, document_type=document_type, billing_source=billing_source)
        if isinstance(mapped, MappingError):
            errors += 1
            logger.warning("sync_ml_billing: mapping error (period=%s): %s", period_key, mapped.reason)
            continue
        upsert_billing_charge(db, mapped)
        upserted += 1
    return len(raw_results), upserted, errors


def persist_documents(db, documents: dict, period_key: str, group: str, document_type: str) -> PersistedDocuments:
    """Upserts the documents of a `/documents` answer and reads which are incomplete.

    The capture stored the list under `results`; the earlier cut read
    `documents`. Either is accepted so a wrong guess about the envelope cannot
    silently drop them all. The caller commits."""
    raw_documents = [
        doc for doc in (documents.get("results") or documents.get("documents") or []) if isinstance(doc, dict)
    ]
    upserted = 0
    for raw_document in raw_documents:
        mapped_document = map_billing_document(raw_document, period_key, group)
        if isinstance(mapped_document, MappingError):
            logger.warning(
                "sync_ml_billing: document mapping error (period=%s): %s", period_key, mapped_document.reason
            )
            continue
        upsert_billing_document(db, mapped_document)
        upserted += 1
    db.flush()
    incomplete = [c.document_id for c in document_completeness(db, period_key, document_type) if not c.complete]
    if incomplete:
        logger.warning(
            "sync_ml_billing: documents incomplete (period=%s): %s -- the next run re-sweeps the period",
            period_key,
            incomplete,
        )
    return PersistedDocuments(
        count_details=sum(int(doc.get("count_details") or 0) for doc in raw_documents),
        upserted=upserted,
        incomplete_ids=incomplete,
    )


def run_billing_sweep(group: str = BILLING_GROUP, document_type: str = DOCUMENT_TYPE) -> BillingSweepResult:
    """Entry point for the cron sweep (`app/scripts/sync_ml_billing.py`).

    Flag-gated: a complete no-op (zero HTTP calls, zero DB writes/reads)
    while `ML_BILLING_ENABLED` is False.

    `document_type` is `BILL` (the cron's call) or `CREDIT_NOTE` (BS-6). A
    credit-note pass is additive: its detail ids are disjoint from BILL's, it
    upserts its own rows and documents, and it leaves the period observation
    (`MlBillingPeriodStat`, about the BILL details) alone.
    """
    if document_type not in DOCUMENT_TYPES:
        raise ValueError(f"document_type inválido: {document_type!r} (esperado {' o '.join(DOCUMENT_TYPES)})")
    if not settings.ML_BILLING_ENABLED:
        return BillingSweepResult(ran=False)

    now = datetime.now(timezone.utc)

    with get_background_db() as db:
        ensure_cursor_row(db, cursor_name=CURSOR_NAME)
        acquired = try_acquire_run_lock(db, now, cursor_name=CURSOR_NAME)
        if not acquired:
            logger.info("sync_ml_billing: another billing sweep run is already in flight, skipping this pass")
            return BillingSweepResult(ran=False, error="already running")
        db.commit()

    # Después del lock, no antes: si dos crons se solapan, el segundo se va
    # sin haber gastado una request del presupuesto de 5/minuto que es de
    # toda la CUENTA. Ese gasto es justo lo que este módulo existe para
    # evitar, y resolverlo antes del lock lo reintroducía por la ventana.
    period_key = _resolve_open_period_key(now, group)

    result = BillingSweepResult(ran=True, period_key=period_key)

    try:
        with get_background_db() as db:
            from_id: int | str = 0
            # `total` es la cantidad de filas que QUEDAN después del cursor,
            # no el tamaño del período (capturado el 2026-10-07: 33260,
            # 32260, ... 310, 0). Por eso NO decide cuándo cortar: la regla
            # anterior comparaba los ids vistos contra él y cortaba a mitad
            # de camino (17.950 de 33.260 en 2026-09). El tamaño del período
            # es el `total` de la PRIMERA página; solo se guarda como
            # observación.
            reported_total: Optional[int] = None
            pages_fetched = 0

            while True:
                # ALWAYS space, including before the FIRST page.
                #
                # The spacing belongs to the PROXY (1 call/15s), not to this
                # loop, and `_resolve_open_period_key` has already spent a
                # call on `/monthly/periods` immediately above. An earlier
                # version skipped the wait on the first iteration -- as if
                # nothing had been requested yet -- so the two calls went
                # out back to back and the proxy answered 429 on the second
                # one, every single time.
                #
                # The sweep then did the right thing with the wrong input:
                # it stopped without retrying, because a 429 means the
                # access pattern is wrong. It was. The result is that this
                # sweep could NEVER complete a pass -- `ml_billing_charges`
                # stayed empty since the day it shipped, and every sale kept
                # reporting "falta el barrido de facturación".
                time.sleep(REQUEST_SPACING_SECONDS)

                page = resolve_maybe_async(
                    ml_webhook_client.get_billing_details(
                        period_key, group, limit=PAGE_LIMIT, from_id=from_id, document_type=document_type
                    )
                )
                if page is None:
                    # A 429 (proxy throttle) and a genuine transport error
                    # both surface as None here -- either way, the correct
                    # move is the SAME: stop this pass, log it, and let
                    # tomorrow's cron try again. NOT an immediate retry:
                    # retrying immediately is exactly the access pattern
                    # that burns the account's shared 5/minute budget.
                    logger.error(
                        "sync_ml_billing: get_billing_details failed (period=%s, group=%s, from_id=%s) "
                        "-- stopping this pass, no retry",
                        period_key,
                        group,
                        from_id,
                    )
                    result.stopped_early = True
                    result.error = "billing details request failed"
                    break

                # `total` viene en el NIVEL SUPERIOR. ML no manda ningún
                # objeto `paging`: leerlo de ahí daba None SIEMPRE, y con
                # None el chequeo de completitud de abajo no comparaba
                # nada -- callado, que es la peor forma de no funcionar.
                # Sin fallback a `paging` a propósito: dejarlo mantendría
                # viva la creencia que este arreglo viene a enterrar.
                page_total = page.get("total")
                if reported_total is None and isinstance(page_total, int):
                    reported_total = page_total

                raw_results = list(page.get("results") or [])
                seen, upserted, errors = persist_details_page(db, raw_results, period_key, document_type)
                result.charges_seen += seen
                result.charges_upserted += upserted
                result.charges_mapping_error += errors

                db.commit()

                # Solo una página VACÍA termina la pasada (BS-1). Una página
                # corta (ML devolvió 950 filas con limit=1000 dos veces en
                # 2026-09) no es el final: se sigue desde su cursor.
                if not raw_results:
                    break

                next_from_id = page.get("last_id")
                if next_from_id is None:
                    next_from_id = _highest_detail_id(raw_results)
                next_value = _cursor_value(next_from_id)
                if next_value is None or next_value <= _cursor_value(from_id):
                    # El cursor no avanzó (o retrocedió, o no es un id).
                    # Sin esto la pasada cicla para
                    # siempre re-escribiendo la misma página: mientras
                    # `total` fue None, lo único que terminaba un barrido
                    # era que la request fallara.
                    logger.warning(
                        "sync_ml_billing: el cursor no avanzó (period=%s, group=%s, from_id=%s, last_id=%s) "
                        "-- corto la pasada para no ciclar",
                        period_key,
                        group,
                        from_id,
                        next_from_id,
                    )
                    result.stopped_early = True
                    result.error = "billing pagination cursor did not advance"
                    break
                from_id = next_from_id

                pages_fetched += 1
                if reported_total is not None and pages_fetched >= _page_cap(reported_total):
                    logger.warning(
                        "sync_ml_billing: la pasada superó las páginas esperadas (period=%s, group=%s, "
                        "pages=%s, first_total=%s) -- corto para no gastar el presupuesto de requests",
                        period_key,
                        group,
                        pages_fetched,
                        reported_total,
                    )
                    result.stopped_early = True
                    result.error = "billing pagination exceeded the expected number of pages"
                    break

            if not result.stopped_early:
                documents_count_details: Optional[int] = None
                # Spaced like every other proxy call, for the same reason:
                # the last details page went out moments ago, and firing
                # this one immediately after got a 429 every time. The
                # completeness check then silently never ran -- the pass
                # still reported "complete", which is the one thing this
                # module is not allowed to do.
                time.sleep(REQUEST_SPACING_SECONDS)
                documents = resolve_maybe_async(
                    ml_webhook_client.get_billing_documents(period_key, group, document_type)
                )
                if documents is not None:
                    persisted = persist_documents(db, documents, period_key, group, document_type)
                    documents_count_details = persisted.count_details
                    if reported_total is not None and documents_count_details != reported_total:
                        # OBSERVATION only -- see module docstring. Never
                        # raised, never blocks, never marks the pass as an
                        # error.
                        logger.info(
                            "sync_ml_billing: documents.count_details=%s differs from details.total=%s "
                            "(period=%s) -- known open discrepancy, recorded as observation only",
                            documents_count_details,
                            reported_total,
                            period_key,
                        )
                    result.documents_upserted = persisted.upserted
                    result.incomplete_document_ids = persisted.incomplete_ids

                if document_type == DOCUMENT_TYPE:
                    # The observation is about the BILL details (their first
                    # `total`, their documents' count), so its stored side
                    # counts BILL rows only: credit-note rows are in the
                    # same table and must not inflate it.
                    stored_total = (
                        db.query(MlBillingCharge).filter_by(period_key=period_key, document_type=DOCUMENT_TYPE).count()
                    )
                    _upsert_period_stat(
                        db,
                        period_key=period_key,
                        reported_total=reported_total,
                        stored_total=stored_total,
                        documents_count_details=documents_count_details,
                        # El FIN del barrido, no el inicio: `now` se capturó
                        # antes de ~19 páginas espaciadas 15s, o sea unos 5
                        # minutos antes. En una tabla de reconciliación,
                        # `swept_at` tiene que ser el momento en que los datos
                        # quedaron consistentes.
                        swept_at=datetime.now(timezone.utc),
                    )
                db.commit()
    except Exception as e:  # noqa: BLE001 -- fail-closed: release the lock as errored, never leave it stuck
        release_lock_as_error(e, cursor_name=CURSOR_NAME)
        result.error = str(e)
        return result

    release_lock_as_idle(now, complete=not result.stopped_early, cursor_name=CURSOR_NAME)
    return result
