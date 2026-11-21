"""MLAs waiting for a "hay mejores ofertas" recompute, outside any date crossing or flag.

The costo SI drain (`costo_si/despues/pubml.py`, owner L15) appends the MLAs whose cost changed; the
`ml_promotions.hay_mejores_boundaries` handler recomputes them on its next tick and removes only the ones it
processed. They live in that handler's own `worker_job_state.detail['pending_ids']` (sorted, distinct, byte order:
the order the handler's cursor compares in), so no table or migration is needed.

Both writers change the list in ONE statement each (orchestrator Q8 (a)): the row lock of that statement serializes
the drain and the worker, and each re-reads the newest committed list under the lock (Postgres READ COMMITTED
re-evaluates `ON CONFLICT DO UPDATE` and `UPDATE` on the latest row version), so an id appended by one is never lost
by the other and an id removed is never brought back. The handler's own state write (`detail || {...}`) never carries
`pending_ids`, so it cannot clobber the list either.
"""

from __future__ import annotations

from typing import Iterable, List

from sqlalchemy import String, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.models.worker_job_state import WorkerJobState

HANDLER_NAME = "ml_promotions.hay_mejores_boundaries"
KEY = "pending_ids"

# The stored list as rows (a missing or non-array value counts as empty).
_ACTUALES = (
    "SELECT jsonb_array_elements_text(CASE WHEN jsonb_typeof(worker_job_state.detail -> 'pending_ids') = 'array' "
    "THEN worker_job_state.detail -> 'pending_ids' ELSE '[]'::jsonb END) AS v"
)

_AGREGAR_SQL = text(
    "INSERT INTO worker_job_state (name, detail) "
    "VALUES (:name, jsonb_build_object('pending_ids', to_jsonb(CAST(:ids AS text[])))) "
    "ON CONFLICT (name) DO UPDATE SET detail = jsonb_set("
    "COALESCE(worker_job_state.detail, '{}'::jsonb), '{pending_ids}', "
    f"(SELECT COALESCE(jsonb_agg(u.v ORDER BY u.v COLLATE \"C\"), '[]'::jsonb) FROM ({_ACTUALES} "
    "UNION SELECT unnest(CAST(:ids AS text[]))) u))"
).bindparams(bindparam("ids", type_=ARRAY(String)))

_QUITAR_SQL = text(
    "UPDATE worker_job_state SET detail = jsonb_set(detail, '{pending_ids}', "
    f"(SELECT COALESCE(jsonb_agg(u.v ORDER BY u.v COLLATE \"C\"), '[]'::jsonb) FROM ({_ACTUALES}) u "
    "WHERE u.v <> ALL(CAST(:ids AS text[])))) "
    "WHERE name = :name AND jsonb_typeof(detail -> 'pending_ids') = 'array'"
).bindparams(bindparam("ids", type_=ARRAY(String)))


def _ids(item_ids: Iterable[str]) -> List[str]:
    return sorted({item_id for item_id in item_ids if item_id})


def _es_postgres(db: Session) -> bool:
    return db.get_bind().dialect.name == "postgresql"


def agregar(db: Session, item_ids: Iterable[str]) -> None:
    """Append `item_ids` to the pending list (every other key of `detail` kept); no ids, no statement.
    Runs in the caller's transaction, which then holds the row lock until it commits."""
    ids = _ids(item_ids)
    if not ids:
        return
    if _es_postgres(db):
        db.execute(_AGREGAR_SQL, {"name": HANDLER_NAME, "ids": ids})
        return
    # SQLite unit tests: one connection, nothing to race with.
    row = db.get(WorkerJobState, HANDLER_NAME)
    if row is None:
        db.add(WorkerJobState(name=HANDLER_NAME, detail={KEY: ids}))
        return
    detail = dict(row.detail or {})
    actuales = detail.get(KEY) if isinstance(detail.get(KEY), list) else []
    detail[KEY] = sorted(set(actuales) | set(ids))
    row.detail = detail


def pendientes(db: Session) -> List[str]:
    """The pending MLAs, sorted (empty when the row or the key is missing)."""
    row = db.get(WorkerJobState, HANDLER_NAME)
    detail = row.detail if row is not None else None
    value = detail.get(KEY) if isinstance(detail, dict) else None
    return sorted(str(v) for v in value) if isinstance(value, list) else []


def quitar(db: Session, item_ids: Iterable[str]) -> None:
    """Remove ONLY `item_ids` from the pending list; ids appended meanwhile by another transaction stay."""
    ids = _ids(item_ids)
    if not ids:
        return
    if _es_postgres(db):
        db.execute(_QUITAR_SQL, {"name": HANDLER_NAME, "ids": ids})
        return
    row = db.get(WorkerJobState, HANDLER_NAME)
    if row is None or not isinstance((row.detail or {}).get(KEY), list):
        return
    detail = dict(row.detail)
    detail[KEY] = [v for v in detail[KEY] if v not in set(ids)]
    row.detail = detail
