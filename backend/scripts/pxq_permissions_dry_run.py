"""Read-only dry-run for the PxQ permissions backfill (task 2c.20).

Reports how many roles / individual users would be granted
`pxq.ver`/`pxq.escribir`, and how many negative overrides would be copied,
by `app.services.pxq_permissions_backfill.backfill_pxq_permissions_from_promos`
— WITHOUT writing anything (`dry_run=True`). Run this against a
production-like or staging dataset and record the printed counts in the PR
description BEFORE the `20260801_pxq_permisos_backfill` migration is applied
to any real environment.

Usage:
    cd backend && DATABASE_URL=<staging-or-prod-url> ./.venv/bin/python -m scripts.pxq_permissions_dry_run

This script commits NOTHING: it opens a session, runs the dry-run query, and
rolls back unconditionally, even though `dry_run=True` never stages writes.
"""

from __future__ import annotations

from app.core.database import SessionLocal
from app.services.pxq_permissions_backfill import backfill_pxq_permissions_from_promos


def main() -> None:
    db = SessionLocal()
    try:
        counts = backfill_pxq_permissions_from_promos(db, dry_run=True)
        db.rollback()  # dry_run never stages writes, but never trust it implicitly
        print("PxQ permissions backfill — DRY RUN (nothing was written)")
        print(f"  roles that would be granted pxq.ver/pxq.escribir:      {counts['roles_granted']}")
        print(f"  individual users that would be granted (positive):     {counts['users_granted']}")
        print(f"  negative overrides that would be copied (concedido=false): {counts['negative_overrides_copied']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
