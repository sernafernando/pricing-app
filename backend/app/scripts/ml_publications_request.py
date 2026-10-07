"""Ask the ML worker to run one of its handlers on its next pass, regardless of schedule.

    python -m app.scripts.ml_publications_request ml_publications.refresh
    python -m app.scripts.ml_publications_request ml_publications.scan --mode full

Same mechanism as `POST /order-metrics/divergence/run`: sets `worker_job_state.state =
'requested'` and wakes the worker through `worker_jobs`. The runtime clears the flag only after
a SUCCESSFUL run, so a request made while the handler is disabled is honored once it is enabled.
`--mode full|rescan` (scan only) first writes `scan.next_mode`: `full` makes the next lap a backfill of
the statuses in `scan.statuses`, consumed when that lap completes; without `--mode` the lap is a rescan (or a backfill
when the store is empty). Run from `backend/`.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from typing import Optional, Sequence

from sqlalchemy import text

from app.core import database
from app.services.ml_publications import settings_store
from app.workers.registry import ML_PUBLICATIONS_REGISTRY

SCAN_HANDLER = "ml_publications.scan"


def _actor() -> str:
    """Who ran the CLI, for `updated_by`; `getuser` raises when the uid has no passwd entry (containers)."""
    try:
        return f"cli:{getpass.getuser()}"
    except Exception:  # noqa: BLE001 -- a missing OS user must not block an operator request
        return "cli:unknown"


def main(argv: Optional[Sequence[str]] = None) -> int:
    known = sorted(handler.name for handler in ML_PUBLICATIONS_REGISTRY)
    parser = argparse.ArgumentParser(prog="ml_publications_request")
    parser.add_argument("handler", help=f"one of: {', '.join(known)}")
    parser.add_argument("--mode", choices=("full", "rescan"), help="scan only: kind of the next lap")
    args = parser.parse_args(argv)
    if args.handler not in known:
        print(f"unknown ML handler {args.handler!r}; known: {', '.join(known)}", file=sys.stderr)
        return 2
    if args.mode and args.handler != SCAN_HANDLER:
        print(f"--mode only applies to {SCAN_HANDLER}", file=sys.stderr)
        return 2
    with database.get_background_db() as db:
        if args.mode:  # same transaction as the request: the worker never sees one without the other
            settings_store.set_setting("scan.next_mode", args.mode, _actor(), session=db)
        db.execute(
            text(
                "INSERT INTO worker_job_state (name, state) VALUES (:name, 'requested') "
                "ON CONFLICT (name) DO UPDATE SET state = 'requested'"
            ),
            {"name": args.handler},
        )
        db.execute(text("SELECT pg_notify('worker_jobs', :name)"), {"name": args.handler})
    suffix = f" (next lap: {args.mode})" if args.mode else ""
    print(f"{args.handler} requested: it runs on the next worker pass{suffix}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
