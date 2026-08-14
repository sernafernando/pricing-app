#!/usr/bin/env python3
"""Cron entry point for `sync_category_embeddings()` (PR-1, tn-publisher-
module — design Decision 8).

Wiring only: `sync_category_embeddings()` itself is already implemented and
tested (`tests/services/test_tn_category_embedding_service.py`) and is not
modified here. This script exists so the sync can be scheduled independently
of the HTTP endpoint (`POST /api/tienda-nube-reconcile/categorias/sync`),
and exits non-zero on `skipped=True` so a cron failure is detectable
(spec ECS2).

Run:
    python -m app.scripts.sync_tn_category_embeddings

Cron:
    0 */6 * * * cd /var/www/html/pricing-app/backend && \
        /var/www/html/pricing-app/backend/venv/bin/python \
        -m app.scripts.sync_tn_category_embeddings \
        >> /var/log/pricing-app/tn-category-embeddings.log 2>&1
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    from dotenv import load_dotenv

    env_path = Path(backend_path) / ".env"
    load_dotenv(dotenv_path=env_path)

from app.core.database import SessionLocal  # noqa: E402
from app.services.tn_category_embedding_service import sync_category_embeddings  # noqa: E402


def main() -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db = SessionLocal()
    try:
        result = sync_category_embeddings(db)
        print(f"[{timestamp}] sync_tn_category_embeddings: {result}", flush=True)
        if result["skipped"]:
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
