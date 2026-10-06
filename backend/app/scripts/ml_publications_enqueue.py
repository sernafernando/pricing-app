"""Enqueue items for refresh by hand (live verification of the ML publications store).

    python -m app.scripts.ml_publications_enqueue MLA935110613 MLA934406852 [--resources bundle]

Entries go in at lane 0 (manual, served first) and collapse with any entry already queued.
The CLI never calls ML: the refresh handler does, and only while `refresh.enabled` is on. With
it off the entries are still accepted and wait; the CLI says so. Run from `backend/`.
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Optional, Sequence

from app.services.ml_publications import queue, settings_store
from app.services.ml_publications.resources import BUNDLE_RESOURCE, REFRESH_RESOURCES

ITEM_ID = re.compile(r"^[A-Z]{3}\d+$")
DEFAULT_RESOURCE = BUNDLE_RESOURCE
KNOWN_RESOURCES = REFRESH_RESOURCES  # the one canonical list, shared with the refresh handler


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ml_publications_enqueue")
    parser.add_argument("item_ids", nargs="+", metavar="ITEM_ID", help="e.g. MLA935110613")
    parser.add_argument(
        "--resources",
        nargs="+",
        choices=KNOWN_RESOURCES,
        metavar="RESOURCE",
        default=[DEFAULT_RESOURCE],
        help=f"resources to refresh, any of: {', '.join(KNOWN_RESOURCES)} (default: {DEFAULT_RESOURCE})",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    invalid = [i for i in args.item_ids if not ITEM_ID.match(i)]
    if invalid:
        print(f"not an item id: {', '.join(invalid)} (expected something like MLA935110613)", file=sys.stderr)
        return 2
    queue.enqueue(
        [
            queue.EnqueueEntry(kind="item", entity_id=i, lane=queue.LANE_MANUAL, resources=tuple(args.resources))
            for i in dict.fromkeys(args.item_ids)
        ]
    )
    print(f"enqueued {len(set(args.item_ids))} item(s) at lane {queue.LANE_MANUAL}")
    if not settings_store.is_enabled("refresh"):
        print("processing is disabled: refresh.enabled is off, the entries wait until it is turned on")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
