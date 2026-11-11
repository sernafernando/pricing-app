"""One-shot: discard the 2026-11-11 factura_cargada backlog storm.

The first deploy of `compras.factura_cargada_alerts` fired every historical
`cargada` row that still had `alerta_disparada_at IS NULL` (marks from Sep–Nov),
creating ~1200 PENDIENTE notifs in one minute (67 docs × ~18 recipients).

Usage (prod / staging, with DATABASE_URL):

    python -m app.scripts.descartar_factura_cargada_backlog_notifs
    python -m app.scripts.descartar_factura_cargada_backlog_notifs --dry-run
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.database import SessionLocal


# The storm was a single minute; pad a few seconds for clock skew.
STORM_FROM = datetime(2026, 11, 11, 15, 26, 0, tzinfo=UTC)
STORM_TO = datetime(2026, 11, 11, 15, 27, 0, tzinfo=UTC)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count matching rows without updating.",
    )
    args = parser.parse_args()

    sql_count = text(
        """
        SELECT COUNT(*) FROM notificaciones
        WHERE tipo = 'compras.factura_cargada'
          AND fecha_creacion >= :from_ts
          AND fecha_creacion < :to_ts
          AND estado <> 'DESCARTADA'
        """
    )
    sql_update = text(
        """
        UPDATE notificaciones
        SET estado = 'DESCARTADA', leida = true
        WHERE tipo = 'compras.factura_cargada'
          AND fecha_creacion >= :from_ts
          AND fecha_creacion < :to_ts
          AND estado <> 'DESCARTADA'
        """
    )
    params = {"from_ts": STORM_FROM, "to_ts": STORM_TO}

    with SessionLocal() as db:
        n = int(db.execute(sql_count, params).scalar() or 0)
        print(f"matching non-DESCARTADA factura_cargada notifs in storm window: {n}")
        if args.dry_run:
            print("dry-run: no update")
            return
        result = db.execute(sql_update, params)
        db.commit()
        print(f"updated: {result.rowcount}")


if __name__ == "__main__":
    main()
