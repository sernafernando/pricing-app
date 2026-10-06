"""Ask the ML worker to run one of its handlers on its next pass, regardless of schedule.

    python -m app.scripts.ml_publications_request ml_publications.refresh

Same mechanism as `POST /order-metrics/divergence/run`: sets `worker_job_state.state =
'requested'` and wakes the worker through `worker_jobs`. The runtime clears the flag only after
a SUCCESSFUL run, so a request made while the handler is disabled is honored once it is enabled.
Run from `backend/`.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from sqlalchemy import text

from app.core import database
from app.workers.registry import ML_PUBLICATIONS_REGISTRY


def main(argv: Optional[Sequence[str]] = None) -> int:
    known = sorted(handler.name for handler in ML_PUBLICATIONS_REGISTRY)
    parser = argparse.ArgumentParser(prog="ml_publications_request")
    parser.add_argument("handler", help=f"one of: {', '.join(known)}")
    args = parser.parse_args(argv)
    if args.handler not in known:
        print(f"unknown ML handler {args.handler!r}; known: {', '.join(known)}", file=sys.stderr)
        return 2
    with database.get_background_db() as db:
        db.execute(
            text(
                "INSERT INTO worker_job_state (name, state) VALUES (:name, 'requested') "
                "ON CONFLICT (name) DO UPDATE SET state = 'requested'"
            ),
            {"name": args.handler},
        )
        db.execute(text("SELECT pg_notify('worker_jobs', :name)"), {"name": args.handler})
    print(f"{args.handler} requested: it runs on the next worker pass")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
