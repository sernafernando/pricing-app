"""Rebuild the business events of the ML publications store from the stored change log.

    python -m app.scripts.ml_publications_events_rederive [--item MLA123] [--batch-size N]

Events are a projection of `ml_change_log`: each row's `changes` and `context` are enough
to derive them, so no current state and no ML call is involved. Existing events are left
alone (unique `dedupe_key`), which makes the command safe to repeat; use it after a rule
fix, or to fill events for rows written while `events.enabled` was off. Nothing is deleted.
Run from the `backend/` directory so the `.env` is found.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from app.core import database
from app.services.ml_publications import events_store


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ml_publications_events_rederive")
    parser.add_argument("--item", help="only the change-log rows of this item id")
    parser.add_argument("--batch-size", type=int, default=events_store.DEFAULT_BATCH_SIZE)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    if not 1 <= args.batch_size <= events_store.MAX_BATCH_SIZE:
        print(f"--batch-size must be between 1 and {events_store.MAX_BATCH_SIZE} (at most)", file=sys.stderr)
        return 2
    with database.get_background_db() as db:
        created = events_store.rederive_events(db, item_id=args.item, batch_size=args.batch_size)
    print(f"created {created} event{'' if created == 1 else 's'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
