"""pubml-lentitud L4: the stock audit's faster sums answer exactly what the old ones answered.

* `Sales.add` skips the days of a row's series with no units and no markup (most of its 90 days).
* `Sales.absorb` adds a row's sales in place instead of `plus` copying the group's growing per-day lists per row.

Both are compared field by field, values AND their exact representation (a Decimal `1.0` is not `1.00` on the wire),
against the old walk on invented rows with sparse series, markups, sell in / out, splits and ageings.
"""

from __future__ import annotations

import random
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.services.ml_daily_metrics import board
from app.services.ml_publications.view.stock_audit import Sales

DAYS = 90


def row(rng: random.Random, n: int) -> board.Row:
    days = sorted(rng.sample(range(DAYS), rng.randint(0, 12)))
    units = [0] * DAYS
    markup: list = [None] * DAYS
    for day in days:
        units[day] = rng.randint(0, 5)
        markup[day] = rng.choice([None, round(rng.uniform(-20, 90), 1)])
    sold = rng.random() < 0.7
    return board.Row(
        key=f"MLA{n}",
        product_item_id=n,
        mla=f"MLA{n}",
        units=sum(units),
        windows={"3d": 0, "7d": rng.randint(0, 9), "15d": 0, "30d": rng.randint(0, 30)},
        gross=Decimal(rng.randint(0, 10**6)) / 100,
        tg=Decimal(rng.randint(-(10**5), 10**5)) / 100,
        mtg=Decimal(rng.randint(-(10**5), 10**5)) / 100,
        costo=Decimal(rng.randint(0, 10**6)) / 100,
        sell_out=rng.choice([None, Decimal(rng.randint(0, 9999)) / 100]),
        series_units=units,
        series_markup=markup,
        last_sale_at=datetime(2026, 11, 1, tzinfo=timezone.utc) - timedelta(days=rng.randint(0, 99)) if sold else None,
        ageing_days=rng.choice([None, rng.randint(0, 400)]),
    )


def split(rng: random.Random):
    return rng.choice(
        [None, board.ShippingSplit(*(rng.randint(0, 4) for _ in range(len(fields(board.ShippingSplit)))))]
    )


def slow_add(total: Sales, r: board.Row, factor: Decimal, s) -> None:
    """`Sales.add` as it was: every day of the series walked (the empty ones add 0 to the units)."""
    series = total.add_series

    def every_day(series_units, series_markup, units_factor: Decimal) -> None:
        days = len(series_units)
        while len(total.series_units) < days:
            total.series_units.append(Decimal(0))
            total.series_markups.append([])
        for day, units in enumerate(series_units):
            total.series_units[day] += units * units_factor
            markup = series_markup[day] if day < len(series_markup) else None
            if markup is not None:
                total.series_markups[day].append((markup, units * units_factor))

    total.add_series = every_day
    try:
        total.add(r, factor, s)
    finally:
        total.add_series = series


def same(a: Sales, b: Sales) -> None:
    for f in fields(Sales):
        got, expected = getattr(a, f.name), getattr(b, f.name)
        if f.name == "series_markups":  # the points of each day; an empty day is any empty sequence
            got, expected = [list(points) for points in got], [list(points) for points in expected]
        assert got == expected, f.name
        assert repr(got) == repr(expected), f.name
    assert a.markup_series() == b.markup_series()


def test_skipping_the_empty_days_adds_what_adding_every_day_added() -> None:
    rng = random.Random(7)
    for _ in range(200):
        fast, slow = Sales(), Sales()
        for n in range(rng.randint(1, 6)):
            r, s, factor = row(rng, n), split(rng), Decimal(rng.choice([1, 1, 2, 3]))
            fast.add(r, factor, s)
            slow_add(slow, r, factor, s)
        same(fast, slow)


def test_absorbing_rows_in_place_is_folding_them_with_plus() -> None:
    rng = random.Random(11)
    for _ in range(100):
        parts = []
        for k in range(rng.randint(1, 30)):
            part = Sales()
            for n in range(rng.randint(0, 3)):
                part.add(row(rng, 100 * k + n), Decimal(1), split(rng))
            parts.append(part)
        folded, absorbed = Sales(), Sales()
        for part in parts:
            folded = folded.plus(part)
            absorbed.absorb(part)
        same(absorbed, folded)


def test_absorbing_never_changes_the_part_it_adds() -> None:
    rng = random.Random(3)
    part = Sales()
    part.add(row(rng, 1), Decimal(1), None)
    before = repr(part)
    total = Sales()
    total.absorb(part)
    total.absorb(part)
    assert repr(part) == before
