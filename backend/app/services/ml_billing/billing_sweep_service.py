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

`documents.count_details` (investigation §3 open discrepancy: 18,414 vs
18,743, a 329 difference with no known explanation) is persisted as an
OBSERVATION on `MlBillingPeriodStat` and is NEVER treated as an alarm or
raised as an exception -- doing so would produce a false alarm every
single day.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.dialects import postgresql, sqlite

from app.core.config import settings
from app.core.database import get_background_db
from app.models.ml_billing import MlBillingCharge, MlBillingPeriodStat
from app.services.ml_billing_ingestion.ingestion_service import upsert_billing_charge
from app.services.ml_billing_ingestion.mapper import MappingError, map_billing_detail
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


def run_billing_sweep(group: str = BILLING_GROUP) -> BillingSweepResult:
    """Entry point for the cron sweep (`app/scripts/sync_ml_billing.py`).

    Flag-gated: a complete no-op (zero HTTP calls, zero DB writes/reads)
    while `ML_BILLING_ENABLED` is False.
    """
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
            seen_in_period = 0
            total: Optional[int] = None
            first_request = True

            while True:
                if not first_request:
                    time.sleep(REQUEST_SPACING_SECONDS)
                first_request = False

                page = resolve_maybe_async(
                    ml_webhook_client.get_billing_details(period_key, group, limit=PAGE_LIMIT, from_id=from_id)
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
                if isinstance(page_total, int):
                    total = page_total

                raw_results = list(page.get("results") or [])
                for raw in raw_results:
                    result.charges_seen += 1
                    mapped = map_billing_detail(raw, period_key)
                    if isinstance(mapped, MappingError):
                        result.charges_mapping_error += 1
                        logger.warning("sync_ml_billing: mapping error (period=%s): %s", period_key, mapped.reason)
                        continue
                    upsert_billing_charge(db, mapped)
                    result.charges_upserted += 1

                db.commit()

                seen_in_period += len(raw_results)
                next_from_id = page.get("last_id")

                if not raw_results:
                    break
                if total is not None and seen_in_period >= total:
                    break
                if next_from_id is None or next_from_id == from_id:
                    # El cursor no avanzó. Sin esto la pasada cicla para
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

            if not result.stopped_early:
                documents_count_details: Optional[int] = None
                documents = resolve_maybe_async(ml_webhook_client.get_billing_documents(period_key, group))
                if documents is not None:
                    documents_count_details = sum(
                        int(doc.get("count_details") or 0)
                        for doc in (documents.get("documents") or [])
                        if isinstance(doc, dict)
                    )
                    if total is not None and documents_count_details != total:
                        # OBSERVATION only -- see module docstring. Never
                        # raised, never blocks, never marks the pass as an
                        # error.
                        logger.info(
                            "sync_ml_billing: documents.count_details=%s differs from details.total=%s "
                            "(period=%s) -- known open discrepancy, recorded as observation only",
                            documents_count_details,
                            total,
                            period_key,
                        )

                stored_total = db.query(MlBillingCharge).filter_by(period_key=period_key).count()
                _upsert_period_stat(
                    db,
                    period_key=period_key,
                    reported_total=total,
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
