"""Health + on-demand divergence trigger for the stored-metrics worker
(ventas-ml-rediseno PR6, design D9, D10, D13).

Two endpoints only:
- `GET /order-metrics/health` (perm `ml_ops.ver`): read-only aggregate over
  `app.services.order_metrics.health`. This is what the user polls to
  decide whether the D10 production gate (backlog drained, divergence
  zero, no hidden parked orders) can be accepted -- see the module
  docstring of `app/services/order_metrics/health.py`.
- `POST /order-metrics/divergence/run` (perm `ml_ops.gestionar`, the
  closest existing admin-level write permission in this router family --
  distinct from the read-only `ml_ops.ver`): sets
  `worker_job_state.state='requested'` and notifies `pg_notify('worker_jobs',
  name)`. NEVER runs the divergence scan inline -- the worker picks it up
  on its own next wake via the `worker_jobs` LISTEN channel
  (`app/workers/runtime.py`).
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario
from app.models.worker_job_state import WorkerJobState
from app.services.order_metrics import health as order_metrics_health
from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION
from app.services.permisos_service import PermisosService

router = APIRouter(prefix="/ml-ops", tags=["ML Order Metrics"])


def require_permission(permission: str):
    """Dependency for a required permission code -- same pattern as
    `ml_ventas_ops.py`/`document_templates.py`/`alertas.py`, reused rather
    than reinvented."""

    def _check_permission(
        current_user: Usuario = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> Usuario:
        permisos_service = PermisosService(db)
        if not permisos_service.tiene_permiso(current_user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No tienes permiso: {permission}",
            )
        return current_user

    return _check_permission


class PoisonedOrderSummary(BaseModel):
    order_id: int
    last_error: Optional[str]


class LastDivergenceSummary(BaseModel):
    run_at: Optional[str] = None
    divergent_count: Optional[int] = None
    missing_count: Optional[int] = None
    checked_count: Optional[int] = None
    # A full lap over `ml_order_metrics` -- possibly spread across many
    # runs -- has finished traversing the whole table since it last wrapped
    # around (PR6 review fix H1). `divergent_count=0` proves NOTHING about
    # the gate while `complete` is False or missing: a run bounded by the
    # handler's own deadline only ever inspects a slice of the table, and
    # an old summary written before this fix carries no `complete` key at
    # all -- treat that as unknown, never as clean.
    complete: Optional[bool] = None


class OrderMetricsHealthResponse(BaseModel):
    queue_depth: int
    oldest_dirty_age_s: Optional[float]
    claimed_count: int
    # Orders with NO `ml_order_metrics` row at all, parked ones excluded
    # (those are reported separately as `poisoned_count`/`poisoned_orders`).
    # This is the figure the D10 production gate reads: it must reach 0
    # before the stored values can be trusted. Do NOT confuse it with
    # `last_divergence.missing_count`, which only covers orders that
    # ALREADY have a row and whose fresh compute came back empty -- that
    # one reads 0 on a completely un-backfilled database.
    missing_metrics_count: int
    # TRUE total of parked orders (`health.poisoned_count`, unlimited) --
    # NEVER `len(poisoned_orders)` (PR6 review fix J1: `poisoned_orders` is
    # capped at its own `limit` and silently undercounts a large backlog).
    poisoned_count: int
    # A SAMPLE only, capped at `poisoned_orders`'s own `limit` (currently
    # 50) -- NOT exhaustive. Read `poisoned_count` for the true total.
    poisoned_orders: List[PoisonedOrderSummary]
    worker_heartbeat_at: Optional[str]
    worker_alive: bool
    worker_draining: bool
    listener_mode: Optional[str]
    last_divergence: Optional[LastDivergenceSummary]
    formula_version: int


class DivergenceRunResponse(BaseModel):
    state: str


def _worker_state_row(db: Session):
    return db.query(WorkerJobState).filter(WorkerJobState.name == "worker").first()


def _divergence_state_row(db: Session):
    return db.query(WorkerJobState).filter(WorkerJobState.name == "order_metrics.divergence").first()


@router.get("/order-metrics/health", response_model=OrderMetricsHealthResponse)
def get_order_metrics_health(
    current_user: Usuario = Depends(require_permission("ml_ops.ver")),
    db: Session = Depends(get_db),
) -> OrderMetricsHealthResponse:
    """Read-only observability endpoint (design D9). Requires `ml_ops.ver`.
    Never mutates anything -- safe to poll continuously while the D10
    production gate is being watched."""
    # `poisoned` is a capped SAMPLE for the UI list; the count comes from
    # the unlimited `poisoned_count` helper, never from `len(poisoned)`
    # (PR6 review fix J1).
    poisoned = order_metrics_health.poisoned_orders(db)
    poisoned_total = order_metrics_health.poisoned_count(db)

    worker_row = _worker_state_row(db)
    heartbeat_at = worker_row.heartbeat_at if worker_row is not None else None
    # PR11.T6: shared with `GET /sales/kpis`'s own `worker_alive` field --
    # `order_metrics_health.worker_alive` is the single implementation of
    # this threshold check now, not two copies.
    worker_alive = order_metrics_health.worker_alive(db)
    worker_draining = bool((worker_row.detail or {}).get("draining")) if worker_row is not None else False
    listener_mode = (worker_row.detail or {}).get("listener_mode") if worker_row is not None else None

    divergence_row = _divergence_state_row(db)
    last_divergence = None
    if divergence_row is not None and divergence_row.detail:
        last_divergence = LastDivergenceSummary(
            run_at=divergence_row.detail.get("run_at"),
            divergent_count=divergence_row.detail.get("divergent_count"),
            missing_count=divergence_row.detail.get("missing_count"),
            checked_count=divergence_row.detail.get("checked_count"),
            complete=divergence_row.detail.get("complete"),
        )

    return OrderMetricsHealthResponse(
        queue_depth=order_metrics_health.queue_depth(db),
        oldest_dirty_age_s=order_metrics_health.oldest_dirty_age_seconds(db),
        claimed_count=order_metrics_health.claimed_count(db),
        missing_metrics_count=order_metrics_health.missing_metrics_count(db),
        poisoned_count=poisoned_total,
        poisoned_orders=[PoisonedOrderSummary(order_id=row.order_id, last_error=row.last_error) for row in poisoned],
        worker_heartbeat_at=heartbeat_at.isoformat() if heartbeat_at is not None else None,
        worker_alive=worker_alive,
        worker_draining=worker_draining,
        listener_mode=listener_mode,
        last_divergence=last_divergence,
        formula_version=CURRENT_FORMULA_VERSION,
    )


@router.post(
    "/order-metrics/divergence/run",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DivergenceRunResponse,
)
def trigger_divergence_run(
    current_user: Usuario = Depends(require_permission("ml_ops.gestionar")),
    db: Session = Depends(get_db),
) -> DivergenceRunResponse:
    """On-demand divergence trigger (design D10). Requires `ml_ops.gestionar`
    (distinct from the read-only `ml_ops.ver`). NEVER runs the scan inline:
    only sets `worker_job_state.state='requested'` for
    `order_metrics.divergence` and notifies `worker_jobs` -- the worker's
    own listener (`app/workers/runtime.py`) picks it up on its next wake."""
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(WorkerJobState.__table__).values(name="order_metrics.divergence", state="requested")
        db.execute(stmt.on_conflict_do_update(index_elements=["name"], set_={"state": stmt.excluded.state}))
        db.execute(text("SELECT pg_notify('worker_jobs', 'order_metrics.divergence')"))
    else:
        from sqlalchemy.dialects import sqlite

        stmt = sqlite.insert(WorkerJobState.__table__).values(name="order_metrics.divergence", state="requested")
        db.execute(stmt.on_conflict_do_update(index_elements=["name"], set_={"state": stmt.excluded.state}))
    db.commit()
    return DivergenceRunResponse(state="requested")
