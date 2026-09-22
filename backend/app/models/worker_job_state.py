"""Schedule/liveness state for `app/workers/` job handlers (ventas-ml-rediseno,
design D4, D6).

One row per `JobHandler.name` (e.g. `'worker'` for the process-wide heartbeat,
`'order_metrics.reconcile'`, `'order_metrics.divergence'`) so a restart does
not re-run a daily job twice (`last_success_at` compared against today's
slot) and the health endpoint (PR6) can read `heartbeat_at`/`detail` without
guessing at in-process state. PR1 ships the table alone, inert: no worker
exists yet to write to it (PR2+).
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class WorkerJobState(Base):
    __tablename__ = "worker_job_state"

    name = Column(String(64), primary_key=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    state = Column(String(32), nullable=True)
    detail = Column(JSONB, nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
