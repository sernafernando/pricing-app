"""One-shot: recompute `hay_mejores_ofertas` from the stored promotions mirror.

Applies the current `es_mejor_oferta` rules against each item's stored
`ml_item_seller_promotions.raw` and `ml_item_sale_prices.amount`. Does **not**
call MercadoLibre — use this after tightening criteria (or any logic change)
so the chooser stops showing false "hay mejores" badges.

Typical ops (post-deploy, as Fernando on the API/worker host):

    cd backend
    python -m app.scripts.recompute_hay_mejores_ofertas --dry-run --flagged-only
    python -m app.scripts.recompute_hay_mejores_ofertas --flagged-only

Optional canary / single MLA:

    python -m app.scripts.recompute_hay_mejores_ofertas --item-ids MLA3132338320 --dry-run
    python -m app.scripts.recompute_hay_mejores_ofertas --item-ids MLA3132338320

See `docs/RUNBOOKS.md` (§ Hay mejores — offline recompute).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.ml_publications import MlItemSellerPromotions
from app.services.ml_promotions_hay_mejores import FlagDecision, actualizar_hay_mejores_ofertas

logger = get_logger("scripts.recompute_hay_mejores_ofertas")


@dataclass
class RecomputeStats:
    considered: int = 0
    cleared: int = 0  # true → false
    still_flagged: int = 0  # true → true
    newly_flagged: int = 0  # false → true
    stayed_clear: int = 0  # false → false
    fingerprint_changed: int = 0
    failed: int = 0  # actualizar returned None
    sample_cleared: List[str] = field(default_factory=list)
    sample_still_flagged: List[str] = field(default_factory=list)

    def record(
        self,
        item_id: str,
        *,
        prev_flag: bool,
        prev_fp: Optional[str],
        decision: Optional[FlagDecision],
    ) -> None:
        self.considered += 1
        if decision is None:
            self.failed += 1
            return
        if prev_flag and not decision.hay_mejores:
            self.cleared += 1
            if len(self.sample_cleared) < 20:
                self.sample_cleared.append(item_id)
        elif prev_flag and decision.hay_mejores:
            self.still_flagged += 1
            if len(self.sample_still_flagged) < 20:
                self.sample_still_flagged.append(item_id)
        elif (not prev_flag) and decision.hay_mejores:
            self.newly_flagged += 1
        else:
            self.stayed_clear += 1
        if decision.fingerprint != prev_fp:
            self.fingerprint_changed += 1


def select_item_ids(
    db: Session,
    *,
    flagged_only: bool,
    item_ids: Optional[Sequence[str]],
    limit: Optional[int],
) -> List[str]:
    """Ordered MLA ids to recompute (stable by item_id)."""
    if item_ids:
        ids = list(dict.fromkeys(item_ids))
        if limit is not None:
            ids = ids[:limit]
        return ids
    q = db.query(MlItemSellerPromotions.item_id)
    if flagged_only:
        q = q.filter(MlItemSellerPromotions.hay_mejores_ofertas.is_(True))
    q = q.order_by(MlItemSellerPromotions.item_id)
    if limit is not None:
        q = q.limit(limit)
    return [row[0] for row in q.all()]


def recompute_items(
    db: Session,
    item_ids: Iterable[str],
    *,
    dry_run: bool,
    commit_every: int,
) -> RecomputeStats:
    """Recompute each id via `actualizar_hay_mejores_ofertas`; commit in batches unless dry_run."""
    stats = RecomputeStats()
    pending = 0
    for item_id in item_ids:
        row = db.query(MlItemSellerPromotions).filter(MlItemSellerPromotions.item_id == item_id).one_or_none()
        if row is None:
            logger.warning("hay_mejores recompute: no promotions row for %s", item_id)
            stats.failed += 1
            stats.considered += 1
            continue
        prev_flag = bool(row.hay_mejores_ofertas)
        prev_fp = row.hay_mejores_fingerprint
        decision = actualizar_hay_mejores_ofertas(db, item_id)
        stats.record(item_id, prev_flag=prev_flag, prev_fp=prev_fp, decision=decision)
        pending += 1
        if not dry_run and pending >= commit_every:
            db.commit()
            pending = 0
    if dry_run:
        db.rollback()
    elif pending:
        db.commit()
    return stats


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="recompute_hay_mejores_ofertas",
        description="Recompute hay_mejores_ofertas from the stored promotions + sale_price mirror (no ML calls).",
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--flagged-only",
        action="store_true",
        help="Only rows with hay_mejores_ofertas=true (default when neither flag is set).",
    )
    scope.add_argument(
        "--all",
        action="store_true",
        help="Every ml_item_seller_promotions row (slower; ~tens of thousands).",
    )
    parser.add_argument(
        "--item-ids",
        nargs="+",
        metavar="MLA",
        help="Explicit MLA list (overrides --flagged-only / --all).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Cap how many ids to process (canary).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and report; roll back all writes (including catalog enqueue side effects).",
    )
    parser.add_argument(
        "--commit-every",
        type=int,
        default=100,
        help="Commit every N items when not --dry-run (default 100).",
    )
    return parser.parse_args(argv)


def _print_stats(stats: RecomputeStats, *, dry_run: bool) -> None:
    mode = "DRY-RUN (rolled back)" if dry_run else "COMMITTED"
    print(f"hay_mejores recompute — {mode}")
    print(f"  considered:            {stats.considered}")
    print(f"  cleared (true→false):  {stats.cleared}")
    print(f"  still flagged:         {stats.still_flagged}")
    print(f"  newly flagged:         {stats.newly_flagged}")
    print(f"  stayed clear:          {stats.stayed_clear}")
    print(f"  fingerprint changed:   {stats.fingerprint_changed}")
    print(f"  failed / missing:      {stats.failed}")
    if stats.sample_cleared:
        print(f"  sample cleared:        {', '.join(stats.sample_cleared)}")
    if stats.sample_still_flagged:
        print(f"  sample still flagged:  {', '.join(stats.sample_still_flagged)}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    if args.commit_every < 1:
        print("--commit-every must be >= 1", file=sys.stderr)
        return 2
    flagged_only = not args.all
    db = SessionLocal()
    try:
        ids = select_item_ids(
            db,
            flagged_only=flagged_only,
            item_ids=args.item_ids,
            limit=args.limit,
        )
        print(f"selected {len(ids)} item(s) (flagged_only={flagged_only and not args.item_ids})")
        if not ids:
            print("nothing to do")
            return 0
        stats = recompute_items(
            db,
            ids,
            dry_run=args.dry_run,
            commit_every=args.commit_every,
        )
        _print_stats(stats, dry_run=args.dry_run)
        return 0 if stats.failed == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
