"""Print one worker's last heartbeat, for the deploy to tell a live worker from a hung one.

    python -m app.scripts.worker_heartbeat worker-ml

Prints the `worker_job_state.heartbeat_at` of the worker name as epoch seconds, or `none` when
the row (or its heartbeat) does not exist. Exit 1, with the reason on stderr and nothing on
stdout, when the database cannot be read. Used by `scripts/restart-verify-workers.sh`; run from
`backend/` so the `.env` is found.
"""

from __future__ import annotations

import sys
from datetime import timezone
from typing import Optional, Sequence

from app.core import database
from app.models.worker_job_state import WorkerJobState


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m app.scripts.worker_heartbeat <worker-name>", file=sys.stderr)
        return 2
    try:
        with database.get_background_db() as db:
            row = db.query(WorkerJobState.heartbeat_at).filter(WorkerJobState.name == args[0]).first()
    except Exception as exc:  # noqa: BLE001 -- the caller only needs "could not read"
        print(f"could not read the heartbeat: {exc}", file=sys.stderr)
        return 1
    heartbeat = row[0] if row else None
    if heartbeat is None:
        print("none")
        return 0
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    print(f"{heartbeat.timestamp():.3f}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
