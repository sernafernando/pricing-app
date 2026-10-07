"""ODD `metricas-ml-tablero`, "Sin tabla resumen" ST1: the board reads the
tables we ALREADY have (orders, items, frozen costs, stored metrics, group
accreditation day) -- never a derived summary table.

Every window, markup, series, last sale and ageing comes from ONE per-order
base, so 24h <= 3d <= 7d <= 15d <= 30d holds by construction (production saw
24h=68 > 3d=53 when 24h came from the orders and the rest from an incomplete
rollup). The property test below checks every window against a brute-force
count in Python over randomly seeded sales.

"Today" is frozen at 2026-09-30 15:00 in Buenos Aires.
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.core.config import settings
from app.services.ml_daily_metrics import board
from tests.services.ml_daily_metrics.seed import Line, seed_group, seed_order, seed_sale

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 30)
BA = ZoneInfo("America/Argentina/Buenos_Aires")
WINDOWS = {"3d": 3, "7d": 7, "15d": 15, "30d": 30}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


def _rows(db, group_by: str = "product", **kwargs):
    f = board.BoardFilter(date_from=TODAY - timedelta(days=29), date_to=TODAY, group_by=group_by, **kwargs)
    with board.Board(db, f, scope_pairs=None) as b:
        return {row.key: row for row in b.page(None)}


def _at(day: date, hour: int = 15) -> datetime:
    """`hour` o'clock in Buenos Aires on `day`, as UTC."""
    return datetime(day.year, day.month, day.day, hour, tzinfo=BA).astimezone(timezone.utc)


class TestWindowsAreMonotonicAndExact:
    """Random sales over the last 96 days (lone orders, packs, multi-item
    orders, cancellations with and without ML coverage, sales a few minutes
    either side of midnight). Every window of every row must equal a
    brute-force count, and therefore 24h <= 3d <= 7d <= 15d <= 30d."""

    @pytest.mark.parametrize("seed", [7, 20261002])
    def test_every_window_matches_a_brute_force_count(self, db, seed):
        rng = random.Random(seed)
        catalogue = [(11, "MLA11A"), (11, "MLA11B"), (12, "MLA12A"), (13, "MLA13A"), (None, "MLA99Z")]
        sales = []  # (group_date, status, covered, [(product, mla, qty)])
        order_id = 2000050000000000
        for i in range(140):
            moment = NOW - timedelta(days=rng.randint(0, 95), minutes=rng.randint(0, 24 * 60 - 1))
            if i % 9 == 0:
                # Hug a Buenos Aires midnight: the day must be the LOCAL one.
                local = moment.astimezone(BA)
                moment = datetime(local.year, local.month, local.day, tzinfo=BA).astimezone(timezone.utc)
                moment += timedelta(minutes=rng.choice([-2, 2]))
                moment = min(moment, NOW)
            status, covered = "paid", None
            if i % 7 == 0:
                status, covered = "cancelled", rng.choice([True, None])
            members = []
            for _member in range(2 if i % 11 == 0 else 1):
                order_id += 1
                picks = rng.sample(catalogue, 2 if i % 5 == 0 else 1)
                lines = [Line(p, mla, rng.randint(1, 4), Decimal("100")) for p, mla in picks]
                seed_order(
                    db,
                    order_id,
                    moment,
                    lines,
                    tg="10",
                    costo="50",
                    status=status,
                    covered=covered,
                    pack_id=(900000 + i) if i % 11 == 0 else None,
                )
                members.append(order_id)
                sales.append(
                    (moment, status, covered, [(p or 0, mla, line.qty) for (p, mla), line in zip(picks, lines)])
                )
            key = f"p:{900000 + i}" if i % 11 == 0 else f"o:{members[0]}"
            seed_group(db, key, members, moment)
        db.commit()

        expected = {
            group_by: defaultdict(lambda: {"24h": 0, "units": 0, **{w: 0 for w in WINDOWS}})
            for group_by in ("product", "publication")
        }
        for moment, status, covered, lines in sales:
            if status == "cancelled" and not covered:
                continue
            day = moment.astimezone(BA).date()
            for product, mla, qty in lines:
                for group_by, key in (("product", str(product)), ("publication", mla)):
                    counts = expected[group_by][key]
                    if moment >= NOW - timedelta(hours=24):
                        counts["24h"] += qty
                    if TODAY - timedelta(days=29) <= day <= TODAY:
                        counts["units"] += qty
                    for name, days in WINDOWS.items():
                        if TODAY - timedelta(days=days - 1) <= day <= TODAY:
                            counts[name] += qty

        for group_by in ("product", "publication"):
            rows = _rows(db, group_by=group_by)
            for key, counts in expected[group_by].items():
                row = rows[key]
                got = {"24h": row.units_24h, "units": row.units, **row.windows}
                assert got == counts, (group_by, key)
                assert row.units_24h <= row.windows["3d"] <= row.windows["7d"] <= row.windows["15d"]
                assert row.windows["15d"] <= row.windows["30d"]


class TestSaleRules:
    def test_a_multi_item_order_splits_money_by_frozen_cost_share(self, db):
        """A: 1 x 300 frozen cost, B: 2 x 50 -> A takes 3/4 of the order's
        Total Gauss and cost, B 1/4."""
        seed_sale(
            db,
            1,
            _at(date(2026, 9, 20)),
            [Line(21, "MLA_A", 1, Decimal("500"), Decimal("300")), Line(22, "MLA_B", 2, Decimal("80"), Decimal("50"))],
            tg="80",
            costo="400",
        )

        rows = _rows(db)

        assert rows["21"].tg == pytest.approx(60) and rows["21"].costo == pytest.approx(300)
        assert rows["22"].tg == pytest.approx(20) and rows["22"].costo == pytest.approx(100)
        assert rows["21"].gross == pytest.approx(500) and rows["22"].gross == pytest.approx(160)
        assert rows["22"].units == 2
        assert float(rows["21"].markup) == pytest.approx(20)

    def test_unresolved_money_counts_units_but_not_money(self, db):
        seed_sale(db, 2, _at(date(2026, 9, 20)), [Line(11, "MLA1", 3, Decimal("100"))], gauss_status="unresolved")

        row = _rows(db)["11"]

        assert row.units == 3
        assert row.tg == 0
        assert row.markup is None
        assert row.gross == pytest.approx(300)

    @pytest.mark.parametrize("state", ["recalculating", "pending"])
    def test_an_order_whose_metrics_are_not_settled_counts_units_but_no_money(self, db, state):
        """Same exclusion as the Ventas ML KPIs (`aggregate.py`): an order
        being recalculated, never computed or parked contributes to NO sum,
        the gross included. Its units still sold."""
        seed_sale(
            db,
            3,
            _at(date(2026, 9, 20)),
            [Line(11, "MLA1", 2, Decimal("100"))],
            tg="20",
            costo="50",
            gauss_status=None if state == "pending" else "ok",
            dirty=state == "recalculating",
        )

        row = _rows(db)["11"]

        assert row.units == 2
        assert (row.gross, row.tg, row.markup) == (0, 0, None)

    def test_an_item_without_frozen_cost_is_product_zero(self, db):
        seed_sale(db, 4, _at(date(2026, 9, 20)), [Line(None, "MLA9", 1, Decimal("100"))], tg="5", costo="50")

        assert _rows(db)["0"].units == 1

    def test_a_sale_with_no_accreditation_is_in_no_day(self, db):
        seed_sale(db, 5, None, [Line(11, "MLA1", 1, Decimal("100"))], tg="5", costo="50")

        rows = _rows(db)
        assert "11" not in rows or rows["11"].units == 0

    def test_a_cancellation_counts_only_when_ml_covered_it(self, db):
        seed_sale(db, 6, _at(date(2026, 9, 20)), [Line(11, "MLA1", 1, Decimal("100"))], status="cancelled")
        seed_sale(
            db, 7, _at(date(2026, 9, 20)), [Line(12, "MLA2", 4, Decimal("100"))], status="cancelled", covered=True
        )

        rows = _rows(db)

        assert "11" not in rows or rows["11"].units == 0
        assert rows["12"].units == 4

    def test_a_pack_lands_on_its_group_day(self, db):
        seed_order(db, 8, _at(date(2026, 9, 20)), [Line(11, "MLA1", 1, Decimal("100"))], pack_id=77, tg="5", costo="50")
        seed_order(db, 9, _at(date(2026, 9, 28)), [Line(12, "MLA2", 1, Decimal("100"))], pack_id=77, tg="5", costo="50")
        seed_group(db, "p:77", [8, 9], _at(date(2026, 9, 28)))

        rows = _rows(db)

        assert rows["11"].windows["3d"] == rows["12"].windows["3d"] == 1

    def test_markup_of_a_pack_is_all_or_nothing(self, db):
        """Ventas ML's per-pack rule: a member without both values keeps the
        WHOLE pack out of the markup ratio; Total Gauss still shows what is
        known."""
        seed_order(
            db, 10, _at(date(2026, 9, 20)), [Line(11, "MLA1", 1, Decimal("100"))], pack_id=78, tg="30", costo="100"
        )
        seed_order(
            db, 11, _at(date(2026, 9, 20)), [Line(11, "MLA1", 1, Decimal("100"))], pack_id=78, gauss_status="unresolved"
        )
        seed_group(db, "p:78", [10, 11], _at(date(2026, 9, 20)))

        row = _rows(db)["11"]

        assert row.tg == pytest.approx(30)
        assert row.markup is None

    def test_two_variations_of_one_mla_go_to_their_own_products_in_every_window(self, db):
        seed_sale(
            db,
            12,
            NOW - timedelta(hours=2),
            [Line(11, "MLA1", 2, Decimal("100"), variation_id=1), Line(12, "MLA1", 3, Decimal("100"), variation_id=2)],
            tg="10",
            costo="50",
        )

        rows = _rows(db)

        assert (rows["11"].units_24h, rows["11"].windows["3d"]) == (2, 2)
        assert (rows["12"].units_24h, rows["12"].windows["3d"]) == (3, 3)

    def test_last_sale_and_ageing_come_from_the_whole_history(self, db):
        sold = _at(TODAY - timedelta(days=200))
        seed_sale(db, 13, sold, [Line(11, "MLA1", 1, Decimal("100"))], tg="5", costo="50")

        row = _rows(db)["11"]

        assert row.units == 0
        assert row.last_sale_at == sold
        assert row.ageing_days == 200
