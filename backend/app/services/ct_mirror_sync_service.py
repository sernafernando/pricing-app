"""Short-window on-demand sync of `tb_commercial_transactions` from GBP.

Used by the factura-cargada alert sweep before auto-vínculo so a CT that
landed in GBP after the last GUID cron can still match. Date-window only —
GBP `scriptCommercial` has no supplier/docnumber filter.

HTTP runs with a tight timeout; callers must not hold an open write
transaction across the fetch (release with `session.commit()` first).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.commercial_transaction import CommercialTransaction
from app.scripts.sync_commercial_transactions_guid import (
    parse_bool,
    parse_datetime,
    parse_decimal,
    parse_int,
    parse_uuid,
)

logger = get_logger(__name__)

DEFAULT_DAYS: Final[int] = 2
DEFAULT_TIMEOUT_S: Final[float] = 20.0
# Cap payload size — scriptCommercial has no supplier filter; keep worker bounded.
MAX_FETCH_ROWS: Final[int] = 5000


def _ct_date_sort_key(record: dict[str, Any]) -> datetime:
    """Newest-first sort key; missing/unparseable dates sort last."""
    parsed = parse_datetime(record.get("ct_date"))
    if parsed is None:
        return datetime.min.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _fetch_window(*, days: int, timeout_s: float) -> list[dict[str, Any]]:
    # Explicit UTC calendar day so the window does not depend on server local TZ.
    hoy = datetime.now(UTC).date()
    fecha_hasta = datetime.combine(hoy, datetime.max.time()).replace(microsecond=0)
    fecha_desde = datetime.combine(hoy - timedelta(days=days), datetime.min.time())
    params = {
        "strScriptLabel": "scriptCommercial",
        "fromDate": fecha_desde.strftime("%Y-%m-%d %H:%M:%S"),
        "toDate": fecha_hasta.strftime("%Y-%m-%d %H:%M:%S"),
    }
    # Per-operation timeouts (connect + read), not one wall-clock budget for the
    # whole client lifetime. Connect is capped so a dead host fails fast.
    timeout = httpx.Timeout(timeout_s, connect=min(5.0, timeout_s))
    with httpx.Client(timeout=timeout) as client:
        response = client.get(settings.GBP_PARSER_URL, params=params)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, list) or not data:
        return []
    if len(data) == 1 and "Column1" in data[0]:
        return []
    if len(data) > MAX_FETCH_ROWS:
        logger.warning(
            "ct_mirror_sync: truncating GBP payload %s → %s rows (keeping newest by ct_date)",
            len(data),
            MAX_FETCH_ROWS,
        )
        ranked = sorted(data, key=_ct_date_sort_key, reverse=True)
        return ranked[:MAX_FETCH_ROWS]
    return data


def _row_datos(record: dict[str, Any], *, ct_transaction: int, ct_guid: UUID) -> dict[str, Any]:
    """Map GBP payload → columns needed for matching + a consistent mirror row."""
    return {
        "comp_id": parse_int(record.get("comp_id")),
        "bra_id": parse_int(record.get("bra_id")),
        "ct_transaction": ct_transaction,
        "ct_pointOfSale": parse_int(record.get("ct_pointOfSale")),
        "ct_kindOf": record.get("ct_kindOf"),
        "ct_docNumber": record.get("ct_docNumber"),
        "ct_date": parse_datetime(record.get("ct_date")),
        "supp_id": parse_int(record.get("supp_id")),
        "ct_subtotal": parse_decimal(record.get("ct_subtotal")),
        "ct_total": parse_decimal(record.get("ct_total")),
        "curr_id_transaction": parse_int(record.get("curr_id_transaction")),
        "ct_Pending": parse_bool(record.get("ct_Pending")),
        "ct_isCancelled": parse_bool(record.get("ct_isCancelled")),
        # str for SQLite unit tests; Postgres UUID column accepts the text form.
        "ct_guid": str(ct_guid),
        "df_id": parse_int(record.get("df_id")),
        "sd_id": parse_int(record.get("sd_id")),
    }


def upsert_cts_from_records(session: Session, records: list[dict[str, Any]]) -> list[int]:
    """Upsert by `ct_transaction` PK (GUID mirrored for Postgres identity). No commit."""
    if not records:
        return []
    incoming_cts = [ct for ct in (parse_int(r.get("ct_transaction")) for r in records) if ct is not None]
    existing_map: dict[int, CommercialTransaction] = {}
    if incoming_cts:
        existing = (
            session.query(CommercialTransaction).filter(CommercialTransaction.ct_transaction.in_(incoming_cts)).all()
        )
        existing_map = {int(row.ct_transaction): row for row in existing}

    cts_synced: list[int] = []
    for record in records:
        ct_transaction = parse_int(record.get("ct_transaction"))
        ct_guid = parse_uuid(record.get("ct_guid"))
        if not ct_transaction or not ct_guid:
            continue
        datos = _row_datos(record, ct_transaction=ct_transaction, ct_guid=ct_guid)
        existente = existing_map.get(ct_transaction)
        if existente is not None:
            for key, value in datos.items():
                if key != "ct_transaction":
                    setattr(existente, key, value)
        else:
            nuevo = CommercialTransaction(**datos)
            session.add(nuevo)
            existing_map[ct_transaction] = nuevo
        cts_synced.append(ct_transaction)
    session.flush()
    return cts_synced


def sync_recent_cts(
    session: Session,
    *,
    days: int = DEFAULT_DAYS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, int]:
    """Fetch a short GBP window and upsert. Best-effort; raises on HTTP errors.

    Caller should `session.commit()` (or equivalent) before this so the HTTP
    wait does not hold an open transaction / PgBouncer server connection.
    """
    records = _fetch_window(days=days, timeout_s=timeout_s)
    if not records:
        logger.info("ct_mirror_sync: empty window days=%s", days)
        return {"fetched": 0, "upserted": 0}
    cts = upsert_cts_from_records(session, records)
    logger.info(
        "ct_mirror_sync: days=%s fetched=%s upserted=%s",
        days,
        len(records),
        len(cts),
    )
    return {"fetched": len(records), "upserted": len(cts)}


__all__ = ["sync_recent_cts", "upsert_cts_from_records"]
