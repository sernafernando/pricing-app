"""Read-only CSV backup of an allocation table to stdout, before a deploy that recomputes it.

One transaction marked `READ ONLY` (never a session-level SET: PgBouncer), `COPY ... TO STDOUT WITH CSV HEADER`
ordered by `id`, then rolled back. Only the tables in `TABLAS` can be dumped. Run from `backend/`:
    venv/bin/python -m app.scripts.backup_tabla_csv sell_out_consumos > /root/backups/sell_out_consumos_$(date +%F_%H%M).csv
"""

from __future__ import annotations

import sys
from typing import TextIO

TABLAS = frozenset({"sell_out_consumos", "sell_in_consumos", "sell_in_bono_consumos"})


def copy_sql(tabla: str) -> str:
    """The COPY statement for `tabla`; ValueError for a table outside `TABLAS`."""
    if tabla not in TABLAS:
        raise ValueError(f"tabla no permitida: {tabla!r} (permitidas: {', '.join(sorted(TABLAS))})")
    return f"COPY (SELECT * FROM {tabla} ORDER BY id) TO STDOUT WITH CSV HEADER"


def backup(tabla: str, out: TextIO) -> None:
    from app.core.database import engine

    sql = copy_sql(tabla)
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute("BEGIN")
        cur.execute("SET TRANSACTION READ ONLY")
        if hasattr(cur, "copy_expert"):  # psycopg2
            cur.copy_expert(sql, out)
        else:  # psycopg 3
            with cur.copy(sql) as cp:
                for chunk in cp:
                    out.write(bytes(chunk).decode())
        cur.execute("ROLLBACK")
    finally:
        raw.close()


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(f"uso: python -m app.scripts.backup_tabla_csv <{'|'.join(sorted(TABLAS))}>", file=sys.stderr)
        return 2
    try:
        backup(argv[0], sys.stdout)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
