"""Seed minimal tb_mercadolibre_items_publicados rows for PARA GANAR sandbox.

Only active `publicaciones_ml` rows. Assigns official_store_id by marca:
  TP-LINK → 471846 (tplink clave / current id)
  everything else → 57997 (Gauss)

Idempotent: bulk-inserts missing MLAs, then refreshes store_id/title/item_id.
Usage (from backend/): python scripts/seed_para_ganar_publicados_stores.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, text

STORE_GAUSS = 57997
STORE_TPLINK = 471846


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
        inserted = conn.execute(
            text(
                """
                INSERT INTO tb_mercadolibre_items_publicados (
                  mlp_publicationid, item_id, mlp_itemtitle, mlp_active, mlp_official_store_id
                )
                SELECT
                  p.mla,
                  p.item_id,
                  p.item_title,
                  true,
                  CASE
                    WHEN UPPER(COALESCE(e.marca, '')) = 'TP-LINK' THEN :store_tplink
                    ELSE :store_gauss
                  END
                FROM publicaciones_ml p
                JOIN productos_erp e ON e.item_id = p.item_id
                WHERE p.activo = true
                  AND NOT EXISTS (
                    SELECT 1 FROM tb_mercadolibre_items_publicados m
                    WHERE m.mlp_publicationid = p.mla
                  )
                """
            ),
            {"store_tplink": STORE_TPLINK, "store_gauss": STORE_GAUSS},
        ).rowcount

        updated = conn.execute(
            text(
                """
                UPDATE tb_mercadolibre_items_publicados AS m
                SET
                  item_id = p.item_id,
                  mlp_itemtitle = p.item_title,
                  mlp_active = true,
                  mlp_official_store_id = CASE
                    WHEN UPPER(COALESCE(e.marca, '')) = 'TP-LINK' THEN :store_tplink
                    ELSE :store_gauss
                  END
                FROM publicaciones_ml p
                JOIN productos_erp e ON e.item_id = p.item_id
                WHERE m.mlp_publicationid = p.mla
                  AND p.activo = true
                """
            ),
            {"store_tplink": STORE_TPLINK, "store_gauss": STORE_GAUSS},
        ).rowcount

        by_store = (
            conn.execute(
                text(
                    """
                    SELECT m.mlp_official_store_id AS store_id, COUNT(*) AS n
                    FROM tb_mercadolibre_items_publicados m
                    JOIN publicaciones_ml p ON p.mla = m.mlp_publicationid AND p.activo = true
                    GROUP BY 1
                    ORDER BY n DESC
                    """
                )
            )
            .mappings()
            .all()
        )

    print(f"inserted_missing={inserted} refreshed={updated}")
    print("by store:", [dict(r) for r in by_store])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
