"""One-time seed: manual product links from the ERP publication map for still-unlinked publications.

Reads `tb_mercadolibre_items_publicados` (`mlp_publicationid` -> `item_id`), the ONLY read of an ERP table
in the publications module, and only here: once the seed ran, the links live in our own
`ml_item_product_links` and the app never reads the ERP map again.

Candidates are item-level units (`variation_id = 0`) of stored items without live variations whose link is
automatic and still unlinked (`unmatched` or `conflict`). The ERP map has one product per publication, so it
cannot say which variation is which product: variation units are left to the operator.

Per candidate, in its own short transaction:
1. re-evaluate the item with the current automatic rule; a unit it now links is left automatic;
2. skip a publication the map does not know, one it maps to several products, or a product gone from
   `productos_erp`;
3. write a manual link (`note` = SEED_NOTE, no author) with its change-log row, under the row lock, only if
   the unit is still automatic and unlinked. Manual decisions and automatic links are never touched.

Dry-run by default: every transaction is rolled back, so the counts are what `--apply` would do.

    cd /var/www/html/pricing-app/backend
    venv/bin/python -m app.scripts.seed_vinculos_ml_desde_erp           # dry-run
    venv/bin/python -m app.scripts.seed_vinculos_ml_desde_erp --apply   # write
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core import database
from app.services.ml_publications import links

logger = logging.getLogger(__name__)

SEED_NOTE = "seed-erp: tb_mercadolibre_items_publicados"
MATCH_RULE = "erp_seed"
BATCH = 200
STATEMENT_TIMEOUT = "30s"
LOCK_TIMEOUT = "5s"
LOCK_NOT_AVAILABLE = "55P03"  # SQLSTATE of a lock_timeout

_CANDIDATES_SQL = """
SELECT l.item_id
FROM ml_item_product_links l
JOIN ml_items i ON i.item_id = l.item_id AND i.raw IS NOT NULL
WHERE l.variation_id = 0
  AND l.source = 'sku_auto'
  AND l.match_status IN ('unmatched', 'conflict')
  AND l.evaluated_at IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM ml_item_variations v WHERE v.item_id = l.item_id AND v.gone_at IS NULL)
  AND l.item_id > :after
ORDER BY l.item_id
LIMIT :size
"""

_ERP_MAP_SQL = """
SELECT DISTINCT item_id
FROM tb_mercadolibre_items_publicados
WHERE mlp_publicationid = :publication AND item_id IS NOT NULL
"""


@dataclass
class SeedCounts:
    candidates: int = 0  # unlinked automatic item-level units looked at
    seeded: int = 0  # manual links written (or that would be, in dry-run)
    relinked_auto: int = 0  # units the current automatic rule links on re-evaluation
    not_in_erp: int = 0  # publication absent from the ERP map
    ambiguous: int = 0  # the map gives several products for the publication
    product_missing: int = 0  # the mapped product is not in productos_erp
    busy: int = 0  # item or link row locked by another writer; a later run picks it up
    changed: int = 0  # the unit stopped being an automatic unlinked unit meanwhile


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _set_timeouts(db) -> None:
    db.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))


def _candidate_batch(after: str, size: int) -> list[str]:
    db = database.SessionLocal()
    try:
        _set_timeouts(db)
        return [r for (r,) in db.execute(text(_CANDIDATES_SQL), {"after": after, "size": size})]
    finally:
        db.rollback()
        db.close()


_OUTCOME_FIELD = {
    links.SEED_LINKED: "seeded",
    links.SEED_RELINKED_AUTO: "relinked_auto",
    links.SEED_PRODUCT_MISSING: "product_missing",
    links.SEED_CHANGED: "changed",
}


def _seed_one(db, item_id: str, now: datetime, events_enabled: bool, counts: SeedCounts) -> None:
    """Decide and (maybe) write one candidate inside the caller's transaction."""
    products = [p for (p,) in db.execute(text(_ERP_MAP_SQL), {"publication": item_id})]
    if not products:
        counts.not_in_erp += 1
        return
    if len(products) > 1:
        counts.ambiguous += 1
        return
    outcome = links.seed_manual_link(
        db, item_id, products[0], note=SEED_NOTE, match_rule=MATCH_RULE, now=now, events_enabled=events_enabled
    )
    name = _OUTCOME_FIELD[outcome]
    setattr(counts, name, getattr(counts, name) + 1)


def run(*, apply: bool, now: Callable[[], datetime] = _utcnow, batch: int = BATCH) -> SeedCounts:
    """Seed every candidate, one short transaction each; rolled back unless `apply`."""
    counts = SeedCounts()
    events_enabled = links.read_flag("events")
    after = ""
    while True:
        ids = _candidate_batch(after, batch)
        if not ids:
            return counts
        for item_id in ids:
            counts.candidates += 1
            db = database.SessionLocal()
            try:
                _set_timeouts(db)
                _seed_one(db, item_id, now(), events_enabled, counts)
                if apply:
                    db.commit()
                else:
                    db.rollback()
            except links.UnknownItem:
                db.rollback()
                counts.changed += 1
            except OperationalError as exc:
                db.rollback()
                if getattr(exc.orig, "pgcode", None) != LOCK_NOT_AVAILABLE:
                    raise
                counts.busy += 1  # another writer holds the item; a later run picks it up
            finally:
                db.close()
        after = ids[-1]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write the links (default: dry-run, nothing written)")
    args = parser.parse_args(argv)
    counts = run(apply=args.apply)
    print("APPLY" if args.apply else "DRY-RUN (nothing written; --apply to write)")
    for name, value in asdict(counts).items():
        print(f"  {name}: {value}")
    return 0


if __name__ == "__main__":
    import app.models  # noqa: F401 -- register every model before the first query

    raise SystemExit(main())
