"""Idempotent seed for ml_tiendas_oficiales (local sandbox / missing migration seed).

Mirrors alembic 20261006_ml_tiendas_oficiales SEED rows.
Usage (from backend/): python scripts/seed_ml_tiendas_oficiales.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, text

SEED = [
    (57997, "Gauss", 0, None),
    (2645, "TP-Link", 1, "tplink"),
    (471846, "TP-Link", 2, "tplink"),
    (144, "Forza/Verbatim", 3, None),
    (191942, "Multi-marca", 4, None),
]


def main() -> int:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    url = None
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not url:
        print("DATABASE_URL not found in backend/.env", file=sys.stderr)
        return 1

    engine = create_engine(url)
    with engine.begin() as conn:
        for store_id, nombre, orden, clave in SEED:
            conn.execute(
                text(
                    """
                    INSERT INTO ml_tiendas_oficiales (store_id, nombre, orden, clave, activa)
                    VALUES (:store_id, :nombre, :orden, :clave, true)
                    ON CONFLICT (store_id) DO UPDATE SET
                      nombre = EXCLUDED.nombre,
                      orden = EXCLUDED.orden,
                      clave = EXCLUDED.clave,
                      activa = true
                    """
                ),
                {"store_id": store_id, "nombre": nombre, "orden": orden, "clave": clave},
            )
        count = conn.execute(text("SELECT COUNT(*) FROM ml_tiendas_oficiales")).scalar_one()
    print(f"ml_tiendas_oficiales rows: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
